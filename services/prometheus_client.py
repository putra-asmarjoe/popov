import asyncio
import logging
import re
from typing import Optional, List, Dict, Any
import httpx
from config.settings import settings
from services.service_name_utils import matches_service, service_name_variants

logger = logging.getLogger(__name__)


def _extract_metric_value(res: Optional[Dict[str, Any]]) -> str:
    """Ekstrak nilai float/string dari Prometheus result list (digunakan get_pod_health)."""
    if not res:
        return "N/A"
    result_list = res.get("result", [])
    if not result_list:
        return "N/A"
    val = result_list[0].get("value", [None, "N/A"])[1]
    try:
        return f"{float(val):.2f}"
    except (ValueError, TypeError):
        return str(val)

# Label yang relevan untuk mencocokkan alert dengan nama service (HPA, deployment, dll.)
ALERT_SERVICE_LABELS = (
    "service", "job", "app", "namespace", "deployment", "statefulset",
    "daemonset", "horizontalpodautoscaler", "hpa", "pod", "scaletargetref_name",
)

# Service placeholder (tiket watchdog tanpa nama service real) → alert TIDAK difilter
# (semua alert dianggap relevan) supaya nama service asli bisa di-resolve dari label.
_PLACEHOLDER_SERVICES = {"", "unknown", "null", "-", "n/a", "none", "undefined"}


def _is_placeholder_service(name: str) -> bool:
    return (name or "").strip().lower() in _PLACEHOLDER_SERVICES


def _extract_service_from_labels(labels: Dict[str, Any]) -> str:
    """Ekstrak nama service terbaik dari label alert (Fix #189, Opsi C).
    Prioritas: service > workload/app/deployment/hpa > job > pod (tanpa hash)."""
    if not labels:
        return ""
    for key in ("service", "app", "workload", "deployment", "statefulset",
                "daemonset", "horizontalpodautoscaler", "hpa", "scaletargetref_name"):
        val = str(labels.get(key, "") or "").strip()
        if val:
            return val
    job = str(labels.get("job", "") or "").strip()
    if job:
        return job.split("/")[-1]
    pod = str(labels.get("pod", "") or "").strip()
    if pod:
        return re.sub(r"-[a-z0-9]+(-[a-z0-9]+)?$", "", pod)
    return ""


def _alert_matches_service(labels: Dict[str, Any], service_name: str) -> bool:
    """True bila salah satu label alert cocok dengan varian nama service.
    Service placeholder → semua alert dianggap cocok (untuk resolve nama real)."""
    if _is_placeholder_service(service_name):
        return True
    for key in ALERT_SERVICE_LABELS:
        if matches_service(labels.get(key, ""), service_name):
            return True
    return False


def _get_timeout() -> float:
    return float(settings.observability_timeout_ms) / 1000.0


def _effective_url(override: Optional[str]) -> Optional[str]:
    """URL efektif per-stack (Fase D): HANYA dari override (DB observ_config).
    None/kosong → observability disabled (graceful degrade). Tanpa fallback env."""
    url = (override or "").strip()
    return url.rstrip("/") if url else None


async def query_prometheus(promql: str, base_url_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Eksekusi Prometheus instant query (GET /api/v1/query?query=...).
    base_url_override: URL stack milik workspace/project (observ_config, DB) —
    None/kosong = disabled (tanpa fallback env).
    Return dict JSON result dari Prometheus atau None jika gagal.
    """
    base = _effective_url(base_url_override)
    if not base:
        logger.debug("Prometheus disabled or URL not set.")
        return None

    url = f"{base}/api/v1/query"
    params = {"query": promql}

    try:
        async with httpx.AsyncClient(timeout=_get_timeout()) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data")
            logger.warning(f"Prometheus query returned status='{data.get('status')}': {promql}")
            return None
    except Exception as e:
        logger.error(f"Prometheus query failed ('{promql}'): {e}")
        return None


async def query_prometheus_range(
    promql: str, start: str, end: str, step: str = "15s",
    base_url_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Eksekusi Prometheus range query (GET /api/v1/query_range?...).
    base_url_override: URL stack per-project (Fase D) — None = settings.
    Return dict JSON result atau None jika gagal.
    """
    base = _effective_url(base_url_override)
    if not base:
        return None

    url = f"{base}/api/v1/query_range"
    params = {"query": promql, "start": start, "end": end, "step": step}

    try:
        async with httpx.AsyncClient(timeout=_get_timeout()) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data")
            logger.warning(f"Prometheus query_range returned status='{data.get('status')}': {promql}")
            return None
    except Exception as e:
        logger.error(f"Prometheus query_range failed ('{promql}'): {e}")
        return None


# ── STACK2 Fase 1: Pod Health & PromQL Range ─────────────────────────────────

def _parse_window_seconds(window: str) -> int:
    """Parse window string (e.g. '30m', '1h', '6h', '24h', '7d') to seconds."""
    window = window.strip().lower()
    multipliers = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    for suffix, mult in multipliers.items():
        if window.endswith(suffix):
            try:
                return int(window[:-1]) * mult
            except ValueError:
                break
    # Default: 1 hour
    return 3600


def _auto_step(seconds: int) -> str:
    """Auto-select step interval based on window duration.
    Short windows (<=1h) → 15s, medium (<=6h) → 1m, long (<=24h) → 5m, very long → 15m."""
    if seconds <= 3600:
        return "15s"
    if seconds <= 21600:
        return "60s"
    if seconds <= 86400:
        return "300s"
    return "900s"


async def query_range(
    promql: str,
    window: str = "1h",
    base_url_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Execute Prometheus range query with automatic start/end/step calculation.
    STACK2 F1-T1: convenience wrapper around query_prometheus_range.

    Args:
        promql: PromQL expression
        window: time window string (e.g. '30m', '1h', '6h', '24h', '7d')
        base_url_override: URL stack per-project (None = disabled)

    Returns:
        Dict with 'resultType', 'result', and metadata, or None on failure.
    """
    import time
    seconds = _parse_window_seconds(window)
    step = _auto_step(seconds)
    end = int(time.time())
    start = end - seconds
    result = await query_prometheus_range(
        promql,
        start=str(start),
        end=str(end),
        step=step,
        base_url_override=base_url_override,
    )
    if result:
        result["window_seconds"] = seconds
        result["step"] = step
    return result


async def get_pod_health(
    service_name: str,
    base_url_override: Optional[str] = None,
    window: str = "24h",
) -> Optional[Dict[str, Any]]:
    """
    STACK2 F1-T2 + O3 fix: Get pod health metrics via kube-state-metrics.
    Returns dict with pod restart counts (windowed), OOMKills (windowed), etc.
    Probes kube-state-metrics availability first.
    
    O3 fix: restarts and OOMKills use increase(... [window]) for windowed data,
    not lifetime totals. Default window = 24h (spec).
    """
    from services.service_name_utils import build_label_regex

    base = _effective_url(base_url_override)
    if not base:
        logger.debug("Prometheus disabled — pod health unavailable.")
        return None

    # Step 1: Probe kube-state-metrics availability
    probe_query = 'up{job="kube-state-metrics"}'
    probe = await query_prometheus(probe_query, base_url_override=base_url_override)
    if probe is None:
        # Fix #267: None = query GAGAL (server down / connection refused / HTTP error /
        # disabled) — BEDA dgn reachable tapi tidak scrape KSM (result kosong).
        # Jangan digabung jadi satu "KSM not available" yang menyesatkan diagnosis.
        logger.warning(f"Prometheus unreachable at '{base}' — cannot query pod health.")
        return {
            "available": False,
            "reason_code": "prometheus_unreachable",
            "reason": f"Prometheus not reachable at {base}",
            "suggestion": "Check the Prometheus stack URL in Workspace Settings → Stacks, or make sure the server is running.",
            "prometheus_url": base,
        }
    if not probe.get("result"):
        logger.warning("kube-state-metrics not scraped by Prometheus — cannot query pod health.")
        return {
            "available": False,
            "reason_code": "ksm_not_scraped",
            "reason": "kube-state-metrics not scraped by Prometheus",
            "suggestion": "Ensure kube-state-metrics is deployed and scraped.",
            "prometheus_url": base,
        }

    rx = build_label_regex(service_name)

    # O3: use increase() with window for windowed data (not lifetime totals)
    restarts_query = f'increase(kube_pod_container_status_restarts_total{{pod=~"{rx}.*"}}[{window}])'
    oom_query = f'increase(kube_pod_container_status_last_terminated_reason{{reason="OOMKilled",pod=~"{rx}.*"}}[{window}])'
    # Phase/ready queries are instantaneous (current state).
    # KSM emits a SERIES per phase/condition label with value 1 (aktif) / 0 —
    # `count(metric{...})` menghitung jumlah SERI (selalu 1 per status, padahal 0/1)
    # → wajib filter `== 1` agar hanya fase/kondisi AKTIF yang dihitung.
    running_query = f'count(kube_pod_status_phase{{phase="Running",pod=~"{rx}.*"}} == 1)'
    pending_query = f'count(kube_pod_status_phase{{phase="Pending",pod=~"{rx}.*"}} == 1)'
    failed_query = f'count(kube_pod_status_phase{{phase="Failed",pod=~"{rx}.*"}} == 1)'
    ready_query = f'count(kube_pod_status_ready{{condition="true",pod=~"{rx}.*"}} == 1)'
    not_ready_query = f'count(kube_pod_status_ready{{condition="false",pod=~"{rx}.*"}} == 1)'
    # Fix: desired/available replicas deployment (spec vs status) — untuk pertanyaan
    # "berapa replica". None = metric tidak tersedia (non-breaking untuk display).
    desired_query = f'kube_deployment_spec_replicas{{deployment=~"{rx}.*"}}'
    available_query = f'kube_deployment_status_replicas_available{{deployment=~"{rx}.*"}}'

    queries = {
        "restarts": restarts_query,
        "oom_kills": oom_query,
        "running": running_query,
        "pending": pending_query,
        "failed": failed_query,
        "ready": ready_query,
        "not_ready": not_ready_query,
        "desired_replicas": desired_query,
        "available_replicas": available_query,
    }

    tasks = [query_prometheus(q, base_url_override=base_url_override) for q in queries.values()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics = {}
    for key, res in zip(queries.keys(), results):
        # Fix: replica deployment — bedakan "tidak ada data" (None) dari nilai 0.
        # Gauge spec/status = per deployment; hasil kosong = deployment tidak
        # ditemukan di KSM, bukan 0 replica.
        if key in ("desired_replicas", "available_replicas") and (
            isinstance(res, Exception) or res is None or not res.get("result")
        ):
            metrics[key] = None
            continue
        if isinstance(res, Exception) or res is None:
            metrics[key] = 0
        else:
            val_str = _extract_metric_value(res)
            try:
                metrics[key] = int(float(val_str))
            except (ValueError, TypeError):
                metrics[key] = 0

    metrics["available"] = True
    metrics["service_name"] = service_name
    metrics["window"] = window
    return metrics

async def get_deployments_replica_overview(
    top_n: int = 5,
    base_url_override: Optional[str] = None,
    namespace: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fix (deployment ranking): overview replica deployment — top-N berdasarkan
    desired (spec). Untuk Q2 "deployment mana yang paling banyak replicanya"
    / Q1 "apakah semua deployment aman?" — deterministik, zero-LLM.

    PromQL: topk({top_n}, kube_deployment_spec_replicas{namespace!=""}) di-join
    kube_deployment_status_replicas_available per series (match label deployment
    + namespace). Filter namespace!="" WAJIB — series KSM tanpa namespace
    tidak boleh tercampur.

    Args:
        top_n: jumlah deployment teratas (default 5).
        base_url_override: URL stack Prometheus per-workspace (None = disabled).
        namespace: opsional — batasi ke 1 namespace workspace. None = semua
            namespace (label namespace tetap ditampilkan per item).

    Returns dict gaya get_pod_health:
        {available, reason_code, items: [{name, namespace, desired, available}]}
        reason_code: "prometheus_unreachable" | "ksm_not_scraped" | None.
    """
    base = _effective_url(base_url_override)
    if not base:
        logger.debug("Prometheus disabled — deployment replica overview unavailable.")
        return {
            "available": False,
            "reason_code": "prometheus_unreachable",
            "reason": "Prometheus not configured",
            "items": [],
        }

    # Probe KSM dulu (konsisten get_pod_health); guard exception — query_prometheus
    # biasanya return None saat gagal, tapi transport error tak terduga tetap aman.
    probe_query = 'up{job="kube-state-metrics"}'
    try:
        probe = await query_prometheus(probe_query, base_url_override=base_url_override)
    except Exception as e:
        logger.warning(f"Prometheus probe failed at '{base}': {e}")
        probe = None
    if probe is None:
        logger.warning(f"Prometheus unreachable at '{base}' — cannot query deployment overview.")
        return {
            "available": False,
            "reason_code": "prometheus_unreachable",
            "reason": f"Prometheus not reachable at {base}",
            "items": [],
        }
    if not probe.get("result"):
        logger.warning("kube-state-metrics not scraped — cannot query deployment overview.")
        return {
            "available": False,
            "reason_code": "ksm_not_scraped",
            "reason": "kube-state-metrics not scraped by Prometheus",
            "items": [],
        }

    ns_filter = f'namespace=~"{re.escape(namespace)}"' if namespace else 'namespace!=""'
    desired_query = (
        f'topk({int(top_n)}, '
        f'kube_deployment_spec_replicas{{{ns_filter}}})'
    )
    available_query = f'kube_deployment_status_replicas_available{{{ns_filter}}}'

    desired_res, avail_res = await asyncio.gather(
        query_prometheus(desired_query, base_url_override=base_url_override),
        query_prometheus(available_query, base_url_override=base_url_override),
        return_exceptions=True,
    )
    if isinstance(desired_res, Exception) or desired_res is None:
        logger.warning(f"Deployment overview desired query failed: {desired_res}")
        return {
            "available": False,
            "reason_code": "prometheus_unreachable",
            "reason": f"Prometheus query failed: {str(desired_res)[:200]}",
            "items": [],
        }

    # Map available per (namespace, deployment) utk join
    avail_map: Dict[tuple, int] = {}
    if not isinstance(avail_res, Exception) and avail_res and avail_res.get("result"):
        for series in avail_res["result"]:
            metric = series.get("metric", {}) or {}
            try:
                val = int(float((series.get("value") or [None, "0"])[1]))
            except (ValueError, TypeError, IndexError):
                continue
            avail_map[(metric.get("namespace", ""), metric.get("deployment", ""))] = val

    items: List[Dict[str, Any]] = []
    for series in (desired_res.get("result") or []):
        metric = series.get("metric", {}) or {}
        try:
            desired = int(float((series.get("value") or [None, "0"])[1]))
        except (ValueError, TypeError, IndexError):
            continue
        name = metric.get("deployment", "")
        ns = metric.get("namespace", "")
        items.append({
            "name": name,
            "namespace": ns,
            "desired": desired,
            "available": avail_map.get((ns, name), 0),
        })
    # topk sudah urut desc, tapi jaga deterministik eksplisit
    items.sort(key=lambda it: -it["desired"])

    return {"available": True, "reason_code": None, "items": items}


async def get_active_alerts(
    service_name: str,
    alertmanager_url_override: Optional[str] = None,
    prometheus_url_override: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Ambil active alerts dari Alertmanager (GET /api/v2/alerts atau /api/v1/alerts)
    atau fallback ke Prometheus alerts jika Alertmanager URL tidak di-set.
    Override URL per-stack (Fase D) — None = settings (.env fallback).
    Pencocokan alert → service dilakukan pada banyak label (service/job/app/namespace/
    deployment/hpa/pod/dll) dengan varian nama service (underscore, hyphen, -apps).
    """
    matching = []
    am_base = _effective_url(alertmanager_url_override)
    prom_base = _effective_url(prometheus_url_override)

    # 1. Utama: Query ke Alertmanager jika URL efektif ada
    if am_base:
        base_url = am_base
        try:
            async with httpx.AsyncClient(timeout=_get_timeout()) as client:
                # Target Alertmanager API v2 (standard)
                resp = await client.get(f"{base_url}/api/v2/alerts")
                if resp.status_code == 200:
                    alerts_data = resp.json()
                    if isinstance(alerts_data, list):
                        for alert in alerts_data:
                            labels = alert.get("labels", {})
                            if not _alert_matches_service(labels, service_name):
                                continue
                            status_obj = alert.get("status", {})
                            state = status_obj.get("state", "firing") if isinstance(status_obj, dict) else "firing"
                            matching.append({
                                "name": labels.get("alertname", "UnknownAlert"),
                                "severity": labels.get("severity", "warning"),
                                "state": state,
                                "active_at": alert.get("startsAt"),
                                "service": _extract_service_from_labels(labels),
                                "description": alert.get("annotations", {}).get("description", "")
                                             or alert.get("annotations", {}).get("summary", ""),
                            })
                        return matching

                # Fallback: Alertmanager API v1 jika v2 return 404
                resp_v1 = await client.get(f"{base_url}/api/v1/alerts")
                if resp_v1.status_code == 200:
                    data = resp_v1.json()
                    alerts = data.get("data", []) if isinstance(data, dict) else []
                    for alert in alerts:
                        labels = alert.get("labels", {})
                        if not _alert_matches_service(labels, service_name):
                            continue
                        matching.append({
                            "name": labels.get("alertname", "UnknownAlert"),
                            "severity": labels.get("severity", "warning"),
                            "state": alert.get("status", {}).get("state", "firing") if isinstance(alert.get("status"), dict) else "firing",
                            "active_at": alert.get("startsAt"),
                            "service": _extract_service_from_labels(labels),
                            "description": alert.get("annotations", {}).get("description", "")
                                         or alert.get("annotations", {}).get("summary", ""),
                        })
                    return matching
        except Exception as e:
            logger.error(f"Alertmanager query failed for service '{service_name}' on '{am_base}': {e}")

    # 2. Fallback: Query ke Prometheus alerts jika Alertmanager URL tidak di-set / gagal
    if prom_base:
        url = f"{prom_base}/api/v1/alerts"
        try:
            async with httpx.AsyncClient(timeout=_get_timeout()) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "success":
                    alerts = data.get("data", {}).get("alerts", [])
                    for alert in alerts:
                        labels = alert.get("labels", {})
                        if not _alert_matches_service(labels, service_name):
                            continue
                        matching.append({
                            "name": labels.get("alertname", "UnknownAlert"),
                            "severity": labels.get("severity", "warning"),
                            "state": alert.get("state", "firing"),
                            "active_at": alert.get("activeAt"),
                            "service": _extract_service_from_labels(labels),
                            "description": alert.get("annotations", {}).get("description", "")
                                         or alert.get("annotations", {}).get("summary", ""),
                        })
                    return matching
        except Exception as e:
            logger.error(f"Prometheus alerts fallback failed for service '{service_name}': {e}")

    return []

