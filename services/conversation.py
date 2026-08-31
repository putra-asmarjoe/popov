"""
Conversation utilities — multi-turn context + clarify.

- `build_conversation_history()`: ambil riwayat chat_messages sesi (bounded) utk
  di-inject ke jawaban LLM (referensi "itu tadi", "lanjutkan" terbaca).
- `clarify_reply()`: titik LLM ke-7 — saat intent ambigu/out-of-konteks, hasilkan
  {route, question}. Bisa routing-rescue aksi tiket valid (mode=ticket_action),
  atau klarifikasi/redirect (mode=service_choice / guard). Fallback deterministik.

Selalu mengembalikan dict valid — tidak pernah dead-end.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TICKET_ACTION_OPTIONS = [
    "close ticket", "reopen", "change status", "change severity",
    "add label", "assign ticket", "add progress note", "summarize ticket condition",
]

# ── Deteksi bahasa chat (DRY — dipakai project_agent, ticket_agent, response_agent) ──
# "gunakan bahasa yang dipakai di chat; bila tidak terdeteksi → preferensi user"
_ID_WORDS = (
    "tiket", "berapa", "terbuka", "yang", "masih", "hari ini", "dibuat",
    "masuk", "tolong", "jelaskan", "saja", "pada", "saya", "itu", "tadi",
    "tampilkan", "buka", "ada", "tidak", "dengan",
)
_EN_WORDS = (
    "the", "how", "many", "what", "open", "tickets", "today", "about",
    "send", "detail", "please", "show", "list", "created", "are", "there",
    "is", "me", "give", "available", "project", "these",
)


def detect_chat_locale(history: Optional[List[dict]], default: str = "en") -> str:
    """Skor kata kunci Indonesia vs English dari pesan-pesan USER terakhir.

    Seri (skor sama) atau kosong → default (preferensi user).
    Pesan yang berupa INTENT TEKNIS dari chip/button (mis. "cek error pada {svc}",
    "berikan N data {svc}", "detail trace <hex>") TIDAK dihitung — itu bukan
    representasi bahasa user (Fix #140: chip Cek Detail kirim intent ID walau
    user EN, supaya tidak menyesatkan deteksi).
    """
    if not history:
        return default
    id_score = en_score = 0
    for h in history:
        if h.get("role") != "user":
            continue
        text = (h.get("content") or "").lower()
        if _is_technical_intent(text):
            continue
        id_score += sum(1 for w in _ID_WORDS if w in text)
        en_score += sum(1 for w in _EN_WORDS if w in text)
    if id_score == en_score:
        return default
    return "id" if id_score > en_score else "en"


def _is_technical_intent(text: str) -> bool:
    """True bila pesan user = intent teknis (dari chip/button, bukan bahasa natural user)."""
    t = (text or "").strip().lower()
    if not t:
        return False
    return any(p in t for p in ("cek error pada", "berikan ", "detail trace ", "cek koneksi",
                                "cek metrics", "rawlog", "health_check", "metrics:", "detail:",
                                "cek error terakhir", "centrall log"))


async def build_conversation_history(
    session_id: str,
    limit: int = 6,
    max_chars: int = 300,
) -> List[Dict[str, str]]:
    """Ambil N pesan terakhir sesi chat → [{role: user|assistant, content}]. Non-fatal."""
    if not session_id:
        return []
    try:
        from services.chat_store import get_messages

        msgs = await get_messages(session_id, limit=limit * 2)
        out: List[Dict[str, str]] = []
        for m in msgs:
            role = "user" if m.get("role") == "user" else "assistant"
            content = (m.get("content") or "").strip()[:max_chars]
            if content:
                out.append({"role": role, "content": content})
        return out[-limit:]
    except Exception as e:
        logger.warning(f"[Conversation] build_history failed: {e}")
        return []


def _render_history(history: Optional[List[dict]]) -> str:
    if not history:
        return "-"
    return "\n".join(f"[{h.get('role')}] {h.get('content', '')}" for h in history[-6:])


def _fallback_question(mode: str, options: Optional[List[str]]) -> str:
    opts = "\n".join(f"  • {o}" for o in (options or [])) or "-"
    if mode == "service_choice":
        return f"Service mana yang kamu maksud?\n{opts}"
    return (
        "Saya fokus membantu tiket yang sedang dibuka.\n"
        "Mau saya bantu dengan salah satu berikut?\n"
        f"{opts}"
    )


_MODE_RULES = {
    "ticket_action": (
        "The text is a command about a ticket. If it is clearly a VALID ticket action → fill route with "
        "{action, params} (action one of: close/reopen/change_status/set_severity/add_label/assign/add_progress; "
        "params matching the action). If unclear OR the text is OUTSIDE the ticket context (general chit-chat like "
        "'how are you'/'dollar price') → route=null and question = a question/suggestion that STEERS BACK to the ticket. "
        "Do NOT answer general questions."
    ),
    "service_choice": (
        "The text does not mention a clear service. Pick the most likely service from the options → "
        "route=null and question = ask for confirmation 'which service?'. Do NOT answer general questions."
    ),
    "guard": (
        "The text is OUTSIDE the ticket context. Do NOT answer it. route=null and question = a sentence that "
        "steers back to the ticket focus (offering ticket actions)."
    ),
}


async def clarify_reply(
    intent: str,
    *,
    context_text: str = "",
    options: Optional[List[str]] = None,
    history: Optional[List[dict]] = None,
    mode: str = "ticket_action",
) -> Dict[str, Any]:
    """Titik LLM ke-7. Return {"route": {"action","params"}|None, "question": str}.

    route diisi HANYA bila aksi tiket valid (whitelist) dan mode=ticket_action.
    Selalu fallback deterministik bila LLM gagal/timeout (tidak pernah dead-end).
    """
    from services.ticket_intent import ACTION_WHITELIST

    options = options or (TICKET_ACTION_OPTIONS if mode == "ticket_action" else [])
    hist = _render_history(history)
    ctx = context_text or "-"
    opt_str = "\n".join(f"- {o}" for o in options) or "-"
    rule = _MODE_RULES.get(mode, _MODE_RULES["ticket_action"])

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from services.llm_factory import get_chat_llm
        from services.prompt_loader import render as render_prompt
        import asyncio

        prompt = render_prompt(
            "ticket_clarify",
            context=ctx,
            history=hist,
            options=opt_str,
            rule=rule,
            intent=intent,
        )

        llm = get_chat_llm(temperature=0.2)
        resp = await asyncio.wait_for(
            llm.ainvoke([
                SystemMessage(content="You are an ops assistant. Reply with JSON only."),
                HumanMessage(content=prompt),
            ]),
            timeout=20.0,
        )
        txt = resp.content.strip() if hasattr(resp, "content") else str(resp)
        if "```" in txt:
            txt = txt.split("```")[1]
            if txt.strip().startswith("json"):
                txt = txt.strip()[4:]
        result = json.loads(txt.strip())
        route = result.get("route")
        question = str(result.get("question") or "").strip()
        if isinstance(route, dict) and route.get("action") in ACTION_WHITELIST:
            return {"route": {"action": route["action"], "params": route.get("params") or {}}, "question": question}
        return {"route": None, "question": question or _fallback_question(mode, options)}
    except Exception as e:
        logger.warning(f"[Conversation] clarify_reply LLM failed ({mode}): {e}")
        return {"route": None, "question": _fallback_question(mode, options)}