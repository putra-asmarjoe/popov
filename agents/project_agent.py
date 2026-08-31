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

# Keyword klasifikasi pertanyaan (murah, deterministik)
_TICKET_KW = ("tiket", "ticket", "total", "berapa", "jenis", "masuk")
_ACTIVITY_KW = (
    "terjadi", "jam terakhir", "aktivitas", "alert", "kejadian",
    "baru-baru", "recent", "hari ini", "tadi",
)
_ERROR_KW = ("error", "gagal", "masalah", "down", "5xx", "500", "bermasalah")
_KNOWLEDGE_KW = ("knowledge", "dokumen", "playbook", "grounding")


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


async def _gather_ticket_stats(project_id: str, hours_today: float) -> tuple[List[str], Dict[str, int]]:
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
            f"- Total tiket (semua waktu): {all_time['total']}\n"
            f"- Tiket terbuka (semua waktu): {sum(open_groups.values())} — status: {open_groups}\n"
            f"- Tiket masuk hari ini (~{int(hours_today)} jam): {today['total']}\n"
            f"- Status hari ini: {groups}\n"
            f"- Jenis hari ini: {kinds['groups'] or '{}'}"
        )
    except Exception as e:
        logger.warning(f"[project_agent] ticket stats gagal: {e}")
        blocks.append("[TICKETS] unavailable (database error)")
    return blocks, groups, open_groups


async def _gather_activity(project_id: Optional[str], ws_id: Optional[str], hours: float) -> List[str]:
    blocks: List[str] = []
    try:
        from services.ticket_store import recent_tickets_by_project

        tickets = await recent_tickets_by_project(project_id, since_hours=hours, limit=8) if project_id else []
        lines = [
            f"- `{t.get('workspaceKey', '')}{''}`#{t.get('ticketNumber')} {t.get('title', '')} "
            f"(status={t.get('status')}, sev={t.get('severity')}, source={t.get('source')})"
            for t in tickets
        ]
        blocks.append(
            f"[RECENT TICKETS last {int(hours)}h]\n" + ("\n".join(lines) if lines else "- none in window")
        )
    except Exception as e:
        logger.warning(f"[project_agent] recent tickets gagal: {e}")
        blocks.append(f"[RECENT TICKETS last {int(hours)}h] unavailable")

    try:
        from services.request_log import list_recent_watchdog_alerts

        alerts = await list_recent_watchdog_alerts(ws_id, since_hours=hours, limit=10)
        lines = [
            f"- [{a.get('sent_at', '')}] {a.get('service_name')}: {(a.get('message') or '')[:120]}"
            for a in alerts
        ]
        blocks.append(
            f"[WATCHDOG ALERTS last {int(hours)}h]\n" + ("\n".join(lines) if lines else "- none in window")
        )
    except Exception as e:
        logger.warning(f"[project_agent] watchdog alerts gagal: {e}")
        blocks.append(f"[WATCHDOG ALERTS last {int(hours)}h] unavailable")

    try:
        from datetime import timedelta

        from services.mongodb_client import get_db as _gdb

        query = (
            {"workspace_id": str(ws_id)}
            if ws_id
            else {}
        )
        docs = await _gdb()["incident_episodes"].find(query).sort("timestamp", -1).limit(5).to_list(5)
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


async def _gather_knowledge(project_id: Optional[str], ws_id: Optional[str]) -> str:
    from services.knowledge_listing import build_project_knowledge_inventory

    if not project_id:
        return "[KNOWLEDGE] no project context"
    return await build_project_knowledge_inventory(project_id, ws_id)


def _build_suggestions(
    *, want_tickets: bool, want_errors: bool, want_knowledge: bool,
    open_count: int, alert_services: List[str], error_services: List[str],
    locale: str = "en",
) -> List[str]:
    """Predictive offers deterministik dari whitelist (bukan LLM) — bahasa ikut locale chat.
    DRY: delegasi ke services.offer_planner.build_chat_suggestions (satu sumber teks)."""
    from services.offer_planner import build_chat_suggestions

    return build_chat_suggestions(
        service_name=(error_services[0] if want_errors and error_services else
                      (alert_services[0] if alert_services else "")),
        root_cause=("service-fault" if want_errors and error_services else
                    ("downstream" if alert_services else "unknown")),
        has_open_tickets=bool(want_tickets and open_count > 0),
        want_knowledge=True,  # perilaku lama: chips knowledge hampir selalu default
        locale=locale,
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
        return {
            "formatted_message": (
                "⚠️ Sesi ini tidak punya konteks project. "
                "Buka chat dari halaman project untuk pertanyaan level project."
            ),
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
            msg = (
                f"🎟️ *Tiket `{key}-{num}`* — \"{ticket.get('title', '')}\"\n"
                f"*Status:* {ticket.get('status')} · *Severity:* {ticket.get('severity')} · "
                f"*Service:* `{ticket.get('serviceName') or '-'}`\n\n"
                "Untuk detail lengkap dan percakapan khusus tiket ini, silakan buka halaman detailnya."
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
                facts_blocks.append("[OPEN TICKETS (detail)]\n" + "\n".join(lines))
        except Exception as e:
            logger.warning(f"[project_agent] open ticket detail gagal: {e}")
            facts_blocks.append("[OPEN TICKETS (detail)] unavailable")

    if want_activity or want_errors:
        activity = await _gather_activity(project_id, ws_id, hours)
        facts_blocks.extend(activity[:2])  # tickets+alerts; episodes hanya bila relevan
        for line in "\n".join(activity).splitlines():
            low = line.lower()
            if "] " in line and ("alert" in low or "watchdog" in low):
                svc = line.split(":")[0].rsplit(" ", 1)[-1]
                if svc and svc not in alert_services:
                    alert_services.append(svc)

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
        facts_blocks.append(await _gather_knowledge(project_id, ws_id))

    # ── 4. Deteksi bahasa chat: isi percakapan dulu, preferensi user fallback ──
    from services.user_store import get_user_locale

    history = state.get("conversation_history") or []
    user_locale = await get_user_locale((state.get("sender") or {}).get("user_id"))
    locale = _detect_chat_locale(history, default=user_locale)

    suggestions = _build_suggestions(
        want_tickets=want_tickets, want_errors=want_errors, want_knowledge=want_knowledge,
        open_count=open_count, alert_services=alert_services, error_services=error_services,
        locale=locale,
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
            llm = get_chat_llm(temperature=0.2)
            messages = [
                SystemMessage(content=render_prompt("project_system")),
                HumanMessage(content=render_prompt(
                    "project_user",
                    question=intent_raw,
                    facts_block="\n\n".join(facts_blocks),
                    history_block=history_block,
                    reply_language=("English" if locale == "en" else "Bahasa Indonesia"),
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
