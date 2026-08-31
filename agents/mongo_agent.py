import asyncio
import logging
from state.schema import AgentState
from services.db_loader import fetch_logs_for_service
from services.mongodb_client import DBConnectionError
from services.log_query import (
    resolve_error_query,
    resolve_sort_field,
    apply_time_window_to_query,
    detect_schema,
)
from config.settings import settings

logger = logging.getLogger(__name__)

# Query default fallback: ambil dokumen/row dengan level error/critical
DEFAULT_QUERY = {
    "level": {"$in": ["error", "critical", "ERROR", "CRITICAL"]},
}


def _build_mongo_summary(service_name: str, collection_name: str, docs: list) -> str:
    """Format ringkasan log database untuk LLM (<500 token, tanpa LLM call)."""
    window = settings.log_time_window_hours
    window_note = f" (window {window} jam terakhir)" if window and window > 0 else ""

    if not docs:
        return (
            f"=== MONGO LOGS SUMMARY: {service_name} ===\n"
            f"Target collection: {collection_name}\n"
            f"Status: Tidak ditemukan log error/critical terbaru di database{window_note}."
        )

    summary_lines = [
        f"=== MONGO LOGS SUMMARY: {service_name} ===",
        f"Target collection: {collection_name}",
        f"Total log error terdeteksi{window_note}: {len(docs)} dokumen",
    ]

    trace_ids = []
    messages = []

    for d in docs:
        if isinstance(d, dict):
            tid = d.get("trace_id") or d.get("traceId") or d.get("trace_ID")
            if tid and str(tid) not in trace_ids:
                trace_ids.append(str(tid))

            msg = d.get("message") or d.get("error") or d.get("msg") or str(d)
            if isinstance(msg, str):
                msg = msg.strip().replace("\n", " ")
                if len(msg) > 150:
                    msg = msg[:147] + "..."
            if msg and msg not in messages:
                messages.append(msg)

    latest_ts = "Unknown"
    if docs and isinstance(docs[0], dict):
        latest_ts = docs[0].get("timestamp") or docs[0].get("createdAt") or docs[0].get("created_at") or "Unknown"

    summary_lines.append(f"Timestamp log terbaru: {latest_ts}")

    if trace_ids:
        summary_lines.append(f"Trace ID terdeteksi: {', '.join(trace_ids[:3])}")
    else:
        summary_lines.append("Trace ID: Tidak terdeteksi di log MongoDB")

    summary_lines.append("\nSampel pesan error teratas:")
    for idx, m in enumerate(messages[:3], 1):
        summary_lines.append(f"  {idx}. {m}")

    return "\n".join(summary_lines)


async def mongo_agent(state: AgentState) -> dict:
    """
    Query database (MongoDB atau MySQL) berdasarkan service_name & collection_name yang resolved.
    """
    service_name = state.get("service_name", "")
    collection_name = state.get("collection_name", "")
    agents_visited = ["mongo_agent"]

    if not service_name and not collection_name:
        return {
            "error": "service_name / collection_name tidak ditemukan di state",
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    logger.info(f"Database Agent querying logs for service='{service_name}', target='{collection_name}'")

    # Fix #43: resolusi chain (JSON→registry→library), bukan settings langsung
    from services.db_loader import resolve_db_config
    db_config, _src = await resolve_db_config(service_name, state.get("workspace_id"))
    db_config = db_config or {}  # Fix #49: service tanpa DB config → default (jangan crash)
    collection = (
        db_config.get("collection")
        or state.get("collection_name")
        or f"logs_{service_name}"
    )

    # Fix #49: service tanpa konfigurasi DB log (infra seperti kube-state-metrics, atau
    # service belum di-set koneksi) → SKIP query, degrade jelas, lanjut ke observability.
    # Konsisten Fix #43: jangan diam-diam query DB default yang salah target.
    if not (db_config.get("uri") and db_config.get("db")):
        logger.warning(
            f"[{service_name}] Tidak ada konfigurasi DB log — degradasi ke observability"
        )
        return {
            "raw_documents": [],
            "query_used": {},
            "mongo_summary": (
                f"=== MONGO LOGS SUMMARY: {service_name} ===\n"
                f"Status: Service ini TIDAK punya konfigurasi database log "
                f"(kemungkinan infra/komponen K8s, bukan service transaksional). "
                f"Analisis mengandalkan observability (metrics/trace/alert)."
            ),
            "mongo_available": False,
            "next_agent": "response_agent",
            "agents_visited": agents_visited,
        }

    try:
        query_used = await resolve_error_query(service_name, db_config, collection)
        sort_field = await resolve_sort_field(db_config, collection)
        # Time-window konsisten dengan db_loader: hanya data LOG_TIME_WINDOW_HOURS jam terakhir.
        ts_type = "unknown"
        if settings.log_time_window_hours > 0:
            uri = db_config.get("uri") or settings.mongodb_uri
            db_name = db_config.get("db") or settings.mongodb_db
            try:
                schema = await detect_schema(uri, db_name, collection)
                ts_type = schema.get("ts_value_type", "unknown")
            except Exception as e:
                logger.error(f"[{service_name}] Gagal deteksi tipe timestamp: {e}")
        query_used = await apply_time_window_to_query(
            query_used,
            sort_field,
            settings.log_time_window_hours,
            ts_type,
        )
        docs = await fetch_logs_for_service(
            service_name=service_name,
            target_name=collection_name,
            query=query_used,
            limit=20,
            workspace_id=state.get("workspace_id"),
        )
    except DBConnectionError as e:
        logger.error(f"Database connection failed: {e}")
        return {
            "raw_documents": [],
            "query_used": {},
            "mongo_summary": (
                f"⚠️ Gagal koneksi ke database untuk service '{service_name}': {e}.\n"
                f"Data log dari DB tidak tersedia saat ini."
            ),
            "mongo_available": False,
            "next_agent": "response_agent",
            "agents_visited": agents_visited,
        }
    except Exception as e:
        logger.error(f"Database query failed: {e}")
        return {
            "error": f"Database query error: {str(e)}",
            "mongo_summary": f"Database query error: {str(e)}",
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    mongo_summary = _build_mongo_summary(service_name, collection_name, docs)

    if not docs:
        logger.info("No documents/rows found in database")
        return {
            "raw_documents": [],
            "query_used": query_used,
            "mongo_summary": mongo_summary,
            "next_agent": "response_agent",
            "agents_visited": agents_visited,
        }

    logger.info(f"Database Agent fetched {len(docs)} documents/rows")
    return {
        "raw_documents": docs,
        "query_used": query_used,
        "mongo_summary": mongo_summary,
        "next_agent": "response_agent",
        "agents_visited": agents_visited,
    }


