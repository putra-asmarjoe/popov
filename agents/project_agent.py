"""
Project Agent — Chat by Project (fase 1, read-only).

Lane baru untuk sesi chat ber-konteks PROJECT (projectId tanpa ticketId):
- Pertanyaan level project: "berapa tiket hari ini", "apa yang terjadi 2 jam
  terakhir", "apakah ada error 3 jam terakhir", "knowledge apa saja di project ini".
- Referensi tiket eksplisit (`CORE-42`) → jawaban PENGARAH ke detail tiket
  (bukan analisis penuh — detail tetap di chat terikat tiket).

Disiplin desain (#1 Summary Pattern): gather data DETERMINISTIK tanpa LLM;
LLM hanya 1 call untuk sintesis jawaban natural. Suggestions (predictive
offers) dibangun deterministik dari whitelist — bukan hasil LLM.

Thinking mode TIDAK ditangani di sini: supervisor yang memutuskan routing
ke triage (pipeline insiden penuh) bila chat_depth="thinking".
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from state.schema import AgentState
from services.prompt_loader import render as render_prompt

logger = logging.getLogger(__name__)

try:
    from langchain_core.messages import SystemMessage, HumanMessage
    from services.llm_factory import get_chat_llm

    _has_llm = True
except Exception:
    _has_llm = False

# Referensi tiket eksplisit: KEY-N (key project 2–5 huruf + nomor).
# Fix G4 gap-scan: case-insensitive — user sering ketik "core-42" lowercase.
TICKET_REF_RE = re.compile(r"\b([A-Za-z]{2,5})-(\d{1,6})\b")

# Hint pengarah setelah jawaban status tiket (Fix #213/#214): bilingual, bukan hardcode ID
_TICKET_REF_HINT = {
    "en": "For full details and the ticket-specific conversation, open the ticket detail page.",
    "id": "Untuk detail lengkap dan percakapan khusus tiket ini, silakan buka halaman detailnya.",
}

# Keyword klasifikasi pertanyaan (murah, deterministik)
_TICKET_KW = ("tiket", "ticket", "total", "berapa", "jenis", "masuk")
_ACTIVITY_KW = (
    "terjadi", "jam terakhir", "aktivitas", "alert", "kejadian",
    "baru-baru", "recent", "hari ini", "tadi",
    "similar", "serupa", "incident", "insiden", "episode",
)
_ERROR_KW = ("error", "gagal", "masalah", "down", "5xx", "500", "bermasalah")
_KNOWLEDGE_KW = ("knowledge", "dokumen", "playbook", "grounding")

# SCOPE-FIX-1: batas tampilan daftar service di facts (inventory TETAP dihitung
# penuh; hanya presentasi yang di-cap, dan sisanya dinyatakan eksplisit).
_SERVICE_LIST_CAP = 30


def _detect_chat_locale(history: Optional[List[dict]], default: str = "en") -> str:
    """Alias DRY — implementasi di services/conversation.detect_chat_locale."""
    from services.conversation import detect_chat_locale as _impl

    return _impl(history, default)


def _hours_from_intent(intent_lower: str, default: float) -> float:
    """Ambil 'N jam' / 'N menit' / 'hari ini' dari intent; default bila tak disebut."""
    import re as _re

    m = _re.search(r"(\d+(?:[.,]\d+)?)\s*menit", intent_lower)
    if m:
        return max(0.1, float(m.group(1).replace(",", ".")) / 60.0)
    m = _re.search(r"(\d+(?:[.,]\d+)?)\s*jam", intent_lower)
    if m:
        return max(0.1, float(m.group(1).replace(",", ".")))
    if "hari ini" in intent_lower:
        # sejak tengah malam UTC lokal user tidak diketahui → 24 jam aman
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return max(0.5, (now - midnight).total_seconds() / 3600.0)
    return default


async def _gather_ticket_stats(project_id: str, hours_today: float) -> tuple[List[str], Dict[str, int], Dict[str, int]]:
    """Return (facts_blocks, today_status_groups, open_status_groups)."""
    """Return (facts_blocks, today_status_groups) — grup terpisah agar caller
    tidak parsing balik dari teks (Fix G5 gap-scan)."""
    from services.ticket_store import OPEN_STATUSES, count_by_project

    blocks: List[str] = []
    groups: Dict[str, int] = {}
    try:
        all_time = await count_by_project(project_id, group_by="status")
        today = await count_by_project(project_id, since_hours=hours_today, group_by="status")
        kinds = await count_by_project(project_id, since_hours=hours_today, group_by="kind")
        groups = {str(k): int(v) for k, v in (today.get("groups") or {}).items()}
        open_groups = {str(k): int(v) for k, v in (all_time.get("groups") or {}).items() if k in OPEN_STATUSES}
        blocks.append(
            "[TICKETS]\n"
            f"- Total tickets (all time): {all_time['total']}\n"
            f"- Open tickets (all time): {sum(open_groups.values())} — status: {open_groups}\n"
            f"- Tickets today (~{int(hours_today)}h): {today['total']}\n"
            f"- Status today: {groups}\n"
            f"- Kinds today: {kinds['groups'] or '{}'}"
        )
    except Exception as e:
        logger.warning(f"[project_agent] ticket stats gagal: {e}")
        blocks.append("[TICKETS] unavailable (database error)")
    return blocks, groups, open_groups


async def _gather_activity(
    project_id: Optional[str],
    ws_id: Optional[str],
    hours: float,
    allowlist: Optional[List[str]] = None,
) -> List[str]:
    """Fakta aktivitas project.

    SCOPE-FIX-1 (Opsi C): `allowlist` = service yang benar-benar milik project
    (services.service_store.project_service_allowlist). Bila tidak dikirim, ia
    DIRESOLVE DI SINI — supaya tidak ada caller yang bisa "lupa" men-scope.
    Semua sumber yang secara struktural hanya workspace-scoped DIINTERSEKSI dengan
    allowlist ini, dan fail-closed (kosong) bila allowlist tidak ada — bukan
    fallback global.
    """
    blocks: List[str] = []
    if allowlist is None:
        try:
            from services.service_store import project_service_allowlist

            allowlist = await project_service_allowlist(project_id or "")
        except Exception as e:
            logger.warning(f"[project_agent] allowlist gagal (fail closed): {e}")
            allowlist = []
    allowed = {str(s) for s in (allowlist or []) if s}
    try:
        from services.ticket_store import recent_tickets_by_project

        tickets = await recent_tickets_by_project(project_id, since_hours=hours, limit=8) if project_id else []
        lines = [
            f"- `{t.get('workspaceKey', '')}`#{t.get('ticketNumber')} {t.get('title', '')} "
            f"(status={t.get('status')}, sev={t.get('severity')}, source={t.get('source')})"
            for t in tickets
        ]
        blocks.append(
            f"[RECENT TICKETS last {int(hours)}h]\n" + ("\n".join(lines) if lines else "- none in window")
        )
    except Exception as e:
        logger.warning(f"[project_agent] recent tickets gagal: {e}")
        blocks.append(f"[RECENT TICKETS last {int(hours)}h] unavailable")

    # ── Alerts: dua tingkat, keduanya tidak boleh menyontol project lain ──────
    # 1) ticket_alerts membawa projectId eksplisit → scoping di level query.
    #    Preseden: services/ticket_alert_store.py::list_alerts_for_project +
    #    api/routes_project_overview.py::_query_alerts (§docstring: watchdog_alerts
    #    = broadcast log TANPA project_id → bocor lintas project).
    # 2) watchdog_alerts tidak punya project_id sama sekali (dikonfirmasi di DB),
    #    jadi TETAP dibaca workspace-scoped lalu DIINTERSEKSI dengan allowlist.
    #    Intersect ini wajib: block ini adalah satu-satunya jalur alert 'terbaru'
    #    (ticket_alerts ber-window hari, bukan jam) dan dulu inilah sumber kebocoran.
    #    Allowlist kosong = TIDAK ADA alert yang boleh ditampilkan (fail closed).
    try:
        from services.ticket_alert_store import list_alerts_for_project

        talerts = await list_alerts_for_project(project_id, limit=10) if project_id else []
        lines = [
            f"- [{a.get('occurredAt', '')}] {a.get('serviceName')}: "
            f"{a.get('name') or ''} (severity={a.get('severity')}, source={a.get('source')})"
            for a in talerts
            if str(a.get("serviceName") or "") in allowed
        ]
        blocks.append(
            f"[PROJECT ALERTS (ticketed) last {int(hours)}h]\n"
            + ("\n".join(lines) if lines else "- none in window")
        )
    except Exception as e:
        logger.warning(f"[project_agent] ticket alerts gagal: {e}")
        blocks.append(f"[PROJECT ALERTS (ticketed) last {int(hours)}h] unavailable")

    try:
        from services.request_log import list_recent_watchdog_alerts

        raw = await list_recent_watchdog_alerts(ws_id, since_hours=hours, limit=10) if allowed else []
        alerts = [a for a in raw if str(a.get("service_name") or "") in allowed]
        lines = [
            f"- [{a.get('sent_at', '')}] {a.get('service_name')}: {(a.get('message') or '')[:120]}"
            for a in alerts
        ]
        blocks.append(
            f"[PROJECT ALERTS last {int(hours)}h]\n"
            + ("\n".join(lines) if lines else "- none for this project's services")
        )
    except Exception as e:
        logger.warning(f"[project_agent] watchdog alerts gagal: {e}")
        blocks.append(f"[PROJECT ALERTS last {int(hours)}h] unavailable")

    # ── Episodes: `incident_episodes` TIDAK punya project_id (dikonfirmasi di DB).
    # Scope via ticket_id ∈ tiket project ATAU observ_id ∈ stack project —
    # disalini dari preseden api/routes_project_overview.py::_query_episodes.
    # FAIL CLOSED: tanpa discriminator project → [] (TANPA `else {}` global).
    try:
        from services.mongodb_client import get_db as _gdb
        from services.observability_store import observ_ids_for_project
        from services.ticket_store import ticket_ids_for_project

        if not (project_id and ws_id):
            docs: List[Dict[str, Any]] = []
        else:
            conds: List[Dict[str, Any]] = []
            tids = await ticket_ids_for_project(project_id)
            if tids:
                conds.append({"ticket_id": {"$in": tids}})
            observ_ids = await observ_ids_for_project(project_id, ws_id)
            if observ_ids:
                conds.append({"observ_id": {"$in": observ_ids}})
            if not conds:
                docs = []   # fail closed — project tanpa tiket & tanpa stack
            else:
                q = {"workspace_id": str(ws_id), "$or": conds}
                docs = await _gdb()["incident_episodes"].find(q).sort("timestamp", -1).limit(5).to_list(5)
        lines = [
            f"- {d.get('episode_id')}: svc={d.get('service_name')} root={d.get('root_cause')} "
            f"conf={d.get('confidence')} at={d.get('timestamp', '')}"
            for d in docs
        ]
        blocks.append("[RECENT ANALYSES (Second Brain)]\n" + ("\n".join(lines) if lines else "- none"))
    except Exception as e:
        logger.warning(f"[project_agent] episodes gagal: {e}")
        blocks.append("[RECENT ANALYSES (Second Brain)] unavailable")
    return blocks


async def _gather_project_identity(project_id: Optional[str]) -> List[str]:
    """SCOPE-FIX-1 (H4): identitas project HARUS masuk facts secara deterministik.
    Dulu `find_project_by_id` hanya dibaca untuk `key` (bekas cabang want_tickets),
    jadi 'apa nama project ini?' dijawab 'not available in the provided facts'."""
    if not project_id:
        return ["[PROJECT] no project context"]
    try:
        from services.workspace_store import find_project_by_id

        doc = await find_project_by_id(project_id) or {}
        name = str(doc.get("name") or "").strip()
        key = str(doc.get("key") or "").strip()
        if not doc:
            return [f"[PROJECT] id={project_id} name=UNAVAILABLE key=UNAVAILABLE"]
        return [
            "[PROJECT] (AUTHORITATIVE identity — use this to answer what the "
            "project is called)\n"
            f"- name: {name or 'UNAVAILABLE'}\n"
            f"- key: {key or 'UNAVAILABLE'}\n"
            f"- id: {project_id}"
        ]
    except Exception as e:
        logger.warning(f"[project_agent] project identity gagal: {e}")
        return ["[PROJECT] unavailable (database error)"]


async def _gather_services(project_id: Optional[str], allowlist: List[str]) -> List[str]:
    """SCOPE-FIX-1 (H3): daftar service project = inventory deterministik dari
    allowlist — TANPA window waktu, TANPA slice limit. Ini yang membuat jawaban
    'service apa saja yang ada di project ini' stabil antar turn (bug 16 vs 11)."""
    if not project_id:
        return ["[PROJECT SERVICES] no project context"]
    if not allowlist:
        return [
            "[PROJECT SERVICES]\n- none registered for this project "
            "(no service refs and no ticket service names)"
        ]
    listed = allowlist[:_SERVICE_LIST_CAP]
    more = len(allowlist) - len(listed)
    lines = [f"- {s}" for s in listed]
    if more > 0:
        lines.append(f"- (+{more} more — ask to list all)")
    return [
        "[PROJECT SERVICES] (AUTHORITATIVE inventory — services belonging to THIS "
        f"project; {len(allowlist)} total)\n" + "\n".join(lines)
    ]



def _harvest_alert_services(activity_blocks: List[str], allowed: set) -> List[str]:
    """Service name dari baris alert sebagai bahan chip — HANYA yang ada di allowlist.

    SCOPE-FIX-1: dulu inline di project_agent() dan mengambil nama dari baris alert
    workspace-wide, sehingga chip "investigate <service>" menawarkan service milik
    project lain. Dijadikan fungsi murni agar guard-nya bisa dites langsung; ia
    bertahan sebagai defense-in-depth walau facts upstream sudah discoped.
    """
    out: List[str] = []
    for line in "\n".join(activity_blocks[:3]).splitlines():
        low = line.lower()
        if not low.startswith("- ") or "] " not in line or "alert" not in low:
            continue
        # JANGAN split(":")[0] — colon ada di dalam ISO timestamp.
        svc = line.split("] ", 1)[-1].split(":", 1)[0].strip().strip("`").strip()
        if not svc or any(ch in svc for ch in "[],"):
            continue
        if allowed and svc not in allowed:      # <- guard chip
            continue
        if svc not in out:
            out.append(svc)
    return out


async def _gather_errors(ws_id: Optional[str], project_id: Optional[str], hours: float) -> List[str]:
    """Hitung error ringan per service ter-link project (max 3 service ber-dbConfig).
    Tanpa dbConfig → catat degraded jujur (bukan klaim 0 error)."""
    blocks: List[str] = []
    try:
        from services.db_loader import resolve_db_config
        from services.log_query import resolve_error_query, apply_time_window_to_query, detect_schema
        from services.service_store import service_ids_for_project
        from services.mongodb_client import get_db, DBConnectionError

        linked = sorted(set(await service_ids_for_project(project_id)))[:3] if project_id else []
        if not linked:
            return ["[ERROR LOGS] no services linked to this project"]
        lines: List[str] = []
        for sid in linked:
            cfg, _src = await resolve_db_config(sid, ws_id)
            if not (cfg and cfg.get("uri") and cfg.get("db")):
                lines.append(f"- {sid}: no log DB config (skip — bukan berarti bebas error)")
                continue
            collection = cfg.get("collection") or f"logs_{sid}"
            try:
                base_q = await resolve_error_query(sid, cfg, collection)
                sort_field = "timestamp"
                ts_type = "unknown"
                try:
                    schema = await detect_schema(cfg["uri"], cfg["db"], collection)
                    ts_type = schema.get("ts_value_type", "unknown")
                    sort_field = schema.get("sort_field") or sort_field
                except Exception:
                    pass
                q = apply_time_window_to_query(base_q, sort_field, int(max(1, round(hours))), ts_type)
                count = await get_db(db_name=cfg["db"], uri=cfg["uri"])[collection].count_documents(q)
                lines.append(f"- {sid}: {count} error documents dalam {int(hours)} jam terakhir")
            except DBConnectionError as e:
                lines.append(f"- {sid}: log DB unreachable ({str(e)[:80]})")
            except Exception as e:
                lines.append(f"- {sid}: query failed ({str(e)[:80]})")
        blocks.append(f"[ERROR LOG COUNTS window {int(hours)}h]\n" + "\n".join(lines))
    except Exception as e:
        logger.warning(f"[project_agent] error counts gagal: {e}")
        blocks.append("[ERROR LOG COUNTS] unavailable")
    return blocks


async def _gather_knowledge(
    project_id: Optional[str], ws_id: Optional[str], locale: str = "en"
) -> str:
    from services.knowledge_listing import build_project_knowledge_inventory

    if not project_id:
        return "[KNOWLEDGE] no project context"
    return await build_project_knowledge_inventory(project_id, ws_id, locale=locale)


def _build_suggestions(
    *, want_tickets: bool, want_errors: bool, want_knowledge: bool,
    open_count: int, alert_services: List[str], error_services: List[str],
    locale: str = "en", intent: str = "",
) -> List[str]:
    """Predictive offers deterministik dari whitelist (bukan LLM) — bahasa ikut locale chat.
    DRY: delegasi ke services.offer_planner.build_chat_suggestions (satu sumber teks).
    intent (Fix #215): skip chip yang topiknya sudah ditanyakan user."""
    from services.offer_planner import build_chat_suggestions

    return build_chat_suggestions(
        service_name=(error_services[0] if want_errors and error_services else
                      (alert_services[0] if alert_services else "")),
        root_cause=("service-fault" if want_errors and error_services else
                    ("downstream" if alert_services else "unknown")),
        has_open_tickets=bool(want_tickets and open_count > 0),
        want_knowledge=True,  # perilaku lama: chips knowledge hampir selalu default
        locale=locale,
        intent=intent,
        max_items=3,
    )


async def _fallback_answer(question: str, facts_blocks: List[str], locale: str = "id") -> str:
    """Fallback deterministik bila LLM down — facts mentah tetap tersampaikan (Fix #113 bilingual)."""
    heads = {
        "id": "⚠️ *LLM tidak tersedia saat ini* — berikut fakta mentah dari database project:\n\n",
        "en": "⚠️ *LLM is currently unavailable* — here are the raw facts from the project database:\n\n",
    }
    body = "\n\n".join(facts_blocks)
    return heads.get(locale, heads["id"]) + body


async def project_agent(state: AgentState) -> dict:
    intent_raw = (state.get("intent") or "").strip()
    intent_lower = intent_raw.lower()
    project_id = state.get("project_id")
    ws_id = state.get("workspace_id")
    depth = (state.get("chat_depth") or "low").lower()
    agents_visited = state.get("agents_visited", []) + ["project_agent"]

    if not project_id:
        try:
            from services.conversation import detect_chat_locale
            from services.user_store import get_user_locale
            _ploc = detect_chat_locale(
                state.get("conversation_history") or [],
                default=await get_user_locale((state.get("sender") or {}).get("user_id")),
            )
        except Exception:
            _ploc = "id"
        if _ploc == "en":
            msg = (
                "⚠️ This session has no project context. "
                "Open a chat from a project page to ask project-level questions."
            )
        else:
            msg = (
                "⚠️ Sesi ini tidak punya konteks project. "
                "Buka chat dari halaman project untuk pertanyaan level project."
            )
        return {
            "formatted_message": msg,
            "next_agent": "response_agent",
            "agents_visited": agents_visited,
            "error": None,
        }

    # ── 1. Referensi tiket eksplisit (`KEY-N`) → jawaban PENGARAH ────────────
    ref = TICKET_REF_RE.search(intent_raw)
    if ref:
        key, num = ref.group(1).upper(), int(ref.group(2))
        try:
            from services.ticket_store import get_ticket_by_number

            ticket = await get_ticket_by_number(num, workspace_id=ws_id)
        except Exception as e:
            logger.warning(f"[project_agent] lookup KEY-N gagal: {e}")
            ticket = None
        if ticket:
            # Fix #214: locale ikut bahasa chat (detect → preferensi user), hint bilingual
            from services.user_store import get_user_locale

            _hist = state.get("conversation_history") or []
            _ulocale = await get_user_locale((state.get("sender") or {}).get("user_id"))
            _locale = _detect_chat_locale(_hist, default=_ulocale)
            _hint = _TICKET_REF_HINT.get(_locale, _TICKET_REF_HINT["en"])
            msg = (
                f"🎟️ *Tiket `{key}-{num}`* — \"{ticket.get('title', '')}\"\n"
                f"*Status:* {ticket.get('status')} · *Severity:* {ticket.get('severity')} · "
                f"*Service:* `{ticket.get('serviceName') or '-'}`\n\n"
                f"{_hint}"
            )
            # Fix #214: chips relevan utk tiket (bilingual, jalur generic build_chat_suggestions)
            from services.offer_planner import build_chat_suggestions

            _sug = build_chat_suggestions(
                ticket={"status": ticket.get("status")},
                project={"key": key},
                service_name=ticket.get("serviceName") or "",
                root_cause="unknown",
                has_open_tickets=False,
                want_knowledge=False,
                locale=_locale,
                max_items=3,
                intent=state.get("intent") or "",  # Fix #215: skip chip topik yang sudah ditanya
            )
            return {
                "formatted_message": msg,
                "project_result": {
                    "type": "ticket_ref",
                    "ticket_refs": [{
                        "ticketNumber": num,
                        "ticketId": str(ticket["_id"]),
                        "projectKey": key,
                        "title": ticket.get("title"),
                        "status": ticket.get("status"),
                    }],
                    "suggestions": _sug,
                },
                "next_agent": "response_agent",
                "agents_visited": agents_visited,
                "routing_strategy": "project_query",
                "error": None,
            }
        # nomor tak ditemukan di workspace ini → lanjut sebagai pertanyaan umum

    # ── 2. Klasifikasi pertanyaan (murah, keyword) ────────────────────────────
    want_tickets = any(k in intent_lower for k in _TICKET_KW)
    want_activity = any(k in intent_lower for k in _ACTIVITY_KW)
    want_errors = any(k in intent_lower for k in _ERROR_KW)
    want_knowledge = any(k in intent_lower for k in _KNOWLEDGE_KW)
    if not (want_tickets or want_activity or want_errors or want_knowledge):
        # default ramah: ringkasan tiket + aktivitas singkat
        want_tickets = want_activity = True

    hours = _hours_from_intent(intent_lower, default=(24.0 if want_tickets else 3.0))

    # ── 3. Gather deterministik ───────────────────────────────────────────────
    facts_blocks: List[str] = []
    open_count = 0
    alert_services: List[str] = []
    error_services: List[str] = []

    # SCOPE-FIX-1 (Opsi C): allowlist "service milik project ini" = project refs ∪
    # distinct serviceName tiket milik project. Dibaca SEKALI, dipakai untuk:
    # intersect alert, validasi chip, dan blok [PROJECT SERVICES].
    # Kegagalan baca => allowlist kosong => facts FAIL CLOSED (bukan global).
    allowlist: List[str] = []
    allowlist_ok = True
    try:
        from services.service_store import project_service_allowlist

        allowlist = await project_service_allowlist(project_id)
    except Exception as e:
        allowlist_ok = False
        logger.warning(f"[project_agent] project allowlist gagal: {e}")

    # Identitas project SELALU di facts (H4) — dulu `name` dibuang sehingga
    # 'apa nama project ini?' dijawab 'not available in the provided facts'.
    facts_blocks.extend(await _gather_project_identity(project_id))

    # Inventaris service SELALU di facts dan TIDAK bergantung window (H3: 16 vs 11).
    facts_blocks.extend(await _gather_services(project_id, allowlist))
    if not allowlist_ok:
        facts_blocks.append(
            "[PROJECT SERVICES] unavailable (database error) — do NOT substitute "
            "services from another project or from the workspace library"
        )

    # ── 4. Deteksi bahasa chat: isi percakapan dulu, preferensi user fallback ──
    from services.user_store import get_user_locale

    history = state.get("conversation_history") or []
    user_locale = await get_user_locale((state.get("sender") or {}).get("user_id"))
    locale = _detect_chat_locale(history, default=user_locale)

    if want_tickets:
        stats, today_groups, open_groups = await _gather_ticket_stats(project_id, hours)
        facts_blocks.extend(stats)
        open_count = sum(v for v in open_groups.values())
        # Grounding detail tiket: daftar tiket TERBUKA nyata (nomor asli `KEY-N`,
        # judul, status, severity, service) — mencegah LLM mengarang "TICKET-N" saat
        # user minta detail ("send me detail ticket", "tiket apa saja yang terbuka").
        try:
            from services.ticket_store import OPEN_STATUSES, recent_tickets_by_project
            from services.workspace_store import find_project_by_id

            proj_doc = await find_project_by_id(project_id)
            proj_key = (proj_doc or {}).get("key") or ""
            open_tickets = await recent_tickets_by_project(project_id, since_hours=None, limit=20)
            open_tickets = [t for t in open_tickets if (t.get("status") or "") in OPEN_STATUSES]
            if open_tickets:
                lines = []
                for t in open_tickets:
                    key = t.get("projectKey") or proj_key or "?"
                    title = (t.get("title") or "")[:80]
                    lines.append(
                        f"- `{key}-{t.get('ticketNumber')}` {title} "
                        f"(status={t.get('status')}, sev={t.get('severity')}, "
                        f"service={t.get('serviceName') or '-'}, source={t.get('source')})"
                    )
                shown = len(lines)
                if open_count and open_count > shown:
                    lines.append(
                        f"- (list truncated: {shown} of {open_count} open tickets shown — this is "
                        "the TICKET list only; the SERVICE inventory is complete in [PROJECT SERVICES])"
                    )
                facts_blocks.append("[OPEN TICKETS (detail)]\n" + "\n".join(lines))
        except Exception as e:
            logger.warning(f"[project_agent] open ticket detail gagal: {e}")
            facts_blocks.append("[OPEN TICKETS (detail)] unavailable")

    if want_activity or want_errors:
        activity = await _gather_activity(project_id, ws_id, hours, allowlist)
        # SCOPE-FIX-1: ketiga blok (tiket + alert ter-tiket + alert project) masuk
        # facts; episode tetap dihitung tapi hanya bila ada diskriminator project.
        facts_blocks.extend(activity[:3])
        # Chip HANYA boleh menawarkan service milik project ini (allowlist).
        alert_services = _harvest_alert_services(activity, set(allowlist))

    if want_errors:
        facts_blocks.extend(await _gather_errors(ws_id, project_id, hours))
        for line in "\n".join(facts_blocks[-1:]).splitlines():
            if ": " in line and "error documents" in line:
                try:
                    cnt = int(line.split(": ")[1].split(" ")[0])
                    if cnt > 0:
                        svc = line.split("- ")[1].split(":")[0]
                        if svc not in error_services:
                            error_services.append(svc)
                except Exception:
                    continue

    if want_knowledge:
        facts_blocks.append(await _gather_knowledge(project_id, ws_id, locale=locale))

    # ── Fix (hallucination guard): pertanyaan infrastruktur yang bocor ke lane
    # project (mis. routing race) TIDAK boleh dijawab dari hitungan tiket —
    # dulu LLM konflasi "4 tiket kuponku-core-api" jadi "4 replicas". Pre-check
    # deterministik SEBELUM LLM synthesis: intent menyinggung dimensi infra +
    # facts tidak punya blok K8s → append blok eksplisit agar LLM bilang jujur
    # data tidak tersedia (bukan mengarang angka dari tiket).
    _INFRA_DIMENSION_KW = ("replica", "pod", "deployment", "cluster", "namespace")
    _facts_text = "\n".join(facts_blocks).lower()
    if any(kw in intent_lower for kw in _INFRA_DIMENSION_KW) and "[k8s data]" not in _facts_text:
        facts_blocks.append(
            "[K8S DATA] unavailable — data replica/pod/deployment tidak dikumpulkan "
            "di lane project (pertanyaan infrastruktur akan diroute ke lane k8s). "
            "Ticket counts are NOT infrastructure metrics."
        )

    # ── CHAT3 P2.1: conversation_state continuity — web-only ────────────────
    # Read topic_context + investigation_context dari turn sebelumnya, inject
    # ke facts agar LLM punya konteks topik lanjutan.
    _conv_topic = {}  # type: Dict[str, Any]
    _conv_inv = {}  # type: Dict[str, Any]
    _chat_session = (state.get("sender") or {}).get("session_id")
    if _chat_session:
        try:
            from services.chat_store import get_conversation_state
            _conv_raw = await get_conversation_state(str(_chat_session))
            _conv_topic = (_conv_raw.get("topic_context") or {})
            _conv_inv = (_conv_raw.get("investigation_context") or {})
        except Exception:
            pass  # non-fatal

    if _conv_topic or _conv_inv:
        _ctx_lines = []
        if _conv_topic.get("active_service"):
            _ctx_lines.append(f"- active_service: {_conv_topic['active_service']}")
        if _conv_topic.get("current_topic"):
            _ctx_lines.append(f"- previous_topic: {_conv_topic['current_topic']}")
        if _conv_topic.get("ticket_id"):
            _ctx_lines.append(f"- ticket_id: {_conv_topic['ticket_id']}")
        if _conv_inv.get("last_findings"):
            _findings = _conv_inv['last_findings']
            if len(_findings) > 400:
                _findings = _findings[:400] + " ...[truncated]"
            _ctx_lines.append(f"- last_findings: {_findings}")
        if _conv_inv.get("last_root_cause"):
            _ctx_lines.append(f"- last_root_cause: {_conv_inv['last_root_cause']}")
        if _ctx_lines:
            facts_blocks.append(
                "[CONVERSATION CONTEXT]\n"
                "(from previous turn — use to maintain topic continuity and anaphora)\n"
                + "\n".join(_ctx_lines)
            )

    suggestions = _build_suggestions(
        want_tickets=want_tickets, want_errors=want_errors, want_knowledge=want_knowledge,
        open_count=open_count, alert_services=alert_services, error_services=error_services,
        locale=locale, intent=state.get("intent") or "",
    )

    # ── 5. Satu LLM call sintesis (fallback deterministik) ────────────────────
    history_block = ""
    if history:
        hist_lines = "\n".join(f"[{h.get('role')}] {h.get('content', '')}" for h in history[-6:])
        history_block = (
            "\nPREVIOUS CONVERSATION (session context — secondary):\n" + hist_lines
        )

    formatted = ""
    if _has_llm:
        try:
            # USER_PROFILE_PLAN Phase 3: blok User Context (web user + workspace ini)
            user_context = ""
            try:
                from services.user_profile import render_user_context_block

                _uid = (state.get("sender") or {}).get("user_id")
                if _uid and ws_id:
                    user_context = await render_user_context_block(str(_uid), str(ws_id))
            except Exception:
                user_context = ""
            llm = get_chat_llm(temperature=0.2)
            messages = [
                SystemMessage(content=render_prompt("project_system")),
                HumanMessage(content=render_prompt(
                    "project_user",
                    question=intent_raw,
                    facts_block="\n\n".join(facts_blocks),
                    history_block=history_block,
                    reply_language=("English" if locale == "en" else "Bahasa Indonesia"),
                    user_context=user_context,
                )),
            ]
            resp = await llm.ainvoke(messages)
            formatted = (resp.content or "").strip()
        except Exception as e:
            logger.warning(f"[project_agent] LLM sintesis gagal: {e}")
            formatted = ""

    if not formatted:
        from agents.correlation_agent import llm_unavailable_note

        formatted = (
            await _fallback_answer(intent_raw, facts_blocks, locale)
            + llm_unavailable_note(locale)
        )

    medium_note = ""
    if depth == "medium" and error_services:
        medium_note = (
            f"\n\n💡 {('Investigate deeper the error on' if locale == 'en' else 'Mau saya investigasi lebih dalam error pada')} "
            f"`{error_services[0]}`?"
        )

    # CHAT3 P2.1: conversation_state write-back — web-only
    # Tulis topic_context agar turn berikutnya punya konteks topik.
    # project_agent tidak menghasilkan correlation/triage → tidak tulis investigation_context.
    if state.get("suppress_telegram") and _chat_session:
        try:
            from services.chat_store import update_conversation_state
            _write_svc = state.get("service_name") or state.get("resolved_service_name") or ""
            if not _write_svc and alert_services:
                _write_svc = alert_services[0]
            # Validate against allowlist (P2.1 review Minor-4)
            if _write_svc and allowlist and _write_svc not in allowlist:
                _write_svc = ""
            _topic_ctx = {
                "active_service": _write_svc,
                "current_topic": (intent_raw or "")[:200],
                "ticket_id": (state.get("ticket_context") or {}).get("ticketNumber") or "",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await update_conversation_state(
                str(_chat_session),
                topic_context=_topic_ctx,
                current_intent=(intent_raw or "")[:200],
            )
            logger.info(
                f"[project_agent] conversation_state written session={_chat_session} "
                f"active_svc={_write_svc!r}"
            )
        except Exception as e:
            logger.warning(f"[project_agent] conversation_state write failed (non-fatal): {e}")

    return {
        "formatted_message": (formatted + medium_note).strip(),
        "project_result": {
            "type": "project_qa",
            "ticket_refs": [],
            "suggestions": suggestions,
        },
        "routing_strategy": "project_query",
        "next_agent": "response_agent",
        "agents_visited": agents_visited,
        "error": None,
    }
