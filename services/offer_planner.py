"""
Offer Planner — membangun & mengklasifikasi tawaran aksi lanjutan.

Tahap 1 (tiket, deterministik): setelah aksi tiket → tawarkan aksi lanjutan paling relevan.
Tahap 2 (investigate + naturalize LLM): setelah laporan insiden → tawarkan "cek service A";
   teks pertanyaan bisa dinaturalisasi LLM (fallback template bila LLM gagal).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Klasifikasi jawaban ya/tidak — paham bahasa alami (kata pertama + frasa 2-kata).
_YES_WORDS = {"ya", "iya", "y", "ok", "oke", "okey", "boleh", "siap", "yes", "gas", "lanjut", "betul", "setuju", "bisa", "silakan", "silahkan", "ayok", "mari"}
_NO_WORDS = {"tidak", "nggak", "ngga", "ga", "gak", "no", "jangan", "skip", "cancel", "batal", "engga", "nggausah", "nggakusah", "nggakperlu", "tidakperlu", "tidakusah"}
_YES_PHRASES = {"ya lanjut", "iya lanjut", "ya silakan", "iya silakan", "ok lanjut", "oke lanjut", "ayo lanjut", "boleh lanjut"}
_NO_PHRASES = {"tidak usah", "tidak perlu", "nggak usah", "nggak perlu", "ngga usah", "ga usah", "gak usah", "nggak dulu", "tidak dulu", "jangan dulu", "gak perlu"}


def _first_word(text: str) -> str:
    return (text or "").strip().strip(".,!?;:").lower().split()[0] if (text or "").strip() else ""


def classify_answer(text: str) -> Optional[str]:
    """Return 'yes' | 'no' | None. Paham bahasa alami ('iya lanjut', 'nggak usah', dll)."""
    low = (text or "").strip().lower()
    if not low:
        return None
    tokens = [w.strip(".,!?;:'\"()") for w in low.split()]
    tokens = [w for w in tokens if w]
    if not tokens:
        return None
    bigram = " ".join(tokens[:2])
    if bigram in _NO_PHRASES or tokens[0] in _NO_WORDS:
        return "no"
    if bigram in _YES_PHRASES or tokens[0] in _YES_WORDS:
        return "yes"
    return None


def _display(project: Dict[str, Any], ticket: Dict[str, Any]) -> str:
    return f"{project.get('key', 'TKT')}-{ticket.get('ticketNumber')}"


def build_ticket_offer(action_executed: str, ticket: Dict[str, Any], project: Dict[str, Any]) -> Optional[dict]:
    """Tawaran tunggal paling relevan setelah aksi tiket. Return None bila tak ada.
    - tiket resolved/closed → tawarkan reopen (tanpa param).
    - selain itu → tawarkan tambah catatan progress (butuh 1 param: note)."""
    display = _display(project, ticket)
    status = ticket.get("status", "open")
    ticket_id = str(ticket.get("_id"))

    if status in ("resolved", "closed"):
        return {
            "type": "ticket_action",
            "params": {"action": "reopen", "ticket_id": ticket_id},
            "needs_param": None,
            "question": f"Apakah kamu ingin saya buka kembali tiket {display}?",
        }
    # Jangan tawarkan add_progress lagi bila aksi barusan justru add_progress
    # (hindari pertanyaan dobel/membingungkan setelah user baru menambah catatan).
    if action_executed == "add_progress":
        return None
    return {
        "type": "ticket_action",
        "params": {"action": "add_progress", "ticket_id": ticket_id},
        "needs_param": "note",
        "question": f"Apakah kamu ingin saya tambahkan catatan pada Progress Log tiket {display}?",
    }


def build_investigate_offer(service_name: str, project_key: str = "") -> Optional[dict]:
    """Tawaran investigasi lanjutan setelah laporan insiden (web chat)."""
    svc = (service_name or "").strip()
    if not svc:
        return None
    return {
        "type": "investigate",
        "params": {"service_name": svc, "intent": f"cek error pada {svc}"},
        "needs_param": None,
        "question": f"Apakah kamu ingin saya mengecek service `{svc}` lebih dalam?",
    }


def render_offer_question(offer: dict) -> str:
    """Kalimat penutup tawaran (web chat) — cukup pertanyaannya, balasan natural sudah dipahami."""
    return (offer.get("question") or "").strip()


def render_offer_buttons(offer: dict) -> list:
    """Tombol inline Telegram untuk tawaran (Tahap 3)."""
    oid = offer.get("offer_id")
    return [
        {"text": "✅ Ya", "callback_data": f"offer:{oid}:accept"},
        {"text": "❌ Tidak", "callback_data": f"offer:{oid}:cancel"},
    ]
