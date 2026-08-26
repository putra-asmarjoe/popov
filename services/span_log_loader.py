import logging
from typing import List, Dict, Any, Optional

from services.mongodb_client import query_collection, DBConnectionError

logger = logging.getLogger(__name__)

SPAN_COLLECTION = "span_logs"
HTTP_COLLECTION = "http_logs"


def _resolve_cfg(log_cfg: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Resolve konfigurasi central log dari stack kind="otel" (log_cfg).
    Fix #107: TIDAK ada lagi fallback .env — tanpa log_cfg berarti belum
    dikonfigurasi (span_agent guard resolver lebih dulu, jadi ini safety net)."""
    c = log_cfg or {}
    uri = c.get("uri")
    db = c.get("db")
    if not uri or not db:
        raise ValueError(
            "Central log is not configured for this workspace. "
            "Register a Central Log (OTel) stack in Workspace Settings → Stacks."
        )
    return {
        "uri": uri,
        "db": db,
        "span_collection": c.get("span_collection") or SPAN_COLLECTION,
        "http_collection": c.get("http_collection") or HTTP_COLLECTION,
    }


async def fetch_spans_by_trace_id(
    trace_id: str,
    limit: int = 50,
    log_cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Ambil semua span dari central log DB untuk satu traceId (terbaru dulu)."""
    cfg = _resolve_cfg(log_cfg)
    query = {"traceId": trace_id}
    return await query_collection(
        collection_name=cfg["span_collection"],
        query=query,
        limit=limit,
        uri=cfg["uri"],
        db_name=cfg["db"],
        sort_field="timestamp",
        service_name="span_logs",
    )


async def fetch_http_logs_by_trace_id(
    trace_id: str,
    limit: int = 10,
    log_cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Ambil detail request dari central log DB http_logs untuk satu traceId."""
    cfg = _resolve_cfg(log_cfg)
    query = {"traceId": trace_id}
    return await query_collection(
        collection_name=cfg["http_collection"],
        query=query,
        limit=limit,
        uri=cfg["uri"],
        db_name=cfg["db"],
        sort_field="timestamp",
        service_name="http_logs",
    )


async def fetch_recent_error_spans(
    limit: int = 20,
    service: Optional[str] = None,
    log_cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Ambil span error (isError=true) terbaru dari central log DB.
    Jika service diisi, filter hanya untuk service tersebut (mendukung varian dash/underscore)."""
    cfg = _resolve_cfg(log_cfg)
    query: Dict[str, Any] = {"isError": True}
    if service:
        # Nama service di central log bisa dash, intent memakai underscore —
        # keduanya diterima sebagai varian filter.
        dash = service.replace("_", "-")
        underscore = service.replace("-", "_")
        variants = {dash, underscore, service}
        # case-insensitive match untuk jaga-jaga
        if len(variants) == 1:
            query["service"] = next(iter(variants))
        else:
            query["service"] = {"$in": list(variants)}
    return await query_collection(
        collection_name=cfg["span_collection"],
        query=query,
        limit=limit,
        uri=cfg["uri"],
        db_name=cfg["db"],
        sort_field="timestamp",
        service_name="span_logs",
    )


def format_recent_errors_summary(spans: List[Dict[str, Any]]) -> str:
    """
    Ringkasan span error terbaru (isError=true) dari app_logs_db untuk LLM.
    Tanpa baris Env — field env tidak valid (lihat Fix #20).
    """
    if not spans:
        return (
            "=== RECENT SPAN ERRORS ===\n"
            "Status: Tidak ditemukan span bertanda isError=true di app_logs_db."
        )

    lines = [
        "=== RECENT SPAN ERRORS (app_logs_db) ===",
        f"Total span error terdeteksi: {len(spans)}",
    ]
    for idx, s in enumerate(spans[:10], 1):
        if not isinstance(s, dict):
            continue
        tid = s.get("traceId") or "N/A"
        lines.append(
            f"{idx}. traceId={tid} | service={s.get('service')} | "
            f"{s.get('method') or ''} {s.get('route') or s.get('name') or ''} "
            f"→ {s.get('statusCode') or 'N/A'} | durasi {s.get('duration')}ms"
        )
        em = s.get("errorMessage")
        if em:
            em = str(em).strip().replace("\n", " ")
            lines.append(f"   error: {em[:200]}")
        ts = s.get("timestamp")
        if ts:
            lines.append(f"   waktu: {ts}")

    return "\n".join(lines)


def _ts(value) -> str:
    if value is None:
        return "N/A"
    return str(value)


def format_span_summary(
    trace_id: str,
    spans: List[Dict[str, Any]],
    http_logs: List[Dict[str, Any]],
) -> str:
    """
    Ringkasan trace dari app_logs_db untuk LLM (<500 token, tanpa LLM call).
    Struktur mengikuti observplan.md schema span_logs.
    """
    if not spans:
        return (
            f"=== SPAN LOGS SUMMARY: {trace_id} ===\n"
            f"Status: Tidak ditemukan data span di app_logs_db untuk traceId ini."
        )

    services = {}
    root = None
    error_spans = []
    total_duration = 0
    business = {}
    route = None
    status_code = None

    for s in spans:
        if not isinstance(s, dict):
            continue
        svc = s.get("service") or "unknown"
        services[svc] = services.get(svc, 0) + 1
        parent = s.get("parentSpanId")
        if not parent:
            root = s
        if s.get("isError"):
            error_spans.append(s)
        dur = s.get("duration")
        if isinstance(dur, (int, float)):
            total_duration += dur
        biz = s.get("business") or {}
        if biz and isinstance(biz, dict):
            business.update(biz)
        if not route:
            route = s.get("route") or s.get("name")
        if status_code is None:
            status_code = s.get("statusCode")

    lines = [
        f"=== SPAN LOGS SUMMARY: {trace_id} ===",
        f"Total span: {len(spans)}",
        f"Service terlibat: {', '.join(f'{k} ({v} span)' for k, v in services.items())}",
        f"Total duration: {total_duration} ms",
        f"StatusCode: {status_code or 'N/A'} · Route: {route or 'N/A'}",
    ]

    if error_spans:
        lines.append(f"Error Spans ({len(error_spans)}):")
        for es in error_spans[:5]:
            lines.append(
                f"  - {es.get('name')} ({es.get('service')}) "
                f"[{es.get('statusCode') or 'N/A'}]"
                f" durasi {es.get('duration')}ms"
            )
            em = es.get("errorMessage")
            if em:
                em = str(em).strip().replace("\n", " ")
                lines.append(f"    error: {em[:200]}")
    else:
        lines.append("Error Spans: Tidak ada span bertanda isError=true.")

    if business:
        biz_str = ", ".join(f"{k}={v}" for k, v in list(business.items())[:8])
        lines.append(f"Business attributes: {biz_str}")

    if root:
        lines.append(
            f"Root span: {root.get('name')} "
            f"({root.get('service')}) durasi {root.get('duration')}ms"
        )

    if http_logs:
        lines.append(f"\nHTTP logs (detail request, {len(http_logs)}):")
        for h in http_logs[:5]:
            if not isinstance(h, dict):
                continue
            lines.append(
                f"  - {h.get('method')} {h.get('path')} → {h.get('statusCode')} "
                f"({h.get('duration')}ms) service={h.get('service')}"
            )
            body = h.get("body")
            if body and isinstance(body, dict):
                try:
                    body_str = ", ".join(f"{k}={v}" for k, v in list(body.items())[:6])
                except Exception:
                    body_str = str(body)
                lines.append(f"    body: {body_str}")

    return "\n".join(lines)