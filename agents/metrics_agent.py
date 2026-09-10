import asyncio
import logging
from typing import Dict, Any
from state.schema import AgentState
from config.settings import settings
from services.prometheus_client import query_prometheus, get_active_alerts
from services.service_name_utils import build_label_regex

logger = logging.getLogger(__name__)

# STACK2-LANG (Fix #259): bilingual strings for pod_health / promql_range paths.
# Pattern: knowledge_listing._L — t = _L.get(locale, _L["en"])
_METRICS_L = {
    "en": {
        "no_stack": "Pod health unavailable: no Prometheus stack configured. Add it in Workspace Settings → Stacks.",
        "unavailable": "Pod health unavailable for '{svc}'.",
        "no_promql": "PromQL range unavailable: no PromQL provided.",
        "no_range_stack": "PromQL range unavailable: no Prometheus stack configured.",
        "no_range_data": "PromQL range returned no data for: `{promql}`",
        "range_error": "PromQL range error: {err}",
        "pod_error": "Pod health error: {err}",
        "no_service": "Metrics unavailable: service_name is empty.",
        "no_metrics_stack": "Metrics unavailable: no Prometheus stack (observability target) for this context.",
        "metrics_error": "Metrics error: {err}",
        "pod_header": "**Pod Health** \u2014 `{svc}` (last {window})",
        "running": "Running", "pending": "Pending", "failed": "Failed",
        "ready": "Ready", "not_ready": "Not Ready",
        "replicas": "Replicas",
        "restarts": "\u26a0\ufe0f Restarts ({window}): {n}",
        "oom_kills": "\U0001f6d8 OOMKills ({window}): {n}",
        "not_ready_pods": "\u26a0\ufe0f Not-ready pods: {n}",
        "failed_pods": "\u274c Failed pods: {n}",
        "verdict_healthy": "Verdict: \u2705 **Healthy**",
        "verdict_degraded": "Verdict: \u26a0\ufe0f **Degraded**",
        "verdict_unhealthy": "Verdict: \u274c **Unhealthy**",
        "pod_unavailable": "**Pod Health** \u2014 kube-state-metrics not available\n> {reason}. {suggestion}",
        "range_header": "**{desc}**",
        "range_meta": "window {window} · step {step}",
        "range_type": "Result type",
        "no_data": "No data returned.",
        "no_values": "no values",
        "no_numeric": "no numeric values",
        "more_series": "... and {n} more series",
        "cont_group": "({n} containers)",
        "no_labels": "(no labels)",
        "unhandled_type": "Unhandled result type: {t}",
    },
    "id": {
        "no_stack": "Pod health tidak tersedia: stack Prometheus belum dikonfigurasi. Tambahkan di Workspace Settings → Stacks.",
        "unavailable": "Pod health tidak tersedia untuk '{svc}'.",
        "no_promql": "PromQL range tidak tersedia: tidak ada PromQL yang diberikan.",
        "no_range_stack": "PromQL range tidak tersedia: stack Prometheus belum dikonfigurasi.",
        "no_range_data": "PromQL range tidak mengembalikan data untuk: `{promql}`",
        "range_error": "Error PromQL range: {err}",
        "pod_error": "Error pod health: {err}",
        "no_service": "Metrics tidak tersedia: service_name kosong.",
        "no_metrics_stack": "Metrics tidak tersedia: belum ada stack Prometheus (observability target) untuk konteks ini.",
        "metrics_error": "Error metrics: {err}",
        "pod_header": "**Kesehatan Pod** \u2014 `{svc}` ({window} terakhir)",
        "running": "Berjalan", "pending": "Menunggu", "failed": "Gagal",
        "ready": "Siap", "not_ready": "Belum Siap",
        "replicas": "Replica",
        "restarts": "\u26a0\ufe0f Restart ({window}): {n}",
        "oom_kills": "\U0001f6d8 OOMKill ({window}): {n}",
        "not_ready_pods": "\u26a0\ufe0f Pod belum siap: {n}",
        "failed_pods": "\u274c Pod gagal: {n}",
        "verdict_healthy": "Kesimpulan: \u2705 **Sehat**",
        "verdict_degraded": "Kesimpulan: \u26a0\ufe0f **Menurun**",
        "verdict_unhealthy": "Kesimpulan: \u274c **Tidak Sehat**",
        "pod_unavailable": "**Pod Health** \u2014 kube-state-metrics tidak tersedia\n> {reason}. {suggestion}",
        "range_header": "**{desc}**",
        "range_meta": "window {window} · step {step}",
        "range_type": "Tipe hasil",
        "no_data": "Tidak ada data.",
        "no_values": "tidak ada nilai",
        "no_numeric": "tidak ada nilai numerik",
        "more_series": "... dan {n} seri lainnya",
        "cont_group": "({n} container)",
        "no_labels": "(tanpa label)",
        "unhandled_type": "Tipe hasil belum ditangani: {t}",
    },
}

# Fix #267: pesan bilingual per reason_code dari get_pod_health (services/prometheus_client.py).
# reason_code = API stabil antar-modul; `reason` free-text di dict hasil hanya fallback
# utk code tak dikenal / data lama. Tambah code baru di DUA tempat: prometheus_client
# (return dict) + map ini.
_POD_UNAVAILABLE_L = {
    "en": {
        "prometheus_unreachable": {
            "header": "**Pod Health** — Prometheus unreachable",
            "reason": "Prometheus is not reachable ({url})",
            "suggestion": "Check the Prometheus stack URL and make sure the server is running — Workspace Settings → Stacks.",
        },
        "ksm_not_scraped": {
            "header": "**Pod Health** — kube-state-metrics not available",
            "reason": "kube-state-metrics is not scraped by this Prometheus",
            "suggestion": "Ensure kube-state-metrics is deployed in the cluster and scraped by Prometheus.",
        },
    },
    "id": {
        "prometheus_unreachable": {
            "header": "**Kesehatan Pod** — Prometheus tidak dapat dihubungi",
            "reason": "Prometheus tidak bisa dihubungi ({url})",
            "suggestion": "Periksa URL stack Prometheus dan pastikan servernya berjalan — Workspace Settings → Stacks.",
        },
        "ksm_not_scraped": {
            "header": "**Kesehatan Pod** — kube-state-metrics tidak tersedia",
            "reason": "kube-state-metrics tidak di-scrape oleh Prometheus ini",
            "suggestion": "Pastikan kube-state-metrics ter-deploy di cluster dan di-scrape oleh Prometheus.",
        },
    },
}


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


def _format_pod_health_summary(pod_health: dict, locale: str = "en") -> str:
    """STACK2 F1-T3 + O3 + Fix #259: Format pod health to <500 token summary (bilingual)."""
    t = _METRICS_L.get(locale, _METRICS_L["en"])
    if not pod_health.get("available"):
        # Fix #267: reason_code → bilingual text + header per kode. reason_code adalah
        # API stabil (prometheus_unreachable / ksm_not_scraped); `reason` free-text
        # hanya fallback utk code tak dikenal / data lama.
        code = pod_health.get("reason_code") or ""
        reasons = _POD_UNAVAILABLE_L.get(locale, _POD_UNAVAILABLE_L["en"])
        r = reasons.get(code)
        if r:
            return "{header}\n> {reason}. {suggestion}".format(
                header=r["header"],
                reason=r["reason"].format(url=pod_health.get("prometheus_url") or ""),
                suggestion=r["suggestion"],
            )
        reason = pod_health.get("reason", "unknown")
        suggestion = pod_health.get("suggestion", "")
        return t["pod_unavailable"].format(reason=reason, suggestion=suggestion)

    restarts = pod_health.get("restarts", 0)
    oom_kills = pod_health.get("oom_kills", 0)
    running = pod_health.get("running", 0)
    pending = pod_health.get("pending", 0)
    failed = pod_health.get("failed", 0)
    ready = pod_health.get("ready", 0)
    not_ready = pod_health.get("not_ready", 0)
    svc = pod_health.get("service_name", "unknown")
    window = pod_health.get("window", "24h")

    lines = [t["pod_header"].format(svc=svc, window=window)]
    lines.append(f"{t['running']}: {running} | {t['pending']}: {pending} | {t['failed']}: {failed}")
    lines.append(f"{t['ready']}: {ready} | {t['not_ready']}: {not_ready}")
    # Fix: Replicas (desired/available) — hanya tampil bila data ada (non-breaking).
    # Key desired_replicas/available_replicas, bukan "available" (sudah dipakai
    # sebagai flag availability pod_health). None = tidak ada data → "?".
    desired = pod_health.get("desired_replicas")
    available = pod_health.get("available_replicas")
    if desired is not None or available is not None:
        d_str = str(desired) if desired is not None else "?"
        a_str = str(available) if available is not None else "?"
        lines.append(f"{t['replicas']}: {d_str}/{a_str} (running {running})")
    if restarts > 0:
        lines.append(t["restarts"].format(window=window, n=restarts))
    if oom_kills > 0:
        lines.append(t["oom_kills"].format(window=window, n=oom_kills))
    if not_ready > 0:
        lines.append(t["not_ready_pods"].format(n=not_ready))
    if failed > 0:
        lines.append(t["failed_pods"].format(n=failed))

    # Health verdict
    if failed > 0 or oom_kills > 0 or not_ready > 1:
        lines.append(t["verdict_unhealthy"])
    elif restarts > 0 or not_ready > 0:
        lines.append(t["verdict_degraded"])
    else:
        lines.append(t["verdict_healthy"])

    return "\n".join(lines)


def _human_duration(seconds: int) -> str:
    """Fix #263 T2: seconds → human duration. 21600→'6h', 3600→'1h', 60→'1m', 900→'15m', 15→'15s'.
    Inverse of prometheus_client._parse_window_seconds; minutes preferred under 1h when divisible."""
    if seconds <= 0:
        return "0s"
    if seconds % 86400 == 0 and seconds >= 86400:
        n = seconds // 86400
        return f"{n}d"
    if seconds % 3600 == 0 and seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0 and seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _human_series_label(labels: dict) -> str:
    """Fix #263 T2/D3: label allow-list — keep only pod/container/node (drop id, image,
    metrics_path, service, name dupe, instance, endpoint, job, namespace...).
    Returns e.g. 'pod foo-app-79645-wvm4k · container app'; '(no labels)' when empty."""
    parts = []
    for key in ("pod", "container", "deployment", "node"):
        val = labels.get(key)
        if val:
            parts.append(f"{key} {val}")
    return " · ".join(parts) if parts else "(no labels)"


def _is_infra_series(labels: dict) -> bool:
    """Fix #263 T2/D4: infra containers (cAdvisor 'POD' umbrella series, pause containers) → skip."""
    if labels.get("container") == "POD":
        return True
    image = labels.get("image") or ""
    if "/pause" in image:
        return True
    return False


def _fmt_value(v: float) -> str:
    """Smart unit formatting (extracted from _format_range_result O7 logic)."""
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}k"
    if 0 < v < 0.01:
        return f"{v:.4f}"
    if v < 1:
        return f"{v:.3f}"
    return f"{v:.1f}"


def _compute_series_stats(values: list) -> list:
    """Extract numeric values from a matrix series' [[ts, val], ...] pairs."""
    nums = []
    for v in values:
        if isinstance(v, (list, tuple)) and len(v) > 1:
            try:
                nums.append(float(v[1]))
            except (ValueError, TypeError):
                pass
    return nums


def _trend_of(nums: list) -> str:
    """O7 trend: compare last-quarter mean vs first-quarter mean."""
    import statistics
    n = len(nums)
    quarter = max(1, n // 4)
    first_q = statistics.mean(nums[:quarter])
    last_q = statistics.mean(nums[-quarter:])
    pct_change = ((last_q - first_q) / first_q * 100) if first_q > 0 else 0
    if abs(pct_change) < 5:
        return "→ stable"
    if pct_change > 0:
        return f"↗ +{pct_change:.0f}%"
    return f"↘ {pct_change:.0f}%"


def _format_range_result(result: dict, description: str, locale: str = "en") -> str:
    """STACK2 F1-T3 + O7 + Fix #259/#263: format Prometheus range result (bilingual, readable).

    Fix #263: humanized window/step, label allow-list, infra series dropped,
    one compact stats line per series, description header exactly once.
    """
    import statistics
    t = _METRICS_L.get(locale, _METRICS_L["en"])

    result_type = result.get("resultType", "unknown")
    data = result.get("result", [])
    window = result.get("window_seconds", 0)
    step = result.get("step", "?")

    lines = []
    if description:
        # Fix #263 T3.6: description header appears EXACTLY once
        lines.append(t["range_header"].format(desc=description))

    if not data:
        lines.append(t["no_data"])
        return "\n".join(lines)

    if result_type == "matrix":
        # Fix #263 T3: infra series dropped, allow-list labels, compact lines
        series_list = [s for s in data if not _is_infra_series(s.get("metric", {}) or {})]
        if not series_list:
            lines.append(t["no_data"])
            return "\n".join(lines)
        # Meta line: optional metric name prefix + humanized window/step (D2)
        metric_name = ""
        for s in series_list:
            mn_meta = (s.get("metric", {}) or {}).get("__name__") or ""
            if mn_meta:
                metric_name = mn_meta
                break
        meta = t["range_meta"].format(
            window=_human_duration(window),
            step=_human_duration(step) if isinstance(step, int) else str(step),
        )
        if metric_name:
            meta = f"`{metric_name}` · {meta}"
        lines.append(meta)
        lines.append("")
        for series in series_list[:5]:  # D5: max 5 lines, footer for overflow
            labels = series.get("metric", {}) or {}
            label_str = _human_series_label(labels)
            values = series.get("values", [])
            if not values:
                lines.append(f"• {label_str}: {t['no_values']}")
                continue
            nums = _compute_series_stats(values)
            if not nums:
                lines.append(f"• {label_str}: {t['no_numeric']}")
                continue
            mn, mx = min(nums), max(nums)
            avg = statistics.mean(nums)
            trend = _trend_of(nums)
            lines.append(
                f"• {label_str}: avg={_fmt_value(avg)} · min={_fmt_value(mn)} · max={_fmt_value(mx)} {trend}"
            )
        if len(series_list) > 5:
            lines.append(t["more_series"].format(n=len(series_list) - 5))
    elif result_type == "vector":
        # Fix #263 T4/D6: instant vector — allow-list labels, one value per line
        lines.append(t["range_meta"].format(
            window=_human_duration(window),
            step=_human_duration(step) if isinstance(step, int) else str(step),
        ))
        lines.append("")
        shown = 0
        for series in data:
            if shown >= 10:
                break
            labels = series.get("metric", {}) or {}
            if _is_infra_series(labels):
                continue
            label_str = _human_series_label(labels)
            value = series.get("value", [None, "?"])
            raw_val = value[1] if len(value) > 1 else "?"
            try:
                val_str = _fmt_value(float(raw_val))
            except (ValueError, TypeError):
                val_str = str(raw_val)
            lines.append(f"• {label_str}: {val_str}")
            shown += 1
    else:
        lines.append(t["unhandled_type"].format(t=result_type))

    return "\n".join(lines)

async def _handle_pod_health(state: AgentState, agents_visited: list, service_name: str, locale: str = "en") -> dict:
    """STACK2 F1-T3 + O3 + Fix #259: Handle pod_health mode — query kube-state-metrics with window (bilingual)."""
    from services.observability_store import get_observ_config_for_state
    from services.prometheus_client import get_pod_health
    t = _METRICS_L.get(locale, _METRICS_L["en"])

    obs_cfg = await get_observ_config_for_state(state)
    prom_override = (obs_cfg or {}).get("prometheus_url")
    if not prom_override:
        return {
            "metrics_data": None,
            "metrics_summary": t["no_stack"],
            "metrics_available": False,
            "agents_visited": agents_visited,
        }

    window = state.get("metrics_window") or "24h"  # O3: default 24h for pod health

    try:
        pod_health = await get_pod_health(service_name, base_url_override=prom_override, window=window)
        if pod_health is None:
            summary = t["unavailable"].format(svc=service_name)
        elif not pod_health.get("available"):
            summary = _format_pod_health_summary(pod_health, locale)
        else:
            summary = _format_pod_health_summary(pod_health, locale)

        return {
            "metrics_data": pod_health,
            "metrics_summary": summary,
            "metrics_available": bool(pod_health and pod_health.get("available")),
            "agents_visited": agents_visited,
        }
    except Exception as e:
        logger.error(f"Pod health query failed for '{service_name}': {e}", exc_info=True)
        return {
            "metrics_data": None,
            "metrics_summary": t["pod_error"].format(err=str(e)),
            "metrics_available": False,
            "agents_visited": agents_visited,
        }


async def _handle_promql_range(state: AgentState, agents_visited: list, locale: str = "en") -> dict:
    """STACK2 F1-T3 + Fix #259: Handle promql_range mode — execute translated PromQL (bilingual)."""
    from services.observability_store import get_observ_config_for_state
    from services.prometheus_client import query_range
    t = _METRICS_L.get(locale, _METRICS_L["en"])

    promql = state.get("metrics_promql")
    window = state.get("metrics_window") or "1h"
    description = state.get("metrics_description") or ""

    if not promql:
        return {
            "metrics_data": None,
            "metrics_summary": t["no_promql"],
            "metrics_available": False,
            "agents_visited": agents_visited,
        }

    obs_cfg = await get_observ_config_for_state(state)
    prom_override = (obs_cfg or {}).get("prometheus_url")
    if not prom_override:
        return {
            "metrics_data": None,
            "metrics_summary": t["no_range_stack"],
            "metrics_available": False,
            "agents_visited": agents_visited,
        }

    try:
        result = await query_range(promql, window=window, base_url_override=prom_override)
        if result:
            summary = _format_range_result(result, description, locale)
            return {
                "metrics_data": result,
                "metrics_summary": summary,
                "metrics_available": True,
                "agents_visited": agents_visited,
            }
        return {
            "metrics_data": None,
            "metrics_summary": t["no_range_data"].format(promql=promql),
            "metrics_available": False,
            "agents_visited": agents_visited,
        }
    except Exception as e:
        logger.error(f"PromQL range query failed: {e}", exc_info=True)
        return {
            "metrics_data": None,
            "metrics_summary": t["range_error"].format(err=str(e)),
            "metrics_available": False,
            "agents_visited": agents_visited,
        }


async def metrics_agent(state: AgentState) -> dict:
    """
    Query Prometheus metrics & active alerts untuk service_name secara paralel.
    STACK2 F1-T3 + Fix #259: Handles pod_health and promql_range modes (no LLM, bilingual).
    Exception safe — tidak boleh throw error.
    """
    service_name = state.get("service_name", "")
    agents_visited = ["metrics_agent"]
    from services.conversation import resolve_state_locale
    locale = await resolve_state_locale(state)
    t = _METRICS_L.get(locale, _METRICS_L["en"])

    # ── STACK2 F1: Pod Health mode (standalone, no correlation/triage) ──────
    metrics_mode = state.get("metrics_mode")
    if metrics_mode == "pod_health":
        return await _handle_pod_health(state, agents_visited, service_name, locale)
    if metrics_mode == "promql_range":
        return await _handle_promql_range(state, agents_visited, locale)

    if not service_name:
        return {
            "metrics_data": None,
            "metrics_summary": t["no_service"],
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
            "metrics_summary": t["no_metrics_stack"],
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
            "metrics_summary": t["metrics_error"].format(err=str(e)),
            "metrics_available": False,
            "agents_visited": agents_visited,
        }
