"""
Ticket Agent — node graph untuk MENGELOLA tiket via chat (bukan analisis insiden).

Lane baru yang TIDAK menyentuh pipeline analisis (triage/planner/fan-out/correlation).
Alur: resolve actor + tiket sesi → LLM parse aksi (atau pending_offer dari tawaran)
      → cek izin → eksekusi ticket_store → bangun konfirmasi deterministik
      → tawarkan aksi lanjutan (Offer Session) → response_agent.

Scope saat ini = tiket sesi yang terbuka (ticket_context.ticket_id). Global = next.
Create tiket via chat = ditunda.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.ticket_intent import parse_ticket_intent, is_ticket_question, is_member_query
from services.ticket_store import (
    add_progress_note,
    can_reopen,
    change_status,
    get_ticket,
    public_ticket,
    reopen_ticket,
    set_assignees,
    update_ticket,
    VALID_SEVERITIES,
)
from services.user_store import get_user
from services.workspace_store import find_project_by_id, find_workspace_by_id, get_membership, is_workspace_admin
from services.offer_planner import build_ticket_offer, render_offer_question
from services.offer_session import create_offer
from services.conversation import clarify_reply
from services.llm_factory import get_chat_llm
from services.prompt_loader import render as render_prompt
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


# ── Teks konfirmasi aksi tiket — bilingual (Fix #145) ─────────────────────────
# Semua pesan user-facing di ticket_agent harus ikut bahasa user (detect → preferensi).
_TICKET_ACTION_TEXTS = {
    "id": {
        "err_user": "Tidak dapat mengidentifikasi pengguna.",
        "err_user_not_found": "Pengguna tidak ditemukan.",
        "err_no_ticket": "Tidak ada konteks tiket terbuka. Buka tiket dari detail tiket.",
        "err_ticket_not_found": "Tiket tidak ditemukan.",
        "err_project": "Project tiket tidak ditemukan.",
        "err_workspace": "Workspace tiket tidak ditemukan.",
        "err_not_member": "Kamu bukan member workspace tiket ini.",
        "err_permission": "⛔ Hanya pembuat, assignee, atau admin workspace yang bisa mengubah severity/label tiket {display}.",
        "already_closed": "ℹ️ Tiket {display} sudah *closed*.",
        "closed": "✅ Tiket {display} {verb}.",
        "closed_resolved": "ditutup (resolved)",
        "closed_closed": "ditutup (closed)",
        "err_reopen": "⚠️ Hanya tiket resolved/closed yang bisa dibuka kembali. Status saat ini: *{status}*.",
        "reopened": "🔄 Tiket {display} dibuka kembali (status *open*).",
        "status_changed": "✅ Status tiket {display} diubah: *{old}* → *{new}*.",
        "err_severity": "⚠️ Severity tidak valid: {severity}",
        "severity_changed": "✅ Severity tiket {display}: *{old}* → *{new}*.",
        "label_updated": "🏷️ Label tiket {display} diperbarui: `{labels}`.",
        "err_member": "⚠️ Tidak menemukan member workspace: {names}. Member tersedia: {members}.",
        "assigned": "👥 Tiket {display} di-assign ke {count} user.",
        "err_progress_empty": "⚠️ Catatan progress tidak boleh kosong untuk tiket {display}.",
        "progress_added": "📝 Progress tiket {display} ditambahkan.",
        "err_action": "⚠️ Aksi tiket tidak didukung.",
        "err_execute": "⚠️ Gagal memproses aksi: {error}",
        "clarify_fallback": "⚠️ Tidak dapat memahami permintaan.",
    },
    "en": {
        "err_user": "Cannot identify the user.",
        "err_user_not_found": "User not found.",
        "err_no_ticket": "No open ticket context. Open a ticket from the ticket detail.",
        "err_ticket_not_found": "Ticket not found.",
        "err_project": "Ticket project not found.",
        "err_workspace": "Ticket workspace not found.",
        "err_not_member": "You are not a member of this ticket's workspace.",
        "err_permission": "⛔ Only the creator, assignee, or workspace admin can change severity/label of ticket {display}.",
        "already_closed": "ℹ️ Ticket {display} is already *closed*.",
        "closed": "✅ Ticket {display} {verb}.",
        "closed_resolved": "closed (resolved)",
        "closed_closed": "closed",
        "err_reopen": "⚠️ Only resolved/closed tickets can be reopened. Current status: *{status}*.",
        "reopened": "🔄 Ticket {display} reopened (status *open*).",
        "status_changed": "✅ Status of ticket {display} changed: *{old}* → *{new}*.",
        "err_severity": "⚠️ Invalid severity: {severity}",
        "severity_changed": "✅ Severity of ticket {display}: *{old}* → *{new}*.",
        "label_updated": "🏷️ Label of ticket {display} updated: `{labels}`.",
        "err_member": "⚠️ Workspace member not found: {names}. Available members: {members}.",
        "assigned": "👥 Ticket {display} assigned to {count} user(s).",
        "err_progress_empty": "⚠️ Progress note cannot be empty for ticket {display}.",
        "progress_added": "📝 Progress note added to ticket {display}.",
        "err_action": "⚠️ Unsupported ticket action.",
        "err_execute": "⚠️ Failed to process action: {error}",
        "clarify_fallback": "⚠️ Could not understand the request.",
    },
}


async def _locale_for_state(state: dict) -> str:
    """Locale bahasa user utk teks aksi — detect chat dulu, preferensi user fallback."""
    from services.conversation import detect_chat_locale
    from services.user_store import get_user_locale

    user_locale = await get_user_locale((state.get("sender") or {}).get("user_id"))
    return detect_chat_locale(state.get("conversation_history") or [], default=user_locale)


def _ticket_t(key: str, locale: str = "id", **fmt) -> str:
    """Satu teks aksi tiket bilingual (dict en/id)."""
    texts = _TICKET_ACTION_TEXTS.get(locale, _TICKET_ACTION_TEXTS["id"])
    tmpl = texts.get(key, texts["err_action"])
    return tmpl.format(**fmt) if fmt else tmpl


def _is_editor(ticket: Dict[str, Any], user_id: str) -> bool:
    uid = str(user_id)
    return uid == str(ticket.get("createdBy")) or uid in ticket.get("assignees", [])


def _resolve_assignees(names: List[str], members: List[Dict[str, Any]]) -> tuple[List[str], List[str]]:
    """Cocokkan nama/email assignee ke member workspace.
    Return (matched_user_ids, unmatched). Match case-insensitive substring nama / exact email."""
    matched: List[str] = []
    unmatched: List[str] = []
    members_low = [
        {
            "userId": m["userId"],
            "name": (m.get("name") or "").lower(),
            "email": (m.get("email") or "").lower(),
        }
        for m in members
    ]
    for raw in names:
        q = (raw or "").strip().lower()
        if not q:
            continue
        hit = next(
            (m for m in members_low if q in m["name"] or q == m["email"]),
            None,
        )
        if hit and hit["userId"] not in matched:
            matched.append(hit["userId"])
        else:
            unmatched.append(raw)
    return matched, unmatched


async def _load_actor_and_ticket(state: dict, locale: str = "id") -> tuple[Optional[Dict], Optional[Dict], str]:
    """Return (user, ticket, error_msg). Salah satu None bila gagal. Pesan error bilingual."""
    user_id = (state.get("sender") or {}).get("user_id")
    tc = state.get("ticket_context") or {}
    ticket_id = tc.get("ticket_id")

    if not user_id:
        return None, None, _ticket_t("err_user", locale)
    user = await get_user(user_id)
    if not user:
        return None, None, _ticket_t("err_user_not_found", locale)
    if not ticket_id:
        return None, None, _ticket_t("err_no_ticket", locale)
    ticket = await get_ticket(str(ticket_id))
    if not ticket:
        return None, None, _ticket_t("err_ticket_not_found", locale)
    return user, ticket, ""


async def _load_workspace(ticket: Dict[str, Any], user_id: str, locale: str = "id") -> tuple[Optional[Dict], Optional[Dict], str]:
    project = await find_project_by_id(str(ticket.get("projectId", "")))
    if not project:
        return None, None, _ticket_t("err_project", locale)
    ws = await find_workspace_by_id(str(project.get("workspaceId", "")))
    if not ws:
        return None, None, _ticket_t("err_workspace", locale)
    if get_membership(ws, user_id) is None:
        return None, None, _ticket_t("err_not_member", locale)
    return project, ws, ""


async def _member_list(ws: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Member workspace + nama/email (ws.members hanya berisi userId/role — fetch user)."""
    out: List[Dict[str, Any]] = []
    for m in ws.get("members", []):
        uid = str(m.get("userId", ""))
        u = await get_user(uid) if uid else None
        out.append({
            "userId": uid,
            "name": (u or {}).get("name", ""),
            "email": (u or {}).get("email", ""),
        })
    return out


async def _reply(state: dict, agents_visited: list, message: str, result: Optional[dict] = None,
                 suggestions: Optional[List[str]] = None) -> dict:
    reply = {
        "formatted_message": message,
        "ticket_result": result if result is not None else {"ok": False},
        "next_agent": "response_agent",
        "agents_visited": agents_visited,
        "error": None,
    }
    if suggestions:
        reply["chat_suggestions"] = suggestions
    return reply


async def _execute_action(
    state: dict,
    agents_visited: list,
    user: Dict[str, Any],
    ticket: Dict[str, Any],
    project: Dict[str, Any],
    ws: Dict[str, Any],
    action: str,
    params: dict,
    locale: str = "id",
) -> dict:
    """Eksekusi satu aksi tiket + izin. Return reply dict (via _reply).
    locale (Fix #145): bahasa konfirmasi ikut user (detect → preferensi)."""
    status_now = ticket.get("status", "open")
    display = f"{project.get('key', 'TKT')}-{ticket.get('ticketNumber')}"

    if action in ("set_severity", "add_label") and not (
        _is_editor(ticket, str(user["_id"])) or is_workspace_admin(ws, str(user["_id"]))
    ):
        return await _reply(state, agents_visited,
                            _ticket_t("err_permission", locale, display=display))

    try:
        if action == "close":
            target = "closed" if status_now == "resolved" else "resolved"
            if status_now == "closed":
                return await _reply(state, agents_visited, _ticket_t("already_closed", locale, display=display))
            updated, cerr = await change_status(ticket, target, user, via="agent")
            if cerr:
                return await _reply(state, agents_visited, f"⚠️ {cerr}")
            verb = _ticket_t("closed_resolved", locale) if target == "resolved" else _ticket_t("closed_closed", locale)
            msg = _ticket_t("closed", locale, display=display, verb=verb)

        elif action == "reopen":
            if not can_reopen(status_now):
                return await _reply(state, agents_visited,
                                    _ticket_t("err_reopen", locale, status=status_now))
            updated = await reopen_ticket(ticket, user, via="agent")
            msg = _ticket_t("reopened", locale, display=display)

        elif action == "change_status":
            target = params["status"]
            updated, cerr = await change_status(ticket, target, user, via="agent")
            if cerr:
                return await _reply(state, agents_visited, f"⚠️ {cerr}")
            msg = _ticket_t("status_changed", locale, display=display, old=status_now, new=target)

        elif action == "set_severity":
            severity = params["severity"]
            if severity not in VALID_SEVERITIES:
                return await _reply(state, agents_visited, _ticket_t("err_severity", locale, severity=severity))
            updated = await update_ticket(str(ticket["_id"]), severity=severity, actor=user, via="agent")
            msg = _ticket_t("severity_changed", locale, display=display,
                            old=ticket.get("severity"), new=severity)

        elif action == "add_label":
            new_labels = params["labels"]
            combined = list(dict.fromkeys([*(ticket.get("tags") or []), *new_labels]))
            updated = await update_ticket(str(ticket["_id"]), tags=combined)
            msg = _ticket_t("label_updated", locale, display=display,
                            labels=", ".join(combined) or "-")

        elif action == "assign":
            names = params.get("assignees") or (params.get("name") and [params["name"]] or [])
            if isinstance(names, str):
                names = [names]
            members = await _member_list(ws)
            ids, unmatched = _resolve_assignees([str(n) for n in names], members)
            if unmatched:
                member_names = ", ".join(m["name"] or m["email"] for m in members) or "-"
                return await _reply(state, agents_visited,
                                    _ticket_t("err_member", locale, names=", ".join(unmatched), members=member_names))
            updated = await set_assignees(str(ticket["_id"]), ids)
            msg = _ticket_t("assigned", locale, display=display, count=len(ids))

        elif action == "add_progress":
            note = str(params.get("note") or "").strip()
            if not note:
                return await _reply(state, agents_visited,
                                    _ticket_t("err_progress_empty", locale, display=display))
            updated = await add_progress_note(ticket, note, user)
            msg = _ticket_t("progress_added", locale, display=display)

        else:
            return await _reply(state, agents_visited, _ticket_t("err_action", locale))

    except Exception as e:
        logger.error(f"TicketAgent execute failed action={action}: {e}", exc_info=True)
        return await _reply(state, agents_visited, _ticket_t("err_execute", locale, error=str(e)[:200]))

    result = {
        "ok": True,
        "action": action,
        "ticket_id": str(ticket["_id"]),
        "ticket_number": display,
        "status": (updated or {}).get("status") if updated else None,
    }
    logger.info(f"TicketAgent {action} success {display} by {user.get('email')}")
    return await _reply(state, agents_visited, msg, result)


async def _offer_next(state: dict, agents_visited: list, ticket: Dict[str, Any],
                      project: Dict[str, Any], action_executed: str, message: str,
                      locale: str = "id") -> str:
    """Setelah aksi sukses, tawarkan aksi lanjutan (web chat). Return pesan + tawaran.
    locale (Fix #145): pertanyaan offer bilingual."""
    offer = build_ticket_offer(action_executed, ticket, project, locale)
    if not offer:
        return message
    sender = state.get("sender") or {}
    session_id = sender.get("session_id")
    if not session_id:
        return message  # non-web (telegram/api) — tawaran tiket khusus web chat
    offer_id = await create_offer(
        type_=offer["type"], params=offer["params"], question=offer["question"],
        needs_param=offer["needs_param"], session_id=session_id, ticket_id=str(ticket["_id"]),
    )
    if not offer_id:
        return message
    return f"{message}\n\n{render_offer_question(offer)}"


async def _load_alerts(ticket_id: str) -> List[Dict[str, Any]]:
    """Alert ter-link tiket (ticket_alerts) utk konteks jawaban — Fix #198.
    Tanpa ini agent hanya punya description tiket, tidak 'mengetahui' alert aslinya
    (nama/severity/source/traceIds) sehingga jawaban soal alert jadi generik."""
    try:
        from services.ticket_alert_store import list_alerts_for_ticket, public_alert
        return [public_alert(a) for a in await list_alerts_for_ticket(str(ticket_id))]
    except Exception as e:
        logger.warning(f"TicketAgent load alerts failed: {e}")
        return []


def _alert_lines(alerts: List[Dict[str, Any]], locale: str = "id") -> str:
    """Baris alert utk ringkasan deterministik — bilingual (Fix #198)."""
    if not alerts:
        return ""
    lines = []
    for a in alerts[:5]:
        trace_n = len(a.get("traceIds") or [])
        lines.append(
            f"  • `{a.get('name') or 'alert'}` · severity `{a.get('severity')}`"
            f" · source `{a.get('source')}` · traceIds `{trace_n}`"
            + (f" · svc `{a.get('serviceName')}`" if a.get("serviceName") else "")
        )
    head = (f"  • *Linked Alerts:* ({len(alerts)})" if locale == "en"
            else f"  • *Alert Ter-Link:* ({len(alerts)})")
    return head + "\n" + "\n".join(lines) + "\n"


async def _build_ticket_summary_deterministic(ticket: Dict[str, Any], project: Dict[str, Any],
                                              locale: str = "id") -> str:
    """Ringkasan deterministik tiket (fallback bila LLM gagal) — bilingual (Fix #145)."""
    alerts = await _load_alerts(str(ticket.get("_id", "")))
    display = f"{project.get('key', 'TKT')}-{ticket.get('ticketNumber')}"
    title = ticket.get("title") or "-"
    status = ticket.get("status") or "open"
    sev = ticket.get("severity") or "-"
    kind = ticket.get("kind") or "-"
    svc = ticket.get("serviceName") or "-"
    env = ticket.get("environment") or "-"
    tags = ", ".join(ticket.get("tags") or []) or "-"
    created_by = ticket.get("createdByName") or "-"
    assignee_ids = ticket.get("assignees") or []
    names = []
    for uid in assignee_ids:
        u = await get_user(str(uid))
        if u:
            names.append(u.get("name") or u.get("email") or str(uid))
    assignees = ", ".join(names) or "-"
    progress_lines = []
    for p in ticket.get("progressLog") or []:
        who = p.get("byName") or p.get("by") or "-"
        at = (p.get("at") or "")[:16].replace("T", " ")
        note = (p.get("note") or "").strip()
        progress_lines.append(f"  • `[{who} {at}]` {note}")
    progress_block = "\n".join(progress_lines) if progress_lines else "  (none yet)" if locale == "en" else "  (belum ada catatan)"
    alert_block = _alert_lines(alerts, locale)
    if locale == "en":
        return (
            f"📋 *Ticket {display}* — {title}\n"
            f"  • Status: *{status}* | Severity: {sev} | Kind: {kind}\n"
            f"  • Service: `{svc}` | Env: {env}\n"
            f"  • Created by: {created_by}\n"
            f"  • Assignees: {assignees}\n"
            f"  • Tags: {tags}\n"
            f"  • *Progress Log:*\n{progress_block}"
            + (f"\n{alert_block}" if alert_block else "")
        )
    return (
        f"📋 *Tiket {display}* — {title}\n"
        f"  • Status: *{status}* | Severity: {sev} | Kind: {kind}\n"
        f"  • Service: `{svc}` | Env: {env}\n"
        f"  • Dibuat oleh: {created_by}\n"
        f"  • Assignees: {assignees}\n"
        f"  • Tags: {tags}\n"
        f"  • *Progress Log:*\n{progress_block}"
        + (f"\n{alert_block}" if alert_block else "")
    )


async def _build_ticket_summary(ticket: Dict[str, Any], project: Dict[str, Any], intent: str,
                                history: Optional[List[dict]] = None, reply_language: str = "English") -> str:
    """Jawab pertanyaan tentang tiket memakai LLM (konteks tiket + riwayat). Fallback deterministik.
    reply_language (Fix #144): kunci bahasa jawaban — "English" / "Bahasa Indonesia"."""
    import asyncio
    import json

    display = f"{project.get('key', 'TKT')}-{ticket.get('ticketNumber')}"
    assignee_ids = ticket.get("assignees") or []
    names = []
    for uid in assignee_ids:
        u = await get_user(str(uid))
        if u:
            names.append(u.get("name") or u.get("email") or str(uid))
    # Fix #198: alert ter-link ikut dikirim ke LLM — agent 'mengetahui' alert asli
    # (nama/severity/source/traceIds) bukan hanya description tiket yang ter-truncate.
    alerts = await _load_alerts(str(ticket.get("_id", "")))
    data = {
        "ticket": display,
        "title": ticket.get("title"),
        "status": ticket.get("status"),
        "severity": ticket.get("severity"),
        "kind": ticket.get("kind"),
        "service": ticket.get("serviceName"),
        "environment": ticket.get("environment"),
        "created_by": ticket.get("createdByName"),
        "assignees": names,
        "tags": ticket.get("tags") or [],
        "description": (ticket.get("description") or "")[:2000],
        "progress_log": ticket.get("progressLog") or [],
        "alerts": alerts,
    }
    hist_lines = "\n".join(f"[{h.get('role')}] {h.get('content','')}" for h in (history or [])[-6:]) or "-"
    try:
        llm = get_chat_llm(temperature=0.3)
        prompt = render_prompt(
            "ticket_summary",
            ticket_json=json.dumps(data, ensure_ascii=False, indent=2, default=str),
            history=hist_lines,
            intent=intent,
            reply_language=reply_language,
        )
        resp = await asyncio.wait_for(
            llm.ainvoke([SystemMessage(content="Answer concisely in Telegram Markdown."), HumanMessage(content=prompt)]),
            timeout=20.0,
        )
        text = (resp.content or "").strip() if hasattr(resp, "content") else str(resp).strip()
        if text:
            return text
    except Exception as e:
        logger.warning(f"TicketAgent summary LLM failed (fallback deterministik): {e}")
    return await _build_ticket_summary_deterministic(ticket, project,
                                                     "id" if reply_language.lower() == "bahasa indonesia" else "en")


async def _ticket_suggestions(ticket: Dict[str, Any], project: Dict[str, Any], state: dict) -> List[str]:
    """Chips follow-up utk chat tiket (web) — deterministik, bilingual (DRY via offer_planner)."""
    from services.conversation import detect_chat_locale
    from services.offer_planner import build_chat_suggestions
    from services.user_store import get_user_locale

    history = state.get("conversation_history") or []
    user_locale = await get_user_locale((state.get("sender") or {}).get("user_id"))
    locale = detect_chat_locale(history, default=user_locale)
    # intent (Fix #215): skip chip yang topiknya sudah ditanyakan user
    return build_chat_suggestions(ticket=ticket, project=project, locale=locale,
                                  max_items=3, intent=state.get("intent") or "")


async def ticket_agent(state: dict) -> dict:
    agents_visited = state.get("agents_visited", []) + ["ticket_agent"]
    intent = state.get("intent", "")
    # Fix #145: bahasa semua konfirmasi/error ikut user (detect chat → preferensi)
    locale = await _locale_for_state(state)

    user, ticket, err = await _load_actor_and_ticket(state, locale)
    if err:
        return await _reply(state, agents_visited, f"⚠️ {err}")
    project, ws, err = await _load_workspace(ticket, str(user["_id"]), locale)
    if err:
        return await _reply(state, agents_visited, f"⚠️ {err}")

    # Pertanyaan tentang tiket → jawab via LLM dengan konteks tiket + riwayat.
    # Fix #197 (Lapis 5): lane arbiter memaksa pertanyaan → summary (bypass parse aksi).
    if state.get("ticket_question_forced"):
        _reply_lang = "English" if locale == "en" else "Bahasa Indonesia"
        summary = await _build_ticket_summary(ticket, project, intent,
                                              state.get("conversation_history"), _reply_lang)
        suggestions = await _ticket_suggestions(ticket, project, state)
        return await _reply(state, agents_visited, summary,
                            {"ok": True, "action": "summary", "ticket_id": str(ticket["_id"])},
                            suggestions=suggestions)

    if is_ticket_question(intent):
        _reply_lang = "English" if locale == "en" else "Bahasa Indonesia"
        summary = await _build_ticket_summary(ticket, project, intent,
                                              state.get("conversation_history"), _reply_lang)
        suggestions = await _ticket_suggestions(ticket, project, state)
        return await _reply(state, agents_visited, summary,
                            {"ok": True, "action": "summary", "ticket_id": str(ticket["_id"])},
                            suggestions=suggestions)

    # Fix #146: "who can i assign this ticket?" → daftar member (bukan parse assign)
    if is_member_query(intent):
        members = await _member_list(ws)
        if locale == "en":
            member_lines = "\n".join(f"• {m['name'] or m['email']}" for m in members) or "• (no members)"
            msg = (f"👥 *Members you can assign to ticket {project.get('key', 'TKT')}-{ticket.get('ticketNumber')}:*\n"
                   f"{member_lines}\n\n"
                   f"Just say: *assign to <name>*")
        else:
            member_lines = "\n".join(f"• {m['name'] or m['email']}" for m in members) or "• (belum ada member)"
            msg = (f"👥 *Member yang bisa di-assign ke tiket {project.get('key', 'TKT')}-{ticket.get('ticketNumber')}:*\n"
                   f"{member_lines}\n\n"
                   f"Katakan saja: *assign ke <nama>*")
        return await _reply(state, agents_visited, msg,
                            {"ok": True, "action": "member_query", "ticket_id": str(ticket["_id"])})

    # Jalur tawaran (offer) yang diterima user — aksi eksplisit, tanpa LLM parse.
    pending = state.get("pending_offer")
    if pending and pending.get("action"):
        reply = await _execute_action(state, agents_visited, user, ticket, project, ws,
                                      pending["action"], pending.get("params") or {}, locale)
        # jangan tawarkan lagi setelah eksekusi offer (hindari loop ya→ya)
        return reply

    members = await _member_list(ws)
    parsed = await parse_ticket_intent(intent, public_ticket(ticket), members)
    if not parsed:
        # Ambigu / di luar konteks tiket → klarifikasi natural (LLM) + routing-rescue.
        summary_ctx = await _build_ticket_summary_deterministic(ticket, project, locale)
        clarify = await clarify_reply(
            intent,
            context_text=summary_ctx,
            history=state.get("conversation_history"),
            mode="ticket_action",
        )
        route = clarify.get("route")
        if route and route.get("action"):
            logger.info(f"TicketAgent routing-rescue action={route['action']} (clarify)")
            return await _execute_action(state, agents_visited, user, ticket, project, ws,
                                         route["action"], route.get("params") or {}, locale)
        return await _reply(state, agents_visited,
                            clarify.get("question") or _ticket_t("clarify_fallback", locale),
                            {"ok": False, "action": "clarify"})

    action = parsed["action"]
    params = parsed.get("params") or {}
    reply = await _execute_action(state, agents_visited, user, ticket, project, ws, action, params, locale)
    if reply.get("ticket_result", {}).get("ok"):
        reply["formatted_message"] = await _offer_next(
            state, agents_visited, ticket, project, action, reply.get("formatted_message", ""), locale
        )
        reply["chat_suggestions"] = await _ticket_suggestions(ticket, project, state)
    return reply
