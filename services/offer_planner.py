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
# Multibahasa (Fix #194): project dipakai lintas bahasa — jangan hanya EN/ID.
_YES_WORDS = {
    # EN/ID
    "ya", "iya", "y", "ok", "oke", "okey", "boleh", "siap", "yes", "gas", "lanjut",
    "betul", "setuju", "bisa", "silakan", "silahkan", "ayok", "mari", "sure", "yep",
    "yeah", "go", "please", "pls", "tentu", "pastinya", "lanjutkan",
    # FR
    "oui", "ouais", "si",
    # ES / IT
    "sí", "si", "claro", "va bene",
    # PT
    "sim",
    # DE / NL / Nordic
    "ja", "jawol", "okay",
    # JP
    "はい", "うん", "そう",
    # ZH
    "是", "对", "好", "要", "可以",
    # KO
    "네", "응", "예",
    # RU / UK
    "да", "так",
    # AR / FA
    "نعم", "أجل", "بله",
    # TR
    "evet",
    # HI
    "हाँ",
    # TH
    "ใช่",
}
_NO_WORDS = {
    # EN/ID
    "tidak", "nggak", "ngga", "ga", "gak", "no", "jangan", "skip", "cancel", "batal",
    "engga", "nggausah", "nggakusah", "nggakperlu", "tidakperlu", "tidakusah", "nope",
    "nah", "gak usah",
    # FR
    "non",
    # ES / IT
    "no", "niente",
    # PT
    "não",
    # DE / NL / Nordic
    "nein", "nee", "nej",
    # JP
    "いいえ", "いや", "いらない",
    # ZH
    "不", "不是", "不要", "不用",
    # KO
    "아니요", "아니",
    # RU / UK
    "нет", "ні",
    # AR / FA
    "لا", "نه",
    # TR
    "hayır",
    # HI
    "नहीं",
    # TH
    "ไม่",
}
_YES_PHRASES = {"ya lanjut", "iya lanjut", "ya silakan", "iya silakan", "ok lanjut", "oke lanjut", "ayo lanjut", "boleh lanjut", "sure go ahead", "yes please", "yeah sure", "ok sure"}
_NO_PHRASES = {"tidak usah", "tidak perlu", "nggak usah", "nggak perlu", "ngga usah", "ga usah", "gak usah", "nggak dulu", "tidak dulu", "jangan dulu", "gak perlu", "no thanks", "nope not"}


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


def build_ticket_offer(action_executed: str, ticket: Dict[str, Any], project: Dict[str, Any],
                       locale: str = "id") -> Optional[dict]:
    """Tawaran tunggal paling relevan setelah aksi tiket. Return None bila tak ada.
    - tiket resolved/closed → tawarkan reopen (tanpa param).
    - selain itu → tawarkan tambah catatan progress (butuh 1 param: note).
    locale (Fix #145): pertanyaan bilingual en/id."""
    display = _display(project, ticket)
    status = ticket.get("status", "open")
    ticket_id = str(ticket.get("_id"))
    texts = _OFFER_TICKET_TEXTS.get(locale, _OFFER_TICKET_TEXTS["id"])

    if status in ("resolved", "closed"):
        return {
            "type": "ticket_action",
            "params": {"action": "reopen", "ticket_id": ticket_id},
            "needs_param": None,
            "question": texts["reopen"].format(display=display),
        }
    # Jangan tawarkan add_progress lagi bila aksi barusan justru add_progress
    # (hindari pertanyaan dobel/membingungkan setelah user baru menambah catatan).
    if action_executed == "add_progress":
        return None
    return {
        "type": "ticket_action",
        "params": {"action": "add_progress", "ticket_id": ticket_id},
        "needs_param": "note",
        "question": texts["progress"].format(display=display),
    }


# Teks tawaran tiket — bilingual (Fix #145)
_OFFER_TICKET_TEXTS = {
    "id": {
        "reopen": "Apakah kamu ingin saya buka kembali tiket {display}?",
        "progress": "Apakah kamu ingin saya tambahkan catatan pada Progress Log tiket {display}?",
    },
    "en": {
        "reopen": "Would you like me to reopen ticket {display}?",
        "progress": "Would you like me to add a note to the Progress Log of ticket {display}?",
    },
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


# ── Chat suggestions (chips follow-up) — bilingual, deterministik, DRY ────────
# Dipakai chat tiket (ticket_agent/response_agent) DAN chat project (project_agent)
# supaya bahasa & konten konsisten satu sumber.

_CHAT_SUGGESTION_TEXTS = {
    "en": {
        "investigate": "Investigate deeper the error on {svc}",
        "alert": "Check alert details on {svc}",
        "open": "Show open tickets",
        "knowledge": "What knowledge is available in this project",
        "progress": "Add a progress note",
        "reopen": "Reopen this ticket",
        "status": "What is the current status?",
        "severity": "Summarize this ticket",
    },
    "id": {
        "investigate": "Investigasi lebih dalam error pada {svc}",
        "alert": "Cek detail alert pada {svc}",
        "open": "Tampilkan tiket yang masih terbuka",
        "knowledge": "Knowledge apa saja pada project ini",
        "progress": "Tambahkan catatan progress",
        "reopen": "Buka kembali tiket ini",
        "status": "Apa status saat ini?",
        "severity": "Ringkas tiket ini",
    },
}


def chat_suggestion(key: str, locale: str = "en", **fmt: str) -> str:
    """Satu teks suggestion (bilingual). key = salah satu kunci di atas."""
    texts = _CHAT_SUGGESTION_TEXTS.get(locale, _CHAT_SUGGESTION_TEXTS["en"])
    tmpl = texts.get(key, texts["status"])
    return tmpl.format(**fmt) if fmt else tmpl


def build_chat_suggestions(
    *,
    ticket: Optional[Dict[str, Any]] = None,
    project: Optional[Dict[str, Any]] = None,
    service_name: str = "",
    root_cause: str = "unknown",
    has_open_tickets: bool = False,
    want_knowledge: bool = False,
    locale: str = "en",
    max_items: int = 3,
) -> List[str]:
    """Chips follow-up untuk chat (tiket & project) — deterministik, bilingual.

    Prioritas sesuai konteks:
    - ticket open → "What is the current status?" / "Summarize this ticket"
    - ticket resolved/closed → "Reopen this ticket" / "Add a progress note"
    - insiden (root_cause ≠ unknown, service ada) → "Investigate deeper the error on X"
    - ada tiket terbuka lain → "Show open tickets"
    - default → "What knowledge is available in this project"
    """
    out: List[str] = []

    if ticket and project:
        status = (ticket.get("status") or "").lower()
        if status in ("resolved", "closed"):
            out.append(chat_suggestion("reopen", locale))
            out.append(chat_suggestion("progress", locale))
        else:
            out.append(chat_suggestion("status", locale))
            out.append(chat_suggestion("severity", locale))

    if root_cause != "unknown" and service_name:
        out.append(chat_suggestion("investigate", locale, svc=service_name))

    if has_open_tickets:
        out.append(chat_suggestion("open", locale))

    if want_knowledge:
        out.append(chat_suggestion("knowledge", locale))

    # dedup + batas
    seen: List[str] = []
    for s in out:
        if s not in seen:
            seen.append(s)
    return seen[:max_items]


def render_offer_question(offer: dict) -> str:
    """Kalimat penutup tawaran (web chat) — cukup pertanyaannya, balasan natural sudah dipahami."""
    return (offer.get("question") or "").strip()


# ── CHATFLOW V2.1 (Tahap 2): chips kontekstual berbasis temuan ────────────────
# Berbeda dari build_chat_suggestions (generik), chips ini dihasilkan dari temuan
# aktual investigasi: deploy detection, Second Brain similarity, trace downstream,
# data_gaps. Return list[str] — KOMPATIBEL dgn pipeline meta.suggestions & FE
# (ChatSuggestions render string[]), jadi TANPA perubahan frontend.

_CONTEXTUAL_CHIP_TEXTS = {
    "id": {
        "deploy": "Cek deployment {time}",
        "deploy_intent": "cek log deployment {svc} {time}",
        "similar": "Bandingkan insiden serupa",
        "similar_intent": "tampilkan insiden serupa dengan {svc}",
        "downstream": "Cek downstream service",
        "downstream_intent": "cek koneksi downstream {svc}",
        "metrics": "Cek metrics error rate",
        "metrics_intent": "cek error rate {svc} 1 jam terakhir",
        "span": "Lihat detail span",
        "span_intent": "lihat detail span {svc}",
        "ticket": "Detail tiket",
        "ticket_intent": "tampilkan detail tiket ini",
    },
    "en": {
        "deploy": "Check deployment {time}",
        "deploy_intent": "check deployment log {svc} {time}",
        "similar": "Compare similar incidents",
        "similar_intent": "show similar incidents for {svc}",
        "downstream": "Check downstream service",
        "downstream_intent": "check downstream connection {svc}",
        "metrics": "Check error rate metrics",
        "metrics_intent": "check error rate {svc} last 1 hour",
        "span": "View span detail",
        "span_intent": "view span detail {svc}",
        "ticket": "Ticket detail",
        "ticket_intent": "show ticket details",
    },
}


def build_contextual_suggestions(state: Dict[str, Any], reply_language: str = "English") -> List[Any]:
    """Chips berbasis temuan investigasi (CHATFLOW V2.1 Tahap 2 + Gap 5).

    Fallback ke build_chat_suggestions bila tidak ada temuan spesifik.
    Return list[Union[str, dict]]:
      - str = chip generik (label → isi input saat klik, pola Fix #138/#139)
      - dict = chip investigasi {label, action, type:"investigation"} → auto-send via
        action identifier "investigate:<node>" (bypass NLU di supervisor).
    """
    lang_id = reply_language.lower() == "bahasa indonesia"
    texts = _CONTEXTUAL_CHIP_TEXTS.get("id" if lang_id else "en", _CONTEXTUAL_CHIP_TEXTS["en"])
    service = state.get("service_name", "")
    suggestions: List[str] = []

    # — Chip dari deploy detection (triage_result) —
    triage = state.get("triage_result") or {}
    if triage.get("hypothesis") == "regression_post_deploy":
        deploy_time = str(triage.get("deploy_time") or "").strip()
        suggestions.append(texts["deploy"].format(time=deploy_time).strip())
        # intent spesifik disimpan ke state terpisah? Tidak — chip label jadi intent
        # (konsisten dgn chips existing yang label = pesan). Detail tetap bisa via LLM.

    # — Chip dari Second Brain (episode serupa) —
    knowledge_ctx = (state.get("knowledge_context") or "").lower()
    if "similar episode" in knowledge_ctx or "insiden serupa" in knowledge_ctx:
        suggestions.append(texts["similar"])

    # — Chip dari trace timeout / downstream —
    trace_summary = (state.get("trace_summary") or "").lower()
    if "timeout" in trace_summary or "downstream" in trace_summary:
        suggestions.append(texts["downstream"])

    # — Chip dari data_gaps (Gap 5): structured read, semua gaps, sorted by priority, max 3 —
    data_gaps = state.get("data_gaps") or []
    gap_chips: List[Dict[str, Any]] = []
    if data_gaps:
        dict_gaps = [g for g in data_gaps if isinstance(g, dict)]
        sorted_gaps = sorted(dict_gaps, key=lambda x: x.get("priority", 99))
        for gap in sorted_gaps[:3]:
            action = (gap.get("suggested_action") or "").strip()
            node = (gap.get("node") or "").strip()
            if action and node:
                gap_chips.append({
                    "label": action,
                    "action": f"investigate:{node}",
                    "type": "investigation",
                })
        logger.info(
            f"[offer_planner] data_gaps={len(data_gaps)} gap_chips_generated={len(gap_chips)} "
            f"nodes_covered={[g.get('node') for g in sorted_gaps[:3]]} "
            f"total_suggestions={len(suggestions)}"
        )

    # — Fallback ke chips generik bila tidak ada temuan spesifik —
    if not suggestions and not gap_chips:
        return build_chat_suggestions(
            service_name=service,
            root_cause=state.get("root_cause_assessment") or "unknown",
            has_open_tickets=False,
            want_knowledge=True,
            locale=("id" if lang_id else "en"),
            max_items=3,
        )

    # — Selalu tambah chip tiket di akhir —
    suggestions.append(texts["ticket"])

    # Gabungkan: gap chips selalu di posisi pertama (primary CTA)
    all_suggestions: List[Any] = gap_chips + suggestions

    # dedup + batas (maksimal 4) — string biasa dedup, dict gap chips dipertahankan
    seen: List[str] = []
    out: List[Any] = []
    for s in all_suggestions:
        if isinstance(s, dict):
            key = s["label"]
        else:
            key = s
        if key not in seen:
            seen.append(key)
            out.append(s)
    return out[:4]


def render_offer_buttons(offer: dict) -> list:
    """Tombol inline Telegram untuk tawaran (Tahap 3)."""
    oid = offer.get("offer_id")
    return [
        {"text": "✅ Ya", "callback_data": f"offer:{oid}:accept"},
        {"text": "❌ Tidak", "callback_data": f"offer:{oid}:cancel"},
    ]
