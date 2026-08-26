import re
import logging
from typing import Optional, List

from state.schema import AgentState
from services.mongodb_client import DBConnectionError
from services.span_log_loader import (
    fetch_spans_by_trace_id,
    fetch_http_logs_by_trace_id,
    fetch_recent_error_spans,
    format_span_summary,
    format_recent_errors_summary,
)

logger = logging.getLogger(__name__)

# traceId OTel: 16-hex (8 byte) atau 32-hex (16 byte). W3C traceparent juga 32-hex.
TRACE_ID_RE = re.compile(r"\b([0-9a-fA-F]{16}|[0-9a-fA-F]{32})\b")

# Keyword intent "error terakhir di span" → query isError=true terbaru (tanpa traceId).
RECENT_ERROR_KEYWORDS = [
    "error terakhir di span", "error terakhir span", "error span",
    "span error", "cek error span", "error terakhir di span agent",
    "error log span", "last error span", "recent error span",
]

CENTRAL_LOG_KEYWORDS = [
    "central log", "centrall log", "centrallog", "centralog",
    "bucketlog", "span_logs", "span logs", "app_logs",
]


def is_recent_error_request(intent: str) -> bool:
    """Deteksi permintaan daftar error span terbaru (tanpa traceId spesifik)."""
    if not intent:
        return False
    return any(kw in intent.lower() for kw in RECENT_ERROR_KEYWORDS)


def is_central_log_request(intent: str) -> bool:
    """Deteksi permintaan yang eksplisit menyebut central log (termasuk typo centrall)."""
    if not intent:
        return False
    lower = intent.lower()
    return any(kw in lower for kw in CENTRAL_LOG_KEYWORDS)


async def _known_service_ids() -> list[str]:
    """
    Kandidat service dinamis (Fix #40 — tanpa hard-code brand):
    settings map ∪ docs auto-discovery ∪ library workspace.
    """
    ids: list[str] = []
    try:
        from services.doc_loader import list_all_services
        ids.extend((await list_all_services()).keys())
    except Exception:
        pass
    try:
        from services.service_store import all_service_ids
        ids.extend(await all_service_ids())
    except Exception:
        pass
    # unik, case-insensitive, urut terpanjang dulu agar match spesifik menang
    seen: set[str] = set()
    out: list[str] = []
    for sid in sorted(set(i.lower() for i in ids if i), key=len, reverse=True):
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _match_service_in_intent(intent_lower: str, candidates: list[str]) -> Optional[str]:
    """Cocokkan nama service yang disebut di intent — normalisasi dua arah
    underscore/dash/tanpa-pemisah agar varian apa pun tetap match."""
    for cand in candidates:
        variants = {
            cand,
            cand.replace("_", "-"),
            cand.replace("-", "_"),
            cand.replace("-", "").replace("_", ""),
        }
        if any(v in intent_lower for v in variants if v):
            return cand
    return None


def extract_trace_id(text: str) -> Optional[str]:
    """Ekstrak traceId dari teks intent. Kembalikan None bila tidak ada."""
    if not text:
        return None
    m = TRACE_ID_RE.search(text)
    return m.group(1) if m else None


def _pick_trace_id(state: AgentState) -> Optional[str]:
    """Prioritas traceId: preset (tombol Cek Detail) > state.trace_id > regex intent."""
    preset = state.get("preset_trace_ids") or []
    if preset:
        return str(preset[0])
    if state.get("trace_id"):
        return str(state["trace_id"])
    return extract_trace_id(state.get("intent", ""))


async def span_agent(state: AgentState) -> dict:
    """
    Query central log DB (span_logs + http_logs):
    - dengan traceId → detail satu trace (span + http_logs).
    - tanpa traceId + intent "error terakhir di span" → daftar span error terbaru.
    Sumber kebenaran centralized OTel logging (observplan.md).
    Konfigurasi: stack kind="otel" (DB, per-workspace) → fallback .env legacy.
    Exception safe — tidak pernah throw error.
    """
    from services.observability_store import get_central_log_config_for_state
    agents_visited = ["span_agent"]

    log_cfg = await get_central_log_config_for_state(dict(state))
    if not log_cfg:
        return {
            "span_summary": (
                "Central log is not configured for this workspace. "
                "Register a Central Log (OTel) stack in Workspace Settings → Stacks."
            ),
            "span_available": False,
            "span_mode": True,
            "trace_id": None,
            "next_agent": "telegram_agent",
            "agents_visited": agents_visited,
        }
    logger.info(
        f"SpanAgent central log source='{log_cfg['source']}' db='{log_cfg['db']}'"
    )

    intent = state.get("intent", "")
    trace_id = _pick_trace_id(state)

    # Mode central log: "data terakhir di centrall log ... <service> ada error"
    # → query isError=true terbaru dengan filter service
    if not trace_id and is_central_log_request(intent):
        svc_filter = state.get("service_name") or ""
        # Fix #40: fallback dinamis — kandidat dari settings/docs/library, tanpa hard-code brand
        if not svc_filter:
            lower_intent = intent.lower()
            candidates = await _known_service_ids()
            matched = _match_service_in_intent(lower_intent, candidates)
            if matched:
                svc_filter = matched
        logger.info(f"SpanAgent mode central-log: service='{svc_filter or 'ALL'}' isError=true terbaru.")
        try:
            spans = await fetch_recent_error_spans(limit=20, service=svc_filter or None, log_cfg=log_cfg)
        except DBConnectionError as e:
            logger.error(f"SpanAgent connection failed (recent errors): {e}")
            return {
                "span_data": None,
                "span_summary": (
                    f"⚠️ Gagal koneksi ke app_logs_db saat ambil error span terbaru: {e}.\n"
                    f"Data tidak tersedia saat ini."
                ),
                "span_available": False,
                "span_mode": True,
                "trace_id": None,
                "next_agent": "telegram_agent",
                "agents_visited": agents_visited,
            }
        except Exception as e:
            logger.error(f"SpanAgent query failed (recent errors): {e}")
            return {
                "span_data": None,
                "span_summary": f"Span query error: {str(e)}",
                "span_available": False,
                "span_mode": True,
                "trace_id": None,
                "next_agent": "telegram_agent",
                "agents_visited": agents_visited,
            }

        summary = format_recent_errors_summary(spans)
        return {
            "span_data": {"spans": spans, "http_logs": []},
            "span_summary": summary,
            "span_available": bool(spans),
            "span_mode": True,
            "trace_id": None,
            "raw_documents": spans,
            "next_agent": "telegram_agent",
            "agents_visited": agents_visited,
        }

    # Mode daftar error terakhir (tanpa traceId): "cek error terakhir di span"
    if not trace_id and is_recent_error_request(intent):
        logger.info("SpanAgent mode recent-error: query isError=true terbaru.")
        try:
            spans = await fetch_recent_error_spans(limit=20, log_cfg=log_cfg)
        except DBConnectionError as e:
            logger.error(f"SpanAgent connection failed (recent errors): {e}")
            return {
                "span_data": None,
                "span_summary": (
                    f"⚠️ Gagal koneksi ke app_logs_db saat ambil error span terbaru: {e}.\n"
                    f"Data tidak tersedia saat ini."
                ),
                "span_available": False,
                "span_mode": True,
                "trace_id": None,
                "next_agent": "telegram_agent",
                "agents_visited": agents_visited,
            }
        except Exception as e:
            logger.error(f"SpanAgent query failed (recent errors): {e}")
            return {
                "span_data": None,
                "span_summary": f"Span query error: {str(e)}",
                "span_available": False,
                "span_mode": True,
                "trace_id": None,
                "next_agent": "telegram_agent",
                "agents_visited": agents_visited,
            }

        summary = format_recent_errors_summary(spans)
        return {
            "span_data": {"spans": spans, "http_logs": []},
            "span_summary": summary,
            "span_available": bool(spans),
            "span_mode": True,
            "trace_id": None,
            "raw_documents": spans,
            "next_agent": "telegram_agent",
            "agents_visited": agents_visited,
        }

    if not trace_id:
        logger.warning("SpanAgent: tidak ada traceId (preset/state/intent).")
        return {
            "span_summary": (
                "Tidak ditemukan traceId pada permintaan ini. "
                "Contoh: 'detail trace 4bf92f3577b34da6a3ce929d0e0e4736' atau "
                "'cek error terakhir di span'."
            ),
            "span_available": False,
            "span_mode": True,
            "trace_id": None,
            "next_agent": "telegram_agent",
            "agents_visited": agents_visited,
        }

    logger.info(f"SpanAgent querying app_logs_db for traceId='{trace_id}'")

    try:
        spans = await fetch_spans_by_trace_id(trace_id, limit=50, log_cfg=log_cfg)
        http_logs = await fetch_http_logs_by_trace_id(trace_id, limit=10, log_cfg=log_cfg)
    except DBConnectionError as e:
        logger.error(f"SpanAgent connection failed for '{trace_id}': {e}")
        return {
            "span_data": None,
            "span_summary": (
                f"⚠️ Gagal koneksi ke app_logs_db saat lookup traceId '{trace_id}': {e}.\n"
                f"Data trace tidak tersedia saat ini."
            ),
            "span_available": False,
            "span_mode": True,
            "trace_id": trace_id,
            "next_agent": "telegram_agent",
            "agents_visited": agents_visited,
        }
    except Exception as e:
        logger.error(f"SpanAgent query failed for '{trace_id}': {e}")
        return {
            "span_data": None,
            "span_summary": f"Span query error: {str(e)}",
            "span_available": False,
            "span_mode": True,
            "trace_id": trace_id,
            "next_agent": "telegram_agent",
            "agents_visited": agents_visited,
        }

    summary = format_span_summary(trace_id, spans, http_logs)
    # Infer dominant service untuk grounding docs (telegram will load build_agent_context)
    inferred_service = ""
    if spans:
        from collections import Counter
        svc_counts = Counter(
            (s.get("service") or "").lower().replace("-", "_") for s in spans if isinstance(s, dict) and s.get("service")
        )
        if svc_counts:
            most_common_norm = svc_counts.most_common(1)[0][0]
            # map normalized -> original service id via span values
            for s in spans:
                svc_raw = s.get("service") or ""
                if svc_raw.lower().replace("-", "_") == most_common_norm:
                    inferred_service = svc_raw
                    # normalize to docs id format (underscore)
                    inferred_service = inferred_service.lower().replace("-", "_")
                    break
    # service_name dari supervisor mungkin kosong untuk traceId-only intent
    final_service = state.get("service_name") or inferred_service
    return {
        "span_data": {"spans": spans, "http_logs": http_logs},
        "span_summary": summary,
        "span_available": bool(spans),
        "span_mode": True,
        "trace_id": trace_id,
        "raw_documents": spans,
        "service_name": final_service,
        "next_agent": "telegram_agent",
        "agents_visited": agents_visited,
    }