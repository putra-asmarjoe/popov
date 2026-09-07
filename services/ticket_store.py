"""
Ticket store — FE-3 Ticketing Core.
Collection: tickets (db popovagent_db).

Model 100% dari popov-frontend-plan.md + field tambahan:
- source: "manual" | "watchdog" (badge 🤖 Auto, FE-4)
- severityRank: int denormalisasi (0=critical..3=low) untuk sort severity
- *Name (createdByName, resolvedByName, progress.byName): snapshot nama saat event

Nomor tiket atomic: projects.ticketCounter di-$inc (anti-race, tanpa collection counter).
"""
import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from services.event_bus import emit
from services.mongodb_client import get_db
from services.workspace_store import PROJECTS_COLLECTION

logger = logging.getLogger(__name__)

TICKETS_COLLECTION = "tickets"
# Alias belajar dari link manual (Fix #246): raw devops → serviceId library kanonik.
SERVICE_ALIAS_COLLECTION = "service_aliases"

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
STATUS_CHAIN = {"new": 0, "open": 1, "in_progress": 2, "needs_review": 3, "resolved": 4, "closed": 5}
# Status tiket yang masih boleh menerima alert ter-link (dedup window auto-ticket)
OPEN_STATUSES = ("new", "open", "in_progress", "needs_review")
VALID_ENVIRONMENTS = ("production", "staging", "development")
VALID_KINDS = ("business_logic", "infrastructure")
VALID_SEVERITIES = tuple(SEVERITY_ORDER.keys())
# Sort whitelist (anti injection)
SORT_FIELDS = {"createdAt": "createdAt", "updatedAt": "updatedAt", "ticketNumber": "ticketNumber", "severity": "severityRank"}

TRACE_ID_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Canonical service resolve (Fix #246) ──────────────────────────────────────

async def library_service_ids() -> List[str]:
    """Semua serviceId di service library (untuk canonical resolve)."""
    try:
        from services.mongodb_client import get_db as _db

        db = _db()
        ids = [
            str(doc.get("serviceId", "")).strip()
            async for doc in db["service_library"].find({}, {"serviceId": 1})
        ]
        return [i for i in ids if i]
    except Exception as e:
        logger.warning(f"[TicketStore] library_service_ids gagal (non-fatal): {e}")
        return []


async def _record_service_alias(raw: str, canonical: str, workspace_id: Optional[str] = None) -> None:
    """Catat alias raw→kanonik dari LINK MANUAL user (belajar pola devops naming).
    Upsert + increment count — makin sering dipakai makin kuat sinyalnya.
    Exception-safe — belajar tidak boleh menggagalkan update tiket."""
    try:
        raw = (raw or "").strip()
        canonical = (canonical or "").strip()
        if not raw or not canonical or raw == canonical:
            return
        from services.mongodb_client import get_db as _db

        now = _now_iso()
        await _db()[SERVICE_ALIAS_COLLECTION].update_one(
            {"raw": raw},
            {
                "$set": {"canonical": canonical, "updated_at": now},
                "$inc": {"count": 1},
                "$setOnInsert": {"workspace_id": workspace_id or None, "created_at": now},
            },
            upsert=True,
        )
        logger.info(f"[TicketStore] service alias belajar: '{raw}' → '{canonical}'")
    except Exception as e:
        logger.warning(f"[TicketStore] record alias gagal (non-fatal): {e}")


async def resolve_service_alias(raw: str) -> Optional[str]:
    """Cari alias yang sudah dipelajari dari link manual user (raw → kanonik)."""
    try:
        if not raw:
            return None
        from services.mongodb_client import get_db as _db

        doc = await _db()[SERVICE_ALIAS_COLLECTION].find_one({"raw": raw.strip()})
        return (doc or {}).get("canonical")
    except Exception as e:
        logger.warning(f"[TicketStore] resolve alias gagal (non-fatal): {e}")
        return None


async def _canonical_service_ids(service_ids: List[str], *, record_aliases: bool = False) -> List[str]:
    """Canonicalize daftar service id terhadap service library.

    Urutan per nilai:
      1. alias yang sudah dipelajari (manual link sebelumnya)
      2. canonical_service (normalize + strip affix + substring) ke library
    Nilai tak dikenal dipertahankan (jangan patahkan link lama).
    record_aliases=True → raw yang berhasil di-kanonikalisasi dicatat sbg alias
    (dipakai saat LINK MANUAL — belajar dari keputusan user).
    """
    try:
        libs = await library_service_ids()
        if not libs:
            return [s.strip() for s in (service_ids or []) if s and s.strip()]
        from services.service_name_utils import canonical_service

        out: List[str] = []
        for s in service_ids or []:
            val = (s or "").strip()
            if not val:
                continue
            known = await resolve_service_alias(val)
            canon = known or canonical_service(val, libs)
            resolved = canon if canon and canon != val else val
            if resolved not in out:  # dedup (raw + kanonik bisa sama)
                out.append(resolved)
            if canon and canon != val and record_aliases:
                await _record_service_alias(val, canon)
        return out
    except Exception as e:
        logger.warning(f"[TicketStore] canonical service_ids gagal (non-fatal): {e}")
        return [s.strip() for s in (service_ids or []) if s and s.strip()]


async def _learn_alias_from_relink(ticket_id: str, new_service_ids: List[str]) -> None:
    """Gap 1 (Fix #246): belajar alias dari keputusan LINK MANUAL user.

    Saat user mengganti service tiket via PATCH (dialog ServicePicker), nilai LAMA
    yang TIDAK ada lagi di daftar baru bisa jadi nama devops raw (mis. "users-kuponku-apps")
    yang TIDAK ter-resolve heuristic canonical_service (token terbalik, dst). User
    menggantinya dgn pilihan eksplisit ("kuponku-users") = keputusan bahwa keduanya
    service sama → rekam raw_lama → kanonik_baru supaya auto-ticket alert serupa
    otomatis resolve ke depannya.

    Guard ketat (jangan salah belajar):
    - hanya nilai lama yang TIDAK dikenal library (raw asing) — user mengganti antar
      service library berbeda (kuponku-core-api → kuponku-users) = ganti pikiran,
      BUKAN alias.
    - hanya bila ada ≥1 nilai baru.
    Exception-safe — belajar tak boleh menggagalkan update.
    """
    try:
        if not new_service_ids:
            return
        old_doc = await get_ticket(ticket_id)
        if old_doc is None:
            return
        libs = set(await library_service_ids())
        old_vals = [s for s in (old_doc.get("serviceIds") or []) if s and s.strip()]
        old_name = (old_doc.get("serviceName") or "").strip()
        if old_name and old_name not in old_vals:
            old_vals.append(old_name)

        known_new = set(new_service_ids)
        for raw in old_vals:
            if raw in known_new:
                continue  # dipertahankan — bukan penggantian
            if raw in libs:
                continue  # service library valid diganti → bukan alias, ganti pikiran
            # raw asing diganti dgn nilai baru → user bilang "ini service sama"
            # Pilih nilai baru pertama (dialog multi-select; cukup 1 relasi)
            target = new_service_ids[0]
            await _record_service_alias(raw, target)
    except Exception as e:
        logger.warning(f"[TicketStore] learn alias dari relink gagal (non-fatal): {e}")


def valid_transition(current: str, target: str) -> bool:
    """Forward-only sepanjang chain: new → open → in_progress → needs_review → resolved → closed.
    Forward jump diizinkan (mis. new→resolved quick fix), KECUALI closed —
    hanya dari resolved. Mundur (resolved/closed→open) hanya via endpoint reopen."""
    if target == "closed":
        return current == "resolved"
    return (
        current in STATUS_CHAIN
        and target in STATUS_CHAIN
        and STATUS_CHAIN[target] > STATUS_CHAIN[current]
    )


def can_reopen(current: str) -> bool:
    return current in ("resolved", "closed")


# ── Serialisasi ───────────────────────────────────────────────────────────────

def public_ticket(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "ticketNumber": doc.get("ticketNumber", 0),
        "title": doc.get("title", ""),
        "description": doc.get("description", ""),
        "workspaceId": doc.get("workspaceId"),
        "projectId": doc.get("projectId"),
        "kind": doc.get("kind", "business_logic"),
        "severity": doc.get("severity", "low"),
        "traceId": doc.get("traceId"),
        "environment": doc.get("environment", "production"),
        "createdBy": doc.get("createdBy"),
        "createdByName": doc.get("createdByName", ""),
        "assignees": doc.get("assignees", []),
        "status": doc.get("status", "new"),
        "resolvedAt": doc.get("resolvedAt"),
        "resolvedBy": doc.get("resolvedBy"),
        "resolvedByName": doc.get("resolvedByName"),
        "tags": doc.get("tags", []),
        "progressLog": doc.get("progressLog", []),
        "source": doc.get("source", "manual"),
        "serviceName": doc.get("serviceName"),
        "serviceIds": doc.get("serviceIds") or [],
        "alertsCount": doc.get("alertsCount", 0),
        "lastAlertAt": doc.get("lastAlertAt"),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
    }


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def ensure_ticket_indexes() -> None:
    db = get_db()
    coll = db[TICKETS_COLLECTION]
    await coll.create_index([("projectId", 1), ("ticketNumber", 1)], unique=True)
    await coll.create_index([("projectId", 1), ("status", 1)])
    await coll.create_index([("projectId", 1), ("severity", 1)])
    await coll.create_index("assignees")
    # FE-4: fingerprint auto-ticket watchdog (sparse — hanya tiket watchdog yang punya).
    # Dedup window-based kini lewat contentFp (find_linkable_ticket_by_fingerprint);
    # index unique lama DILEPAS agar masalah sama bisa jadi tiket baru setelah window.
    try:
        await coll.drop_index("fingerprint_1")
    except Exception:
        pass  # index lama belum ada (DB baru)
    await coll.create_index("fingerprint", sparse=True)
    # dedup window: cari tiket aktif dengan konten alert sama dalam N jam terakhir
    await coll.create_index([("projectId", 1), ("contentFp", 1), ("status", 1)])
    # Fix #40: filter tiket per service (field serviceName terstruktur)
    await coll.create_index([("projectId", 1), ("serviceName", 1)])
    logger.info("Ticket indexes ensured")


async def find_ticket_by_fingerprint(fingerprint: str) -> Optional[Dict[str, Any]]:
    return await get_db()[TICKETS_COLLECTION].find_one({"fingerprint": fingerprint})


def _linkable_query(project_id: str, content_fp: str, window_hours: int) -> Dict[str, Any]:
    """Query tiket aktif dgn konten sama dalam window jam terakhir (dedup auto-ticket).

    resolved/closed TIDAK di-match → masalah yang balik setelah selesai = tiket baru."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(0, window_hours))
    ).isoformat()
    query: Dict[str, Any] = {
        "projectId": str(project_id),
        "contentFp": content_fp,
        "status": {"$in": list(OPEN_STATUSES)},
    }
    if window_hours > 0:
        query["createdAt"] = {"$gte": cutoff}
    return query


async def find_linkable_ticket_by_fingerprint(
    project_id: str, content_fp: str, window_hours: int
) -> Optional[Dict[str, Any]]:
    """Tiket watchdog AKTIF dengan konten alert sama dalam window jam terakhir.

    Dipakai auto_ticket untuk memutuskan: link alert ke tiket ini vs buat tiket baru.
    Bila ada beberapa tiket aktif konten sama (legacy duplikat), yang TERBARU dipilih."""
    return await get_db()[TICKETS_COLLECTION].find_one(
        _linkable_query(project_id, content_fp, window_hours),
        sort=[("createdAt", -1)],
    )


async def create_ticket(
    project: Dict[str, Any],
    user: Dict[str, Any],
    *,
    title: str,
    description: str,
    kind: str,
    severity: str,
    environment: str,
    trace_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    source: str = "manual",
    fingerprint: Optional[str] = None,
    content_fp: Optional[str] = None,
    initial_note: Optional[str] = None,
    service_name: Optional[str] = None,
    service_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if kind not in VALID_KINDS:
        raise ValueError("Kind harus business_logic atau infrastructure")
    if severity not in VALID_SEVERITIES:
        raise ValueError("Severity tidak valid")
    if environment not in VALID_ENVIRONMENTS:
        raise ValueError("Environment tidak valid")
    if trace_id and not TRACE_ID_RE.match(trace_id):
        raise ValueError("TraceId harus hex 16-64 karakter")

    db = get_db()
    project_oid = project["_id"]

    # Nomor tiket atomic — aman untuk request paralel
    updated = await db[PROJECTS_COLLECTION].find_one_and_update(
        {"_id": project_oid}, {"$inc": {"ticketCounter": 1}}, return_document=True
    )
    if updated is None:
        raise ValueError("Project tidak ditemukan")
    ticket_number = updated["ticketCounter"]

    now = _now_iso()
    doc = {
        "ticketNumber": ticket_number,
        "title": title.strip(),
        "description": description.strip(),
        "workspaceId": str(project["workspaceId"]),
        "projectId": str(project_oid),
        "kind": kind,
        "severity": severity,
        "severityRank": SEVERITY_ORDER[severity],
        "traceId": trace_id or None,
        "serviceName": (service_name or "").strip() or None,
        "serviceIds": service_ids or ([service_name.strip()] if service_name and service_name.strip() else []),
        "environment": environment,
        "createdBy": str(user["_id"]),
        "createdByName": user.get("name", ""),
        "assignees": [],
        "status": "new",
        "resolvedAt": None,
        "resolvedBy": None,
        "resolvedByName": None,
        "tags": [t.strip() for t in (tags or []) if t.strip()],
        "progressLog": (
            [{"id": uuid.uuid4().hex[:8], "note": initial_note, "by": str(user["_id"]),
              "byName": user.get("name", ""), "at": now}]
            if initial_note
            else []
        ),
        "source": source,
        "fingerprint": fingerprint,
        "contentFp": content_fp,
        "alertsCount": 0,
        "lastAlertAt": None,
        "createdAt": now,
        "updatedAt": now,
    }
    try:
        result = await db[TICKETS_COLLECTION].insert_one(doc)
    except DuplicateKeyError:
        # race nomor tiket / constraint lain (fingerprint sudah non-unique — window dedup)
        raise ValueError("Tiket duplikat (race)")
    doc["_id"] = result.inserted_id
    logger.info(f"Ticket #{ticket_number} created in project {project_oid} by {user.get('email') or user.get('name')}")
    emit(
        f"project:{project_oid}",
        {
            "type": "ticket:created",
            "payload": {
                "ticketId": str(doc["_id"]),
                "ticketNumber": ticket_number,
                "title": doc["title"],
                "severity": severity,
                "status": "new",
                "source": source,
            },
        },
    )
    return doc


async def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        return None
    return await get_db()[TICKETS_COLLECTION].find_one({"_id": oid})


def _emit_ticket_event(type_: str, doc: Dict[str, Any], **extra) -> None:
    """Publish event tiket ke channel project (FE-4 realtime)."""
    payload = {"ticketId": str(doc["_id"]), "ticketNumber": doc.get("ticketNumber", 0)}
    payload.update(extra)
    emit(f"project:{doc.get('projectId', '')}", {"type": type_, "payload": payload})


async def list_tickets(
    project_id: str,
    *,
    status: Optional[List[str]] = None,
    severity: Optional[List[str]] = None,
    environment: Optional[str] = None,
    assignee: Optional[str] = None,
    search: Optional[str] = None,
    service: Optional[str] = None,
    days: Optional[int] = None,
    page: int = 1,
    limit: int = 20,
    sort: str = "createdAt:desc",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from datetime import datetime, timedelta, timezone

    query: Dict[str, Any] = {"projectId": project_id}
    if status:
        query["status"] = {"$in": status}
    if severity:
        query["severity"] = {"$in": severity}
    if environment:
        query["environment"] = environment
    if assignee:
        query["assignees"] = assignee
    if days:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        query["createdAt"] = {"$gte": since}
    if service:
        svc = service.strip()
        # Filter: tiket yang serviceName SAMA ATAU serviceIds mengandung svc
        service_clause = {"$or": [{"serviceName": svc}, {"serviceIds": svc}]}
    else:
        service_clause = None

    if search:
        regex = {"$regex": re.escape(search.strip()), "$options": "i"}
        search_clause = {"$or": [{"title": regex}, {"description": regex}]}
    else:
        search_clause = None

    # Kombinasikan filter bila ada lebih dari satu
    if service_clause and search_clause:
        query["$and"] = [service_clause, search_clause]
    elif service_clause:
        query.update(service_clause)
    elif search_clause:
        query.update(search_clause)

    # Sort whitelist
    field_raw, _, dir_raw = sort.partition(":")
    sort_field = SORT_FIELDS.get(field_raw, "createdAt")
    sort_dir = -1 if dir_raw.strip().lower() == "desc" else 1

    limit = max(1, min(limit, 100))
    page = max(1, page)

    db = get_db()
    coll = db[TICKETS_COLLECTION]
    total = await coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort(sort_field, sort_dir)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    tickets = [doc async for doc in cursor]
    meta = {
        "page": page,
        "limit": limit,
        "total": total,
        "pages": (total + limit - 1) // limit if total > 0 else 0,
    }
    return tickets, meta


async def update_ticket(
    ticket_id: str,
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    severity: Optional[str] = None,
    tags: Optional[List[str]] = None,
    kind: Optional[str] = None,
    environment: Optional[str] = None,
    trace_id: Optional[str] = None,
    service_ids: Optional[List[str]] = None,
    actor: Optional[Dict[str, Any]] = None,
    via: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Edit field tiket. None = tidak diubah. trace_id="" berarti hapus.
    Perubahan severity tercatat di progressLog bila `actor` diberikan
    (siapa & kapan; via="agent" menandai eksekusi AI agent)."""
    set_doc: Dict[str, Any] = {"updatedAt": _now_iso()}
    if title is not None:
        set_doc["title"] = title.strip()
    if description is not None:
        set_doc["description"] = description.strip()
    if tags is not None:
        set_doc["tags"] = [t.strip() for t in tags if t.strip()]
    if kind is not None:
        if kind not in VALID_KINDS:
            raise ValueError("Kind tidak valid")
        set_doc["kind"] = kind
    if environment is not None:
        if environment not in VALID_ENVIRONMENTS:
            raise ValueError("Environment tidak valid")
        set_doc["environment"] = environment
    if severity is not None:
        if severity not in VALID_SEVERITIES:
            raise ValueError("Severity tidak valid")
        set_doc["severity"] = severity
        set_doc["severityRank"] = SEVERITY_ORDER[severity]
    if trace_id is not None:
        if trace_id and not TRACE_ID_RE.match(trace_id):
            raise ValueError("TraceId harus hex 16-64 karakter")
        set_doc["traceId"] = trace_id or None
    if service_ids is not None:
        # Fix #246: canonicalize nama service mentah → serviceId library kanonik.
        # User/devops bisa mengirim "lovvit-release-coupon-apps" (suffix K8s) padahal
        # library punya "lovvit-release-coupon" — simpan yang kanonik agar routing
        # chat tiket / incident_router / filter ?service= konsisten. Nilai yang TIDAK
        # bisa di-resolve tetap disimpan apa adanya (jangan patahkan link lama).
        # record_aliases=True: PATCH serviceIds = LINK MANUAL user → belajar alias
        # raw→kanonik utk auto-resolve ticket/alert serupa ke depan.
        canonical_new = await _canonical_service_ids(service_ids, record_aliases=True)
        # Fix #246 (Gap 1): bila nilai LAMA diganti manual oleh user (bukan agent)
        # → rekam alias lama→baru. Skenario: tiket bawa "users-kuponku-apps" (raw
        # tak dikenal library), user manual link ke "kuponku-users" di dialog →
        # keputusan eksplisit bahwa keduanya service sama; auto-ticket alert
        # "users-kuponku-apps" berikutnya akan resolve via alias.
        if actor is not None and via != "agent":
            await _learn_alias_from_relink(ticket_id, canonical_new)
        set_doc["serviceIds"] = canonical_new

    # Progress entry utk perubahan severity — butuh nilai lama dari dokumen saat ini
    severity_entry = None
    if severity is not None and actor is not None:
        current = await get_ticket(ticket_id)
        old_severity = (current or {}).get("severity")
        if current is not None and old_severity != severity:
            severity_entry = {
                "id": uuid.uuid4().hex[:8],
                "note": (
                    f"Severity changed: {old_severity} → {severity}"
                    + (" via Popov Agent" if via == "agent" else "")
                ),
                "by": str(actor["_id"]),
                "byName": actor.get("name", ""),
                "at": _now_iso(),
            }

    db = get_db()
    update_ops: Dict[str, Any] = {"$set": set_doc}
    if severity_entry is not None:
        update_ops["$push"] = {"progressLog": severity_entry}
    doc = await db[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ObjectId(ticket_id)}, update_ops, return_document=True
    )
    if doc is not None:
        _emit_ticket_event("ticket:updated", doc, status=doc.get("status", "open"))
    return doc


async def set_assignees(ticket_id: str, user_ids: List[str]) -> Optional[Dict[str, Any]]:
    """Set (replace) daftar assignee."""
    db = get_db()
    doc = await db[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ObjectId(ticket_id)},
        {"$set": {"assignees": user_ids, "updatedAt": _now_iso()}},
        return_document=True,
    )
    if doc is not None:
        _emit_ticket_event("ticket:assigned", doc, assignees=doc.get("assignees", []))
    return doc


async def remove_assignee(ticket_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    doc = await db[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ObjectId(ticket_id)},
        {"$pull": {"assignees": user_id}, "$set": {"updatedAt": _now_iso()}},
        return_document=True,
    )
    if doc is not None:
        _emit_ticket_event("ticket:assigned", doc, assignees=doc.get("assignees", []))
    return doc


async def link_episode_to_ticket(ticket_id: str, episode_id: str) -> bool:
    """Simpan episode_id ke ticket document. Idempotent — tidak overwrite jika sudah ada.
    Gap 2 Fase 3: internal linking, tanpa WebSocket broadcast (bukan user-facing change)."""
    try:
        db = get_db()
        result = await db[TICKETS_COLLECTION].update_one(
            {"_id": ObjectId(ticket_id), "episode_id": {"$exists": False}},
            {"$set": {"episode_id": episode_id, "updatedAt": _now_iso()}},
        )
        if result.modified_count:
            logger.info(f"[TicketStore] linked episode {episode_id} → ticket {ticket_id}")
        return result.modified_count > 0
    except Exception as e:
        logger.warning(f"[TicketStore] link_episode_to_ticket failed ticket={ticket_id}: {e}")
        return False


async def change_status(
    ticket: Dict[str, Any], target: str, user: Dict[str, Any],
    *, via: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Forward-only transition. Setiap perubahan status tercatat di progressLog
    (siapa & kapan) — termasuk auto-open new→open. via="agent" menandai aksi
    yang dieksekusi AI agent atas nama user. Return (doc, error)."""
    old = ticket.get("status", "open")
    if not valid_transition(old, target):
        return None, f"Transisi {old} → {target} tidak valid"
    now = _now_iso()
    set_doc: Dict[str, Any] = {"status": target, "updatedAt": now}
    if target == "resolved":
        set_doc["resolvedAt"] = now
        set_doc["resolvedBy"] = str(user["_id"])
        set_doc["resolvedByName"] = user.get("name", "")
    # Gap 5-Verify: schedule re-check saat masuk in_progress/needs_review (debounce —
    # hanya jika belum ada pending; tidak re-schedule jika masih menunggu verifikasi)
    if target in ("in_progress", "needs_review") and ticket.get("verification_status") != "pending":
        from config.settings import settings
        delay_min = getattr(settings, "verification_delay_minutes", 10)
        set_doc["verification_due_at"] = (
            datetime.now(timezone.utc) + timedelta(minutes=delay_min)
        ).isoformat()
        set_doc["verification_status"] = "pending"
        set_doc["verification_result"] = None
        set_doc["verification_note"] = None
    entry = {
        "id": uuid.uuid4().hex[:8],
        "note": (
            f"Status changed: {old} → {target}"
            + (" via Popov Agent" if via == "agent" else "")
        ),
        "by": str(user["_id"]),
        "byName": user.get("name", ""),
        "at": now,
    }
    db = get_db()
    doc = await db[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ticket["_id"]},
        {"$set": set_doc, "$push": {"progressLog": entry}},
        return_document=True,
    )
    if doc is not None:
        _emit_ticket_event("ticket:status_changed", doc, status=target)
        # Gap 2 Fase 5: enrich episode saat ticket resolved (fire-and-forget, tidak block flow)
        if target == "resolved":
            try:
                from services.episode_enrichment import enrich_episode_from_ticket_async
                asyncio.create_task(enrich_episode_from_ticket_async(str(doc["_id"])))
            except Exception as e:
                logger.warning(f"[TicketStore] schedule enrichment failed (non-fatal): {e}")
    return doc, None


async def reopen_ticket(
    ticket: Dict[str, Any], user: Dict[str, Any], *, via: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """resolved|closed → open + progress entry otomatis."""
    entry = {
        "id": uuid.uuid4().hex[:8],
        "note": "Ticket reopened" + (" via Popov Agent" if via == "agent" else ""),
        "by": str(user["_id"]),
        "byName": user.get("name", ""),
        "at": _now_iso(),
    }
    db = get_db()
    doc = await db[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ticket["_id"]},
        {
            "$set": {
                "status": "open",
                "resolvedAt": None,
                "resolvedBy": None,
                "resolvedByName": None,
                "updatedAt": _now_iso(),
            },
            "$push": {"progressLog": entry},
        },
        return_document=True,
    )
    if doc is not None:
        _emit_ticket_event("ticket:status_changed", doc, status="open")
    return doc


async def mark_opened(ticket: Dict[str, Any], user: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Idempotent: tiket berstatus 'new' → 'open' (tiket sudah dibuka user).
    Selain 'new' → no-op (kembalikan dokumen saat ini). Silent — tanpa progress entry."""
    if ticket.get("status") != "new":
        return await get_ticket(str(ticket["_id"])), None
    return await change_status(ticket, "open", user)


async def add_progress_note(ticket: Dict[str, Any], note: str, user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    entry = {
        "id": uuid.uuid4().hex[:8],
        "note": note.strip(),
        "by": str(user["_id"]),
        "byName": user.get("name", ""),
        "at": _now_iso(),
    }
    db = get_db()
    doc = await db[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ticket["_id"]},
        {"$push": {"progressLog": entry}, "$set": {"updatedAt": _now_iso()}},
        return_document=True,
    )
    if doc is not None:
        _emit_ticket_event("ticket:updated", doc, status=doc.get("status", "open"))
    return doc


async def attach_alert_to_ticket(ticket: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update counter alert tiket ($inc alertsCount + lastAlertAt) — dipanggil
    ticket_alert_store.record_ticket_alert tiap alert ter-link.
    Emit WS 'ticket:alert_added'. Return doc TERBARU (post-increment)."""
    now = _now_iso()
    doc = await get_db()[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ticket["_id"]},
        {
            "$inc": {"alertsCount": 1},
            "$set": {"lastAlertAt": now, "updatedAt": now},
        },
        return_document=True,
    )
    if doc is not None:
        _emit_ticket_event(
            "ticket:alert_added", doc, alertsCount=doc.get("alertsCount", 1)
        )
    return doc


async def add_progress_note_watchdog(ticket: Dict[str, Any], note: str) -> Optional[Dict[str, Any]]:
    """Entry ProgressLog dari aktor watchdog (dipakai ticket_alert_store utk
    mencatat alert ter-link dgn jumlah FINAL post-increment)."""
    now = _now_iso()
    doc = await get_db()[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ticket["_id"]},
        {
            "$push": {
                "progressLog": {
                    "id": uuid.uuid4().hex[:8],
                    "note": note,
                    "by": "watchdog",
                    "byName": "Popov Watchdog",
                    "at": now,
                }
            },
            "$set": {"updatedAt": now},
        },
        return_document=True,
    )
    if doc is not None:
        _emit_ticket_event("ticket:updated", doc, status=doc.get("status", "open"))
    return doc


# ── Agregasi Chat by Project (read-only) ──────────────────────────────────────

def _since_iso(hours: Optional[float]) -> Optional[str]:
    """createdAt tersimpan sebagai ISO-8601 UTC string (_now_iso) — perbandingan
    leksikografis valid utk rentang waktu (format sama panjang)."""
    if not hours or hours <= 0:
        return None
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


async def count_by_project(
    project_id: str,
    *,
    since_hours: Optional[float] = None,
    group_by: str = "status",
) -> Dict[str, Any]:
    """Agregasi tiket per project untuk chat project (Chat by Project fase 1).
    group_by: 'status' | 'kind' | 'severity'. Return {total, groups{key:count}}.
    since_hours kosong/<=0 = semua waktu."""
    field = {"status": "status", "kind": "kind", "severity": "severity"}.get(group_by, "status")
    query: Dict[str, Any] = {"projectId": project_id}
    since = _since_iso(since_hours)
    if since:
        query["createdAt"] = {"$gte": since}
    coll = get_db()[TICKETS_COLLECTION]
    total = await coll.count_documents(query)
    cursor = coll.aggregate(
        [{"$match": query}, {"$group": {"_id": f"${field}", "count": {"$sum": 1}}}]
    )
    groups = {doc["_id"] or "unknown": doc["count"] async for doc in cursor}
    return {"total": total, "groups": groups}


async def recent_tickets_by_project(
    project_id: str,
    *,
    since_hours: float = 24.0,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Tiket terbaru dalam window N jam (aktivitas project utk chat project)."""
    query: Dict[str, Any] = {"projectId": project_id}
    since = _since_iso(since_hours)
    if since:
        query["createdAt"] = {"$gte": since}
    cursor = (
        get_db()[TICKETS_COLLECTION]
        .find(query)
        .sort("createdAt", -1)
        .limit(max(1, min(limit, 50)))
    )
    return [doc async for doc in cursor]


async def get_ticket_by_number(
    ticket_number: int, *, workspace_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Cari tiket dari nomor (KEY-N) — untuk deteksi referensi tiket di chat project.
    ticketNumber unik PER PROJECT saja, jadi bila hasil >1 tanpa konteks workspace
    → None ambigu. Bila workspace_id diberikan, dibatasi ke workspace tsb."""
    coll = get_db()[TICKETS_COLLECTION]
    query: Dict[str, Any] = {"ticketNumber": int(ticket_number)}
    if workspace_id:
        query["workspaceId"] = str(workspace_id)
    docs = [doc async for doc in coll.find(query).limit(2)]
    if len(docs) == 1:
        return docs[0]
    return None
