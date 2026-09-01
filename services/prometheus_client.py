import logging
import re
from typing import Optional, List, Dict, Any
import httpx
from config.settings import settings
from services.service_name_utils import matches_service, service_name_variants

logger = logging.getLogger(__name__)

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

