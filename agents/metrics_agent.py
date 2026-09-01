import asyncio
import logging
from typing import Dict, Any
from state.schema import AgentState
from config.settings import settings
from services.prometheus_client import query_prometheus, get_active_alerts
from services.service_name_utils import build_label_regex

logger = logging.getLogger(__name__)


def _build_queries(service_name: str) -> Dict[str, str]:
    """Bangun PromQL dengan regex label yang mencakup varian nama service (hyphen/-apps)."""
    rx = build_label_regex(service_name)
    return {
        "error_rate": f'rate(http_requests_total{{service=~"{rx}"}}[5m])',
        "request_rate": f'rate(http_requests_total{{service=~"{rx}"}}[5m])',
        "latency_p99": f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service=~"{rx}"}}[5m]))',
        "memory_bytes": f'container_memory_usage_bytes{{pod=~"{rx}.*"}}',
        "cpu_rate": f'rate(container_cpu_usage_seconds_total{{pod=~"{rx}.*"}}[5m])',
        # HPA: current vs max replicas (deteksi HPA maxed out)
        "hpa_current": f'kube_horizontalpodautoscaler_status_current_replicas{{horizontalpodautoscaler=~"{rx}"}}',
        "hpa_max": f'kube_horizontalpodautoscaler_spec_max_replicas{{horizontalpodautoscaler=~"{rx}"}}',
    }


def _extract_metric_value(res: Dict[str, Any]) -> str:
    """Ekstrak nilai float/string dari Prometheus result list."""
    if not res:
        return "N/A"
    result_list = res.get("result", [])
    if not result_list:
        return "N/A"
    val = result_list[0].get("value", [None, "N/A"])[1]
    try:
        fval = float(val)
        return f"{fval:.2f}"
    except (ValueError, TypeError):
        return str(val)


def _analyze_hpa(current_res: Dict[str, Any], max_res: Dict[str, Any]) -> str:
    """Deteksi HPA maxed out: current >= max. Return deskripsi status."""
    cur = _extract_metric_value(current_res)
    mx = _extract_metric_value(max_res)
    if cur in ("N/A", "0.00") and mx in ("N/A", "0.00"):
        return "N/A"
    try:
        if float(cur) >= float(mx):
            return f"HPA MAXED OUT (current={cur} / max={mx})"
        return f"HPA normal (current={cur} / max={mx})"
    except (ValueError, TypeError):
        return f"HPA unknown (current={cur} / max={mx})"


def _dominant_service(alerts: list) -> str:
    """Fix #189 (Opsi C): resolve nama service asli dari label alert aktif (paling sering).
    Return "" bila tidak ada alert / label service kosong."""
    from collections import Counter
    services = [str(a.get("service") or "").strip().lower() for a in alerts or []]
    services = [s for s in services if s and not s in ("unknown", "null", "-")]
    if not services:
        return ""
    top = Counter(services).most_common(1)[0][0]
    return top


def _build_metrics_summary(service_name: str, raw_metrics: Dict[str, Any], alerts: list) -> str:
    """Format metrics_summary string ringkas (<500 token)."""
    hpa_status = _analyze_hpa(raw_metrics.get("hpa_current"), raw_metrics.get("hpa_max"))
    lines = [
        f"=== METRICS SUMMARY: {service_name} ===",
        f"Prometheus Status: Available",
        f"Error rate (5m): {_extract_metric_value(raw_metrics.get('error_rate'))}",
        f"Request rate: {_extract_metric_value(raw_metrics.get('request_rate'))} req/s",
        f"Latency p99: {_extract_metric_value(raw_metrics.get('latency_p99'))} s",
        f"Memory usage: {_extract_metric_value(raw_metrics.get('memory_bytes'))} bytes",
        f"CPU rate: {_extract_metric_value(raw_metrics.get('cpu_rate'))}",
        f"HPA Status: {hpa_status}",
    ]

    if alerts:
        lines.append(f"\nActive Alerts ({len(alerts)}):")
        for a in alerts[:3]:
            lines.append(f"  - [{a.get('severity', 'warning').upper()}] {a.get('name')}: {a.get('description', '')}")
    else:
        lines.append("\nActive Alerts: Tidak ada alert aktif.")

    return "\n".join(lines)


async def metrics_agent(state: AgentState) -> dict:
    """
    Query Prometheus metrics & active alerts untuk service_name secara paralel.
    Exception safe — tidak boleh throw error.
    """
    service_name = state.get("service_name", "")
    agents_visited = ["metrics_agent"]

    if not service_name:
        return {
            "metrics_data": None,
            "metrics_summary": "Metrics tidak tersedia: service_name kosong.",
            "metrics_available": False,
            "agents_visited": agents_visited,
        }

    # Fix #45: sumber stack = DB observ_config (bukan env). Tanpa stack → degraded.
    from services.observability_store import get_observ_config_for_state
    obs_cfg = await get_observ_config_for_state(state)
    prom_override = (obs_cfg or {}).get("prometheus_url")
    am_override = (obs_cfg or {}).get("alertmanager_url")
    if not prom_override:
        logger.info(f"Prometheus disabled (no stack configured in DB). Skipping metrics for '{service_name}'.")
        return {
            "metrics_data": None,
            "metrics_summary": "Metrics tidak tersedia: belum ada stack Prometheus (observability target) untuk konteks ini.",
            "metrics_available": False,
            "agents_visited": agents_visited,
        }

    logger.info(
        f"MetricsAgent querying Prometheus for service='{service_name}' "
        f"(stack={'custom' if prom_override else 'global'})"
    )

    try:
        # Build queries per metric
        queries = _build_queries(service_name)

        # Run PromQL queries and alert lookup in parallel
        tasks = [query_prometheus(promql, base_url_override=prom_override) for promql in queries.values()]
        alert_task = get_active_alerts(service_name, alertmanager_url_override=am_override, prometheus_url_override=prom_override)

        results = await asyncio.gather(*tasks, alert_task, return_exceptions=True)

        metric_results = {}
        for key, res in zip(queries.keys(), results[:-1]):
            if isinstance(res, Exception) or res is None:
                metric_results[key] = None
            else:
                metric_results[key] = res

        alerts = results[-1] if not isinstance(results[-1], Exception) else []

        summary = _build_metrics_summary(service_name, metric_results, alerts)

        # Fix #189 (Opsi C): service placeholder ("unknown") → resolve nama asli dari
        # alert aktif supaya laporan & offer pakai service yang benar (mis. rabbitmq-cluster).
        resolved = ""
        from services.prometheus_client import _is_placeholder_service
        if _is_placeholder_service(service_name):
            resolved = _dominant_service(alerts)

        return {
            "metrics_data": {"queries": metric_results, "alerts": alerts},
            "metrics_summary": summary,
            "metrics_available": True,
            "resolved_service_name": resolved or None,
            "agents_visited": agents_visited,
        }

    except Exception as e:
        logger.error(f"MetricsAgent error for '{service_name}': {e}", exc_info=True)
        return {
            "metrics_data": None,
            "metrics_summary": f"Metrics error: {str(e)}",
            "metrics_available": False,
            "agents_visited": agents_visited,
        }
