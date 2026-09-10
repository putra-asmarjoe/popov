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
    # chip "Summarize this ticket" / "Ringkas tiket ini" (build_chat_suggestions severity key,
    # Fix #243 follow-up): label persis chip ini adalah PERTANYAAN ringkasan — tanpa ini
    # intent jatuh ke parse_ticket_intent (LLM) yang saat model down/insufficient-credits
    # berakhir fallback "I'm focused on the ticket..." alih-alih summary tiket.
    # "summarize/summary" EN; "ringkas" ID sudah tercakup di daftar atas.
    "summarize", "summarise", "summary",
    # frasa EN umum permintaan detail/ringkasan tiket (CPRO-38: "Ticket detail" = judul
    # panel, bukan aksi — tanpa ini jatuh ke parse aksi LLM → redirect saat model down).
    # HATI-HATI: jangan tambah frasa yang bisa bentrok aksi ("this ticket" saja terlalu
    # umum — "close this ticket" adalah aksi). Hanya frasa yang tak pernah jadi aksi.
    "ticket detail", "ticket details", "details of this ticket", "detail of this ticket",
    "ticket summary", "tell me about", "what about this ticket",
    "what is this ticket", "whats this ticket", "show ticket details", "show me this ticket",
)


def is_ticket_question(intent: str) -> bool:
    """True bila intent adalah PERTANYAAN tentang tiket (→ ringkasan), bukan aksi.

    Fix #192 (multibahasa): pesan berakhiran tanda tanya (`?`/`؟`) DIJAMIN pertanyaan
    → selalu summary, TIDAK pernah dieksekusi sebagai aksi mutasi. Bahasa-agnostik —
    melindungi user bahasa non-EN/ID dari salah-parse jadi add_progress/change_status."""
    low = _clean_intent(intent).lower()
    if low.rstrip().endswith(("?", "؟")):
        return True
    return any(kw in low for kw in QUESTION_KEYWORDS)


def is_member_query(intent: str) -> bool:
    """True bila user bertanya siapa yang bisa di-assign (bukan perintah assign).
    Fix #146: "who can i assign this ticket?" sebelumnya di-parse sebagai aksi assign
    dgn nama member → error 'member not found'."""
    low = _clean_intent(intent).lower()
    return any(kw in low for kw in _MEMBER_QUERY_KEYWORDS)


# Fix #251: investigation query detection — "why is X happening?", "what is causing Y?"
# Pertanyaan ini seharusnya route ke investigasi/analysis, bukan summary tiket.
# Fix #253 (CHIP_CONTEXT_PLAN C1): HANYA frasa kausal eksplisit. Bare noun/verb
# ("investigation", "analyze", dst.) DIHAPUS — "What was the conclusion of the
# investigation?" adalah pertanyaan summary, bukan permintaan investigasi.
# Jalur "Investigate deeper..." aman: punya gate sendiri di supervisor
# (_investigate_ticket_kw) dan dicek SEBELUM tiket lane.
_INVESTIGATION_KEYWORDS = (
    # EN — kausal eksplisit
    "why is", "why does", "why did", "why are", "why was", "why were",
    "what is causing", "what causes", "what caused", "what's causing",
    "what is the root cause", "what's the root cause", "root cause",
    "what is the reason", "what's the reason", "reason for",
    "how did this happen", "how does this happen", "how did this occur",
    "what led to", "what led up to", "what triggered", "what triggered this",
    # ID — kausal eksplisit
    "kenapa", "mengapa", "apa yang menyebabkan", "apa penyebab",
    "akar masalah", "mengapa ini terjadi",
    "bagaimana ini bisa terjadi", "apa yang membuat", "apa yang memicu",
)


def is_investigation_query(intent: str) -> bool:
    """True bila intent adalah pertanyaan investigasi (root cause, analysis).

    Fix #251: pertanyaan investigasi seharusnya route ke investigasi/analysis,
    bukan summary tiket. Tanpa ini, "Why is X happening?" dijawab summary generik.
    """
    low = _clean_intent(intent).lower()
    return any(kw in low for kw in _INVESTIGATION_KEYWORDS)


# Fix #249: rule-based detect "add progress note" — pattern umum EN/ID.
# Tanpa ini, intent jatuh ke parse_ticket_intent (LLM) → gagal saat model down →
# clarify_reply → fallback "I'm focused on the ticket..." (dead-end).
_PROGRESS_NOTE_PATTERNS = (
    # EN patterns
    "add a progress note", "add progress note", "add progress",
    "add a note", "add note",
    "write a progress note", "write progress note",
    "post a progress note", "post progress note",
    "insert a progress note", "insert progress note",
    "note that",
    # ID patterns
    "tambahkan catatan progress", "tambah catatan progress", "tambah progress",
    "tambahkan catatan", "tambah catatan",
    "tulis catatan progress", "tulis catatan",
    "buat catatan progress", "buat catatan",
    "catat bahwa",
    # chip label (EN/ID)
    "add progress note", "catatan progress",
)


def _is_progress_note_command(intent: str) -> bool:
    """True bila intent adalah perintah 'add progress note' (deterministic, tanpa LLM)."""
    low = _clean_intent(intent).lower()
    return any(p in low for p in _PROGRESS_NOTE_PATTERNS)


def _extract_progress_note(intent: str) -> Optional[str]:
    """Ekstrak teks catatan dari perintah 'add progress note'.

    supported patterns:
      - "add progress note: we are checking the gateway logs"
      - "add progress note saying we are checking the gateway logs"
      - "add a progress note about scaling investigation"   (Fix #253 B2: separator about/that/regarding)
      - "note that we are investigating the error"          (Fix #253 B1: tanpa verb perintah)
      - "tambahkan catatan progress: kami sedang memeriksa log gateway"
      - "tambah catatan progress sedang investigasi"
      - "catat bahwa kami sedang memeriksa log"             (Fix #253 B1)
    """
    import re
    text = _clean_intent(intent)
    # EN pattern 1: "add/write/post/insert [a] [progress] note <sep> <text>"
    # Fix #253 B2: separator diperluas — 'about/that/regarding/says' ikut dibuang,
    # bukan tersimpan sebagai bagian note (bocor kata penghubung ke progressLog).
    m = re.search(
        r'\b(?:add|write|post|insert)\s+(?:a\s+)?(?:progress\s+)?note\s*'
        r'(?:saying|says|that|about|regarding|:|;|-|,)?\s*(.+)',
        text, re.IGNORECASE
    )
    if m and m.group(1).strip():
        return m.group(1).strip()
    # EN pattern 2 (Fix #253 B1): "note that <text>" — tanpa verb perintah.
    # Pattern list sudah memuat "note that" (Fix #252) — extract wajib ikut,
    # kalau tidak guard match lalu jatuh ke clarify (dead-end deterministik).
    m = re.search(r'\bnote\s+that\s*[:\-]?\s*(.+)', text, re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # ID pattern 1 (Fix #253 B1): "catat bahwa <text>"
    m = re.search(r'\bcatat\s+bahwa\s*[:\-]?\s*(.+)', text, re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # ID pattern 2: "tambahkan/tambah/buat/tulis catatan progress <sep> <text>"
    # Fix #253 B2: separator + bahwa/tentang.
    m = re.search(
        r'(?:tambahkan|tambah|buat|tulis)\s+catatan\s+progress\s*'
        r'(?:bahwa|tentang|:|;|-|_|,)?\s*(.+)',
        text, re.IGNORECASE
    )
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


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

    Fix #193 (multibahasa): pesan berakhiran tanda tanya (`?`/`؟`) SELALU dianggap
    pertanyaan → return None (bukan aksi), tanpa memanggil LLM. Ini pertahanan
    terakhir: apapun bahasa/loophole routing, pertanyaan tidak pernah dieksekusi
    sebagai mutasi tiket.
    """
    if not intent:
        return None
    if _clean_intent(intent).rstrip().endswith(("?", "؟")):
        logger.info("[TicketIntent] question (?) detected → not an action")
        return None
    intent = _clean_intent(intent)

    # Fix #249: rule-based "add progress note" — tanpa LLM, selalu jalan walau model down.
    # Pattern umum EN/ID sudah cukup stabil; parsing teks catatan via regex.
    if _is_progress_note_command(intent):
        note = _extract_progress_note(intent)
        if note:
            logger.info(f"[TicketIntent] rule-based add_progress (note={note[:50]}...)")
            return {"action": "add_progress", "params": {"note": note}}
        # pattern detected tapi teks kosong → tetap return None, biar clarify_reply handle
        logger.info("[TicketIntent] rule-based add_progress detected but note empty → None")

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
