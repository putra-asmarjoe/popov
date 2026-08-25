"""
Ticket Agent — node graph untuk MENGELOLA tiket via chat (bukan analisis insiden).

Lane baru yang TIDAK menyentuh pipeline analisis (triage/planner/fan-out/correlation).
Alur: resolve actor + tiket sesi → LLM parse aksi (atau pending_offer dari tawaran)
      → cek izin → eksekusi ticket_store → bangun konfirmasi deterministik
      → tawarkan aksi lanjutan (Offer Session) → telegram_agent.

Scope saat ini = tiket sesi yang terbuka (ticket_context.ticket_id). Global = next.
Create tiket via chat = ditunda.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.ticket_intent import parse_ticket_intent, is_ticket_question
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


async def _load_actor_and_ticket(state: dict) -> tuple[Optional[Dict], Optional[Dict], str]:
    """Return (user, ticket, error_msg). Salah satu None bila gagal."""
    user_id = (state.get("sender") or {}).get("user_id")
    tc = state.get("ticket_context") or {}
    ticket_id = tc.get("ticket_id")

    if not user_id:
        return None, None, "Tidak dapat mengidentifikasi pengguna."
    user = await get_user(user_id)
    if not user:
        return None, None, "Pengguna tidak ditemukan."
    if not ticket_id:
        return None, None, "Tidak ada konteks tiket terbuka. Buka tiket dari detail tiket."
    ticket = await get_ticket(str(ticket_id))
    if not ticket:
        return None, None, "Tiket tidak ditemukan."
    return user, ticket, ""


async def _load_workspace(ticket: Dict[str, Any], user_id: str) -> tuple[Optional[Dict], Optional[Dict], str]:
    project = await find_project_by_id(str(ticket.get("projectId", "")))
    if not project:
        return None, None, "Project tiket tidak ditemukan."
    ws = await find_workspace_by_id(str(project.get("workspaceId", "")))
    if not ws:
        return None, None, "Workspace tiket tidak ditemukan."
    if get_membership(ws, user_id) is None:
        return None, None, "Kamu bukan member workspace tiket ini."
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


async def _reply(state: dict, agents_visited: list, message: str, result: Optional[dict] = None) -> dict:
    return {
        "formatted_message": message,
        "ticket_result": result if result is not None else {"ok": False},
        "next_agent": "telegram_agent",
        "agents_visited": agents_visited,
        "error": None,
    }


async def _execute_action(
    state: dict,
    agents_visited: list,
    user: Dict[str, Any],
    ticket: Dict[str, Any],
    project: Dict[str, Any],
    ws: Dict[str, Any],
    action: str,
    params: dict,
) -> dict:
    """Eksekusi satu aksi tiket + izin. Return reply dict (via _reply)."""
    status_now = ticket.get("status", "open")
    display = f"{project.get('key', 'TKT')}-{ticket.get('ticketNumber')}"

    if action in ("set_severity", "add_label") and not (
        _is_editor(ticket, str(user["_id"])) or is_workspace_admin(ws, str(user["_id"]))
    ):
        return await _reply(state, agents_visited,
                            f"⛔ Hanya pembuat, assignee, atau admin workspace yang bisa mengubah severity/label tiket {display}.")

    try:
        if action == "close":
            target = "closed" if status_now == "resolved" else "resolved"
            if status_now == "closed":
                return await _reply(state, agents_visited, f"ℹ️ Tiket {display} sudah *closed*.")
            updated, cerr = await change_status(ticket, target, user)
            if cerr:
                return await _reply(state, agents_visited, f"⚠️ {cerr}")
            verb = "ditutup (resolved)" if target == "resolved" else "ditutup (closed)"
            msg = f"✅ Tiket {display} {verb}."

        elif action == "reopen":
            if not can_reopen(status_now):
                return await _reply(state, agents_visited,
                                    f"⚠️ Hanya tiket resolved/closed yang bisa dibuka kembali. Status saat ini: *{status_now}*.")
            updated = await reopen_ticket(ticket, user)
            msg = f"🔄 Tiket {display} dibuka kembali (status *open*)."

        elif action == "change_status":
            target = params["status"]
            updated, cerr = await change_status(ticket, target, user)
            if cerr:
                return await _reply(state, agents_visited, f"⚠️ {cerr}")
            msg = f"✅ Status tiket {display} diubah: *{status_now}* → *{target}*."

        elif action == "set_severity":
            severity = params["severity"]
            if severity not in VALID_SEVERITIES:
                return await _reply(state, agents_visited, f"⚠️ Severity tidak valid: {severity}")
            updated = await update_ticket(str(ticket["_id"]), severity=severity)
            msg = f"✅ Severity tiket {display}: *{ticket.get('severity')}* → *{severity}*."

        elif action == "add_label":
            new_labels = params["labels"]
            combined = list(dict.fromkeys([*(ticket.get("tags") or []), *new_labels]))
            updated = await update_ticket(str(ticket["_id"]), tags=combined)
            msg = f"🏷️ Label tiket {display} diperbarui: `{', '.join(combined) or '-'}`."

        elif action == "assign":
            names = params.get("assignees") or (params.get("name") and [params["name"]] or [])
            if isinstance(names, str):
                names = [names]
            members = await _member_list(ws)
            ids, unmatched = _resolve_assignees([str(n) for n in names], members)
            if unmatched:
                member_names = ", ".join(m["name"] or m["email"] for m in members) or "-"
                return await _reply(state, agents_visited,
                                    f"⚠️ Tidak menemukan member workspace: {', '.join(unmatched)}. "
                                    f"Member tersedia: {member_names}.")
            updated = await set_assignees(str(ticket["_id"]), ids)
            msg = f"👥 Tiket {display} di-assign ke {len(ids)} user."

        elif action == "add_progress":
            note = str(params.get("note") or "").strip()
            if not note:
                return await _reply(state, agents_visited,
                                    f"⚠️ Catatan progress tidak boleh kosong untuk tiket {display}.")
            updated = await add_progress_note(ticket, note, user)
            msg = f"📝 Progress tiket {display} ditambahkan."

        else:
            return await _reply(state, agents_visited, "⚠️ Aksi tiket tidak didukung.")

    except Exception as e:
        logger.error(f"TicketAgent execute failed action={action}: {e}", exc_info=True)
        return await _reply(state, agents_visited, f"⚠️ Gagal memproses aksi: {str(e)[:200]}")

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
                      project: Dict[str, Any], action_executed: str, message: str) -> str:
    """Setelah aksi sukses, tawarkan aksi lanjutan (web chat). Return pesan + tawaran."""
    offer = build_ticket_offer(action_executed, ticket, project)
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


async def _build_ticket_summary_deterministic(ticket: Dict[str, Any], project: Dict[str, Any]) -> str:
    """Ringkasan deterministik tiket (fallback bila LLM gagal)."""
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
    progress_block = "\n".join(progress_lines) if progress_lines else "  (belum ada catatan)"
    return (
        f"📋 *Tiket {display}* — {title}\n"
        f"  • Status: *{status}* | Severity: {sev} | Kind: {kind}\n"
        f"  • Service: `{svc}` | Env: {env}\n"
        f"  • Dibuat oleh: {created_by}\n"
        f"  • Assignees: {assignees}\n"
        f"  • Tags: {tags}\n"
        f"  • *Progress Log:*\n{progress_block}"
    )


async def _build_ticket_summary(ticket: Dict[str, Any], project: Dict[str, Any], intent: str,
                                history: Optional[List[dict]] = None) -> str:
    """Jawab pertanyaan tentang tiket memakai LLM (konteks tiket + riwayat). Fallback deterministik."""
    import asyncio
    import json

    display = f"{project.get('key', 'TKT')}-{ticket.get('ticketNumber')}"
    assignee_ids = ticket.get("assignees") or []
    names = []
    for uid in assignee_ids:
        u = await get_user(str(uid))
        if u:
            names.append(u.get("name") or u.get("email") or str(uid))
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
    }
    hist_lines = "\n".join(f"[{h.get('role')}] {h.get('content','')}" for h in (history or [])[-6:]) or "-"
    try:
        llm = get_chat_llm(temperature=0.3)
        prompt = render_prompt(
            "ticket_summary",
            ticket_json=json.dumps(data, ensure_ascii=False, indent=2, default=str),
            history=hist_lines,
            intent=intent,
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
    return await _build_ticket_summary_deterministic(ticket, project)


async def ticket_agent(state: dict) -> dict:
    agents_visited = state.get("agents_visited", []) + ["ticket_agent"]
    intent = state.get("intent", "")

    user, ticket, err = await _load_actor_and_ticket(state)
    if err:
        return await _reply(state, agents_visited, f"⚠️ {err}")
    project, ws, err = await _load_workspace(ticket, str(user["_id"]))
    if err:
        return await _reply(state, agents_visited, f"⚠️ {err}")

    # Pertanyaan tentang tiket → jawab via LLM dengan konteks tiket + riwayat.
    if is_ticket_question(intent):
        summary = await _build_ticket_summary(ticket, project, intent, state.get("conversation_history"))
        return await _reply(state, agents_visited, summary,
                            {"ok": True, "action": "summary", "ticket_id": str(ticket["_id"])})

    # Jalur tawaran (offer) yang diterima user — aksi eksplisit, tanpa LLM parse.
    pending = state.get("pending_offer")
    if pending and pending.get("action"):
        reply = await _execute_action(state, agents_visited, user, ticket, project, ws,
                                      pending["action"], pending.get("params") or {})
        # jangan tawarkan lagi setelah eksekusi offer (hindari loop ya→ya)
        return reply

    members = await _member_list(ws)
    parsed = await parse_ticket_intent(intent, public_ticket(ticket), members)
    if not parsed:
        # Ambigu / di luar konteks tiket → klarifikasi natural (LLM) + routing-rescue.
        summary_ctx = await _build_ticket_summary_deterministic(ticket, project)
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
                                         route["action"], route.get("params") or {})
        return await _reply(state, agents_visited, clarify.get("question") or "⚠️ Tidak dapat memahami permintaan.",
                            {"ok": False, "action": "clarify"})

    action = parsed["action"]
    params = parsed.get("params") or {}
    reply = await _execute_action(state, agents_visited, user, ticket, project, ws, action, params)
    if reply.get("ticket_result", {}).get("ok"):
        reply["formatted_message"] = await _offer_next(
            state, agents_visited, ticket, project, action, reply.get("formatted_message", "")
        )
    return reply
