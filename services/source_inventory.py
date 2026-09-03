"""
Source Inventory — Source Registry aware chat lane (Fix #208, plan SOURCE-CHAT-LANE.md).

Engine chat sebelumnya TIDAK paham Sources: pertanyaan "sumber apa saja yang mengirim
signal" jatuh ke `fuzzy_suggest` → insiden service acak. Modul ini:
- `is_source_query(intent)` — deteksi intent source (deterministik, tanpa LLM)
- `extract_source_label(intent, known_labels)` — parse label spesifik
- `build_source_inventory(workspace_id, label, locale)` — baca `source_registry` → render markdown bilingual

Guard penting: intent insiden ("error pada X dari sentry") TIDAK boleh di-hijack —
tetap ke lane insiden. Jawaban deterministic — TIDAK butuh LLM.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# Kata konteks "source/sumber" (butuh ≥1) + kata tanya (butuh ≥1)
_SOURCE_WORDS = (
    "source", "sumber", "pengirim", "penyedia", "integrasi", "integrations",
    "signal", "signals", "kirim signal", "mengirim signal", "dari mana",
)
_QUERY_WORDS = (
    "apa", "berapa", "list", "daftar", "tampilkan", "lihat", "kirim",
    "dikirim", "diterima", "masuk", "aktif", "status", "ada", "how many",
    "what", "which", "send", "sends", "sent", "receive", "receives",
    "menerima", "terima",
)
# Kata insiden — bila ada + ada service match → BUKAN source query (lane insiden menang)
_INCIDENT_WORDS = (
    "error", "gagal", "crash", "timeout", "500", "gangguan", "down",
    "investigasi", "analisis error", "cek error",
)

# Preposisi utk extract label spesifik
_LABEL_PATTERNS = (
    r"\bfrom\s+([a-z0-9_\-]+)",
    r"\bdari\s+([a-z0-9_\-]+)",
    r"\boleh\s+([a-z0-9_\-]+)",
    r"\bsource\s+([a-z0-9_\-]+)",
    r"\bsumber\s+([a-z0-9_\-]+)",
    r"\bdikirim\s+([a-z0-9_\-]+)",
    r"\boleh\s+([a-z0-9_\-]+)\s+kirim",
    r"^([a-z0-9_\-]+)\s+kirim",
)


def _has_any(text: str, words) -> bool:
    low = " " + text.lower() + " "
    for w in words:
        if (" " + w + " ") in low:
            return True
    return False


def _is_incident(intent: str, matched_service: Optional[str]) -> bool:
    """Bila intent mengandung kata insiden DAN ada service match → incident lane,
    bukan source query. ("error pada X dari sentry" = insiden.)"""
    if not matched_service:
        return False
    return _has_any(intent, _INCIDENT_WORDS)


def is_source_query(intent: str, matched_service: Optional[str] = None) -> bool:
    """True bila intent bertanya tentang source/sumber pengirim signal (workspace-level).

    Aturan:
    - (kata source ATAU kata label) AND (kata tanya) → source query
    - GUARD insiden: incident words + matched_service → False (lane insiden)
    - "source code ..." tanpa kata tanya → False
    """
    low = (intent or "").strip()
    if not low:
        return False
    if _is_incident(low, matched_service):
        return False
    # anti-kolisi: frasa teknis "source code"/"source data" tanpa kata tanya
    if "source code" in low or "source data" in low:
        return False
    has_source_word = _has_any(low, _SOURCE_WORDS)
    has_query_word = _has_any(low, _QUERY_WORDS)
    if "dari mana" in low or "where from" in low or "where does" in low:
        return True  # frasa "dari mana" sendiri = query source
    if has_source_word and has_query_word:
        return True
    # pola label langsung: "berapa alert yang dikirim sentry?" (tanpa kata source/sumber)
    if has_query_word and _extract_label_pattern(low):
        return True
    return False


_QUERY_STOPWORDS = {
    "apa", "berapa", "list", "daftar", "semua", "all", "saja", "what",
    "which", "how", "many", "the", "yang", "di", "ke", "dari", "ini",
}


def _extract_label_pattern(intent: str) -> Optional[str]:
    low = (intent or "").lower()
    for pat in _LABEL_PATTERNS:
        m = re.search(pat, low)
        if m:
            label = m.group(1)
            if label not in _QUERY_STOPWORDS:
                return label
    return None


def extract_source_label(
    intent: str, known_labels: Optional[List[str]] = None
) -> Optional[str]:
    """Resolve label source spesifik dari intent.

    Prioritas: (1) cocokkan label registry yang sudah dikenal (case-insensitive,
    substring dengan batas kata); (2) regex pola "dari/source/sumber/dikirim <label>".
    Return None bila tidak ada label spesifik (→ tampilkan semua source).
    """
    low = (intent or "").lower()
    if not low:
        return None
    # 1. label registry dikenal → paling andal
    if known_labels:
        for label in known_labels:
            if label and (" " + label.lower() + " ") in (" " + low + " "):
                return label
    # 2. pola regex
    return _extract_label_pattern(low)


def _fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        return value.strftime("%d %b %H:%M")
    except Exception:
        return str(value)[:16]


_SOURCE_TEXTS = {
    "en": {
        "header": "📡 *Sources* — external tools that send signals to Popov (deploy events, error alerts)",
        "row": "• `{label}` · {type} · {count} signal · last {last} · {status}",
        "none": "No sources yet — sources appear automatically once an external tool sends a signal "
                "(POST /api/pub/v1/deploy-event or /api/pub/v1/ingest/alert).",
        "not_found": "No source named `{label}` found in this workspace.",
        "no_workspace": "⚠️ Workspace context is required to list sources.",
        "load_failed": "⚠️ Failed to load sources.",
        "active": "Active",
        "inactive": "Inactive",
        "specific_header": "📡 Source `{label}`",
        "count_line": "• Total signals: **{count}** · last seen {last} · {status}",
    },
    "id": {
        "header": "📡 *Sources* — tool eksternal yang mengirim signal ke Popov (deploy event, error alert)",
        "row": "• `{label}` · {type} · {count} signal · terakhir {last} · {status}",
        "none": "Belum ada source — source muncul otomatis setelah tool eksternal mengirim signal "
                "(POST /api/pub/v1/deploy-event atau /api/pub/v1/ingest/alert).",
        "not_found": "Tidak ada source `{label}` di workspace ini.",
        "no_workspace": "⚠️ Konteks workspace diperlukan untuk melihat sources.",
        "load_failed": "⚠️ Gagal memuat sources.",
        "active": "Aktif",
        "inactive": "Nonaktif",
        "specific_header": "📡 Source `{label}`",
        "count_line": "• Total signal: **{count}** · terakhir {last} · {status}",
    },
}


async def build_source_inventory(
    workspace_id: Optional[str],
    source_label: Optional[str] = None,
    locale: str = "id",
) -> str:
    """Baca source_registry → render daftar/ringkasan source (deterministik, tanpa LLM).
    Semua teks user-facing bilingual via dict (en/id) — bukan if/else bahasa."""
    t = _SOURCE_TEXTS.get(locale, _SOURCE_TEXTS["en"])
    if not workspace_id:
        # Telegram legacy tanpa konteks ws → tidak bisa resolve
        return t["header"] + "\n" + t["no_workspace"]

    from services.source_registry_store import list_sources
    try:
        sources = await list_sources(workspace_id)
    except Exception as e:
        logger.warning(f"[SourceInventory] list_sources failed: {e}")
        return t["header"] + "\n" + t["load_failed"]

    if not sources:
        return t["header"] + "\n" + t["none"]

    # label spesifik?
    if source_label:
        match = next((s for s in sources if s["source_label"].lower() == source_label.lower()), None)
        if not match:
            return t["header"] + "\n" + t["not_found"].format(label=source_label)
        status = t["active"] if match["enabled"] else t["inactive"]
        lines = [
            t["specific_header"].format(label=match["source_label"]),
            t["count_line"].format(
                count=match["signal_count"], last=_fmt_dt(match["last_seen_at"]), status=status
            ),
        ]
        return "\n".join(lines)

    lines = [t["header"]]
    for s in sources:
        status = t["active"] if s["enabled"] else t["inactive"]
        lines.append(t["row"].format(
            label=s["source_label"] or "—",
            type=s["source_type"],
            count=s["signal_count"],
            last=_fmt_dt(s["last_seen_at"]),
            status=status,
        ))
    return "\n".join(lines)