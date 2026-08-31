"""
Ticket intent — memisahkan DETEKSI (rule murah) dari PARSING (LLM).

Aksi yang didukung (scope saat ini = tiket sesi yang terbuka; create ditunda):
  close | reopen | change_status | set_severity | add_label | assign | add_progress

- `is_ticket_intent()`  : gate rule-based murah untuk supervisor (mensyaratkan
                          state.ticket_context ada — global scope = next).
- `parse_ticket_intent()`: LLM mengekstrak {action, params} dari freeform intent.
                          Dipanggil HANYA bila gate lolos (hemat LLM).

Ini titik LLM ke-5 (penyimpangan sadar dari "4 titik") — dipakai hanya untuk
parsing aksi tiket, temperature rendah + validasi ketat.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Aksi yang DIKENALI & BOLEH dieksekusi (whitelist — anti LLM mengarang aksi)
ACTION_WHITELIST = {
    "close",
    "reopen",
    "change_status",
    "set_severity",
    "add_label",
    "assign",
    "add_progress",
}

# Keyword murah untuk gate deteksi (rule-based, tanpa LLM)
_TICKET_KEYWORDS = [
    "tiket", "ticket",
    "close", "tutup", "solve", "selesaikan", "resolve", "selesai",
    "reopen", "buka kembali", "buka lagi",
    "status", "progress", "note", "catatan", "label", "tag",
    "severity", "prioritas", "assign", "tetapkan",
    "ubah", "ganti", "update",
    # Fix #146: typo umum ("asign" → assign) — tanpa ini intent jatuh ke insiden
    "asign", "asignee", "assiign",
]

# Pertanyaan tentang MEMBER yang bisa di-assign — bukan perintah assign (Fix #146)
_MEMBER_QUERY_KEYWORDS = (
    "who can i assign", "siapa yang bisa", "who can assign", "who is available",
    "who can i", "siapa saja", "daftar member", "list members", "available members",
)

VALID_STATUS = {"open", "in_progress", "needs_review", "resolved", "closed"}
VALID_SEVERITY = {"critical", "high", "medium", "low"}

# Tanda pertanyaan TENTANG tiket (bukan aksi) → tampilkan ringkasan, bukan parse aksi.
QUESTION_KEYWORDS = (
    "apa yang", "kenapa", "mengapa", "bagaimana", "jelaskan", "ceritakan",
    "ringkas", "ringkasan", "informasi", "status tiket", "detail tiket",
    "kondisi", "tolong jelaskan", "bantu jelaskan",
    # chip "check ticket detail" (Fix #139) — kirim dari chat tiket, harus route ke summary
    "check tiket", "check ticket", "cek tiket", "periksa tiket",
    "explain this ticket", "explain the ticket", "what's happening", "what is happening",
    "check this ticket", "what happened",
)


def is_ticket_question(intent: str) -> bool:
    """True bila intent adalah PERTANYAAN tentang tiket (→ ringkasan), bukan aksi."""
    low = _clean_intent(intent).lower()
    return any(kw in low for kw in QUESTION_KEYWORDS)


def is_member_query(intent: str) -> bool:
    """True bila user bertanya siapa yang bisa di-assign (bukan perintah assign).
    Fix #146: "who can i assign this ticket?" sebelumnya di-parse sebagai aksi assign
    dgn nama member → error 'member not found'."""
    low = _clean_intent(intent).lower()
    return any(kw in low for kw in _MEMBER_QUERY_KEYWORDS)


def _clean_intent(intent: str) -> str:
    """Buang prefix FE `[context: ...]` (robust terhadap kurung bersarang)."""
    text = intent or ""
    if not text.lstrip().startswith("[context:"):
        return text
    depth = 0
    for i, ch in enumerate(text):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[i + 1:].lstrip()
    return text


def is_ticket_intent(intent: str, state: dict) -> bool:
    """Gate murah: intent beraroma aksi tiket DAN ada konteks tiket terbuka.

    Tanpa `ticket_context` (chat global) → selalu False (global scope = next).
    Mencegah intent analisis normal ("error pada order-service") kena-hijack.
    """
    if not state.get("ticket_context"):
        return False
    low = _clean_intent(intent).lower()
    return any(kw in low for kw in _TICKET_KEYWORDS)


async def parse_ticket_intent(
    intent: str,
    ticket: Dict[str, Any],
    workspace_members: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """LLM parse intent bebas → {action, params}. Return None bila gagal / tak valid.

    Hanya aksi dalam ACTION_WHITELIST yang diterima. Enum status/severity divalidasi
    ulang di sini + di store. Dipanggil HANYA oleh ticket_agent.
    """
    if not intent:
        return None
    intent = _clean_intent(intent)
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from services.llm_factory import get_chat_llm
        from services.prompt_loader import render as render_prompt
        import asyncio

        member_lines = "\n".join(
            f"- {m.get('name') or '?'} <{m.get('email') or '?'}> (id={m.get('userId')})"
            for m in workspace_members
        ) or "- (no member)"

        assignees = [a.get("name") or a.get("email") for a in ticket.get("assigneesDetail") or []] \
            if isinstance(ticket.get("assigneesDetail"), list) else "n/a"

        prompt = render_prompt(
            "ticket_parse",
            ticket_number=ticket.get("ticketNumber"),
            ticket_status=ticket.get("status"),
            ticket_severity=ticket.get("severity"),
            ticket_tags=ticket.get("tags") or [],
            ticket_assignees=assignees,
            member_list=member_lines,
            intent=intent,
        )

        llm = get_chat_llm(temperature=0.1)
        # Model (mis. mimo-v2.5 via opencode) bisa lambat (5-10s) — timeout longgar
        # agar parse tidak ke-potong jadi fallback "tidak dapat memahami".
        resp = await asyncio.wait_for(
            llm.ainvoke([
                SystemMessage(content="You are a ticket action classifier. Reply with JSON only."),
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

        action = (result.get("action") or "").strip().lower()
        if action not in ACTION_WHITELIST:
            logger.info(f"[TicketIntent] aksi tak dikenal: {action!r}")
            return None
        params = result.get("params") or {}

        # validasi enum
        if action == "change_status" and params.get("status") not in VALID_STATUS:
            return None
        if action == "set_severity" and params.get("severity") not in VALID_SEVERITY:
            return None
        if action == "assign":
            names = params.get("assignees") or []
            if not isinstance(names, list) or not names:
                return None
        if action == "add_label":
            labels = params.get("labels")
            if isinstance(labels, str):
                labels = [labels]
            if not isinstance(labels, list) or not labels:
                return None
            params["labels"] = [str(l).strip() for l in labels if str(l).strip()]
        if action == "add_progress" and not str(params.get("note") or "").strip():
            return None

        logger.info(f"[TicketIntent] parsed action={action} params={params}")
        return {"action": action, "params": params}

    except asyncio.TimeoutError:
        logger.warning("[TicketIntent] LLM timeout")
        return None
    except Exception as e:
        logger.warning(f"[TicketIntent] parse failed: {e}")
        return None
