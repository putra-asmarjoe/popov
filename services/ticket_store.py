"""
Ticket store — FE-3 Ticketing Core.
Collection: tickets (db popovagent_db).

Model 100% dari popov-frontend-plan.md + field tambahan:
- source: "manual" | "watchdog" (badge 🤖 Auto, FE-4)
- severityRank: int denormalisasi (0=critical..3=low) untuk sort severity
- *Name (createdByName, resolvedByName, progress.byName): snapshot nama saat event

Nomor tiket atomic: projects.ticketCounter di-$inc (anti-race, tanpa collection counter).
"""
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
        "workspaceId": str(doc.get("workspaceId", "")),
        "projectId": str(doc.get("projectId", "")),
        "kind": doc.get("kind", "business_logic"),
        "severity": doc.get("severity", "medium"),
        "traceId": doc.get("traceId"),
        "serviceName": doc.get("serviceName"),
        "environment": doc.get("environment", "production"),
        "createdBy": str(doc.get("createdBy", "")),
        "createdByName": doc.get("createdByName", ""),
        "assignees": doc.get("assignees", []),
        "status": doc.get("status", "new"),
        "resolvedAt": doc.get("resolvedAt"),
        "resolvedBy": doc.get("resolvedBy"),
        "resolvedByName": doc.get("resolvedByName"),
        "tags": doc.get("tags", []),
        "progressLog": doc.get("progressLog", []),
        "source": doc.get("source", "manual"),
        "alertsCount": int(doc.get("alertsCount") or 0),
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
    page: int = 1,
    limit: int = 20,
    sort: str = "createdAt:desc",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    query: Dict[str, Any] = {"projectId": project_id}
    if status:
        query["status"] = {"$in": status}
    if severity:
        query["severity"] = {"$in": severity}
    if environment:
        query["environment"] = environment
    if assignee:
        query["assignees"] = assignee
    if service:
        query["serviceName"] = service.strip()
    if search:
        regex = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"title": regex}, {"description": regex}]

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
) -> Optional[Dict[str, Any]]:
    """Edit field tiket. None = tidak diubah. trace_id="" berarti hapus."""
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

    db = get_db()
    doc = await db[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ObjectId(ticket_id)}, {"$set": set_doc}, return_document=True
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


async def change_status(
    ticket: Dict[str, Any], target: str, user: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Forward-only transition. Return (doc, error)."""
    if not valid_transition(ticket.get("status", "open"), target):
        return None, f"Transisi {ticket.get('status')} → {target} tidak valid"
    set_doc: Dict[str, Any] = {"status": target, "updatedAt": _now_iso()}
    if target == "resolved":
        set_doc["resolvedAt"] = _now_iso()
        set_doc["resolvedBy"] = str(user["_id"])
        set_doc["resolvedByName"] = user.get("name", "")
    db = get_db()
    doc = await db[TICKETS_COLLECTION].find_one_and_update(
        {"_id": ticket["_id"]}, {"$set": set_doc}, return_document=True
    )
    if doc is not None:
        _emit_ticket_event("ticket:status_changed", doc, status=target)
    return doc, None


async def reopen_ticket(ticket: Dict[str, Any], user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """resolved|closed → open + progress entry otomatis."""
    entry = {
        "id": uuid.uuid4().hex[:8],
        "note": "Tiket dibuka kembali",
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
