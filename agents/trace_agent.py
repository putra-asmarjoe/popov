import logging
from typing import Dict, Any, Optional, List
from state.schema import AgentState
from config.settings import settings
from services.tempo_client import get_trace, search_traces
from services.service_name_utils import service_name_variants

logger = logging.getLogger(__name__)


def _extract_trace_id_from_documents(docs: list) -> Optional[str]:
    """Ekstrak trace_id pertama yang ditemukan di raw_documents MongoDB."""
    if not docs:
        return None
    for d in docs:
        if isinstance(d, dict):
            tid = d.get("trace_id") or d.get("traceId") or d.get("trace_ID")
            if tid:
                return str(tid)
    return None


async def _search_traces_variants(service_name: str, limit: int = 3, tempo_url_override: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search traces ke Tempo untuk semua varian nama service; gabungkan hasil unik."""
    seen = set()
    combined = []
    for variant in service_name_variants(service_name):
        traces = await search_traces(variant, limit=limit, tempo_url_override=tempo_url_override)
        for t in traces:
            tid = t.get("traceID")
            if tid and tid not in seen:
                seen.add(tid)
                combined.append(t)
        if combined:
            break
    return combined


def _format_trace_summary(service_name: str, trace_id: Optional[str], trace_data: Optional[Dict[str, Any]], traces_search: List[Dict[str, Any]]) -> str:
    if trace_data:
        spans = trace_data.get("batches", [])
        lines = [
            f"=== TRACE SUMMARY: {service_name} ===",
            f"Trace ID: {trace_id}",
            f"Tempo Status: Trace detail berhasil diambil.",
        ]

        error_spans = []
        long_spans = []

        # Parse basic spans
        for batch in spans:
            scope_spans = batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", []))
            for scope in scope_spans:
                for span in scope.get("spans", []):
                    s_name = span.get("name", "unknown")
                    status = span.get("status", {})
                    code = status.get("code") or status.get("statusCode")
                    if code in ("STATUS_CODE_ERROR", "ERROR", 2):
                        error_spans.append(s_name)

        if error_spans:
            lines.append(f"Error Spans ({len(error_spans)}): {', '.join(error_spans[:5])}")
            lines.append("Downstream Root Cause Candidate: Error terdeteksi di span tersebut.")
        else:
            lines.append("Error Spans: Tidak ada span bertanda ERROR pada trace ini.")

        return "\n".join(lines)

    if traces_search:
        lines = [
            f"=== TRACE SUMMARY: {service_name} ===",
            f"Tempo Status: {len(traces_search)} trace ditemukan via search by service.",
        ]
        for t in traces_search[:3]:
            t_id = t.get("traceID", "N/A")
            duration = t.get("durationMs") or t.get("duration", "N/A")
            lines.append(f"  - TraceID: {t_id} (Duration: {duration})")
        return "\n".join(lines)

    return f"=== TRACE SUMMARY: {service_name} ===\nTidak ada data trace yang ditemukan di Tempo untuk service ini."


async def _fetch_trace_details(trace_ids: List[str], tempo_url_override: Optional[str] = None) -> Dict[str, Any]:
    """Ambil detail beberapa trace_id (prioritas preset dari alert watchdog)."""
    for tid in trace_ids:
        trace_data = await get_trace(tid, tempo_url_override=tempo_url_override)
        if trace_data:
            return trace_data
    return None


async def trace_agent(state: AgentState) -> dict:
    """
    Query Grafana Tempo untuk trace analysis.
    Exception safe — tidak pernah throw error.
    """
    service_name = state.get("service_name", "")
    raw_docs = state.get("raw_documents", [])
    agents_visited = ["trace_agent"]

    if not service_name:
        return {
            "trace_data": None,
            "trace_summary": "Trace tidak tersedia: service_name kosong.",
            "trace_available": False,
            "trace_id": None,
            "agents_visited": agents_visited,
        }

    # Fix #45: sumber stack = DB observ_config (bukan env). Tanpa stack → degraded.
    from services.observability_store import get_observ_config_for_state
    obs_cfg = await get_observ_config_for_state(state)
    tempo_override = (obs_cfg or {}).get("tempo_url")

    if not tempo_override:
        logger.info(f"Tempo disabled (no stack configured in DB). Skipping trace analysis for '{service_name}'.")
        return {
            "trace_data": None,
            "trace_summary": "Trace tidak tersedia: belum ada stack Tempo (observability target) untuk konteks ini.",
            "trace_available": False,
            "trace_id": None,
            "agents_visited": agents_visited,
        }

    logger.info(f"TraceAgent querying Tempo for service='{service_name}' (stack={'custom' if tempo_override else 'global'})")

    try:
        preset_trace_ids = state.get("preset_trace_ids") or []
        extracted_trace_id = state.get("trace_id") or _extract_trace_id_from_documents(raw_docs)
        trace_data = None
        traces_search = []

        if preset_trace_ids:
            logger.info(f"Fetching preset trace details (Cek Detail): {preset_trace_ids}")
            trace_data = await _fetch_trace_details(preset_trace_ids, tempo_url_override=tempo_override)
            extracted_trace_id = extracted_trace_id or (preset_trace_ids[0] if preset_trace_ids else None)
        elif extracted_trace_id:
            logger.info(f"Fetching trace details for trace_id='{extracted_trace_id}'")
            trace_data = await get_trace(extracted_trace_id, tempo_url_override=tempo_override)

        if not trace_data:
            logger.info(f"Search fallback traces for service='{service_name}'")
            traces_search = await _search_traces_variants(service_name, limit=3, tempo_url_override=tempo_override)

        available = bool(trace_data or traces_search)
        summary = _format_trace_summary(service_name, extracted_trace_id, trace_data, traces_search)

        return {
            "trace_data": trace_data or {"search": traces_search},
            "trace_summary": summary,
            "trace_available": available,
            "trace_id": extracted_trace_id,
            "agents_visited": agents_visited,
        }

    except Exception as e:
        logger.error(f"TraceAgent error for '{service_name}': {e}", exc_info=True)
        return {
            "trace_data": None,
            "trace_summary": f"Trace error: {str(e)}",
            "trace_available": False,
            "trace_id": None,
            "agents_visited": agents_visited,
        }
