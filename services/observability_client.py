import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_timeout() -> float:
    return float(settings.observability_timeout_ms) / 1000.0


async def _fetch_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """HTTP GET yang fault-tolerant. Return parsed JSON atau None (tidak pernah raise)."""
    try:
        async with httpx.AsyncClient(timeout=_get_timeout()) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Observability HTTP failed for url='{url}': {e}")
        return None


# Label prioritas tinggi = objek yang benar-benar terdampak (bukan exporter/collector).
# Alert infra (mis. KubeHpaMaxedOut) ber-label `service`/`job` = exporter kube-state-metrics,
# padahal target sebenarnya ada di label horizontalpodautoscaler/deployment.
_SERVICE_LABELS_PRIORITY = (
    "horizontalpodautoscaler", "hpa", "deployment", "statefulset", "daemonset",
    "service", "app",
    "job",
    "namespace",
)


def _extract_service(labels: Dict[str, Any]) -> str:
    """Ekstrak nama service yang terdampak dari label alert (target HPA > deployment > service)."""
    for key in _SERVICE_LABELS_PRIORITY:
        val = labels.get(key)
        if val:
            return str(val)
    return "unknown"


def _normalize_alert(source: str, labels: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Bentuk alert menjadi struktur ringkas yang seragam."""
    return {
        "source": source,
        "name": labels.get("alertname", "UnknownAlert"),
        "severity": labels.get("severity", "warning"),
        "service": _extract_service(labels),
        "state": extra.get("state", "firing"),
        "active_at": extra.get("active_at"),
        "description": extra.get("description", ""),
    }


async def get_alertmanager_active(base_url_override: Optional[str] = None) -> List[Dict[str, Any]]:
    """Semua active alert dari Alertmanager (API v2, fallback v1). Tanpa filter service.
    base_url_override: untuk multi-stack (SCALE plan) — HANYA dari DB observ_config; None = disabled."""
    base = (base_url_override or "").rstrip("/")
    if not (base and settings.observability_enabled):
        return []
    alerts = []

    data = await _fetch_json(f"{base}/api/v2/alerts")
    if isinstance(data, list):
        for alert in data:
            labels = alert.get("labels", {})
            status_obj = alert.get("status", {})
            state = status_obj.get("state", "firing") if isinstance(status_obj, dict) else "firing"
            alerts.append(_normalize_alert(
                "alertmanager", labels,
                {
                    "state": state,
                    "active_at": alert.get("startsAt"),
                    "description": alert.get("annotations", {}).get("description", "")
                                   or alert.get("annotations", {}).get("summary", ""),
                },
            ))
        return alerts

    data = await _fetch_json(f"{base}/api/v1/alerts")
    if isinstance(data, dict):
        for alert in data.get("data", []):
            labels = alert.get("labels", {})
            alerts.append(_normalize_alert(
                "alertmanager", labels,
                {
                    "state": alert.get("status", {}).get("state", "firing") if isinstance(alert.get("status"), dict) else "firing",
                    "active_at": alert.get("startsAt"),
                    "description": alert.get("annotations", {}).get("description", "")
                                   or alert.get("annotations", {}).get("summary", ""),
                },
            ))
        return alerts

    return alerts


async def get_prometheus_firing(prometheus_url_override: Optional[str] = None) -> List[Dict[str, Any]]:
    """Semua alert yang sedang FIRING dari Prometheus (/api/v1/alerts). Tanpa filter service.
    prometheus_url_override: multi-stack (SCALE plan) — HANYA dari DB; None = disabled."""
    base = (prometheus_url_override or "").rstrip("/")
    if not (base and settings.observability_enabled):
        return []
    url = f"{base}/api/v1/alerts"
    data = await _fetch_json(url)
    if not data or data.get("status") != "success":
        return []
    alerts = []
    for alert in data.get("data", {}).get("alerts", []):
        if alert.get("state") != "firing":
            continue
        labels = alert.get("labels", {})
        alerts.append(_normalize_alert(
            "prometheus", labels,
            {
                "state": alert.get("state", "firing"),
                "active_at": alert.get("activeAt"),
                "description": alert.get("annotations", {}).get("description", "")
                               or alert.get("annotations", {}).get("summary", ""),
            },
        ))
    return alerts


async def get_tempo_5xx(limit: int = 5, tempo_url_override: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Trace dengan status code 5xx dari Tempo (/api/search?tags=http.status_code=500).
    Setiap trace di-enrich dengan detail span (jumlah, service terlibat, span error)
    via /api/traces/{trace_id}. Fault-tolerant: bila detail gagal, metadata tetap ada.
    tempo_url_override: multi-stack (SCALE plan) — HANYA dari DB observ_config; None = disabled.
    """
    base = (tempo_url_override or "").rstrip("/")
    if not (base and settings.observability_enabled):
        return []
    url = f"{base}/api/search"
    data = await _fetch_json(url, params={"tags": "http.status_code=500", "limit": limit})
    if not isinstance(data, dict):
        return []
    traces = []
    for trace in data.get("traces", [])[:limit]:
        trace_id = trace.get("traceID")
        enriched = {
            "source": "tempo",
            "trace_id": trace_id,
            "service": trace.get("rootServiceName") or "unknown",
            "root_trace_name": trace.get("rootTraceName") or "",
            "span_count": trace.get("spanCount"),
            "duration_ms": trace.get("durationMs"),
        }
        try:
            detail = await _fetch_json(f"{base}/api/traces/{trace_id}")
            if detail:
                enriched.update(_summarize_trace_detail(detail))
        except Exception as e:
            logger.error(f"Observability enrich trace '{trace_id}' failed: {e}")
        traces.append(enriched)
    return traces


def _summarize_trace_detail(trace_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ekstrak ringkasan dari detail trace Tempo: total span, service terlibat,
    span error (STATUS_CODE_ERROR/ERROR), dan durationMs.
    """
    batches = trace_data.get("batches", [])
    total_spans = 0
    services = set()
    error_spans = []

    for batch in batches:
        svc_name = "unknown"
        for attr in batch.get("resource", {}).get("attributes", []):
            if attr.get("key") == "service.name":
                svc_name = attr.get("value", {}).get("stringValue", "unknown")
                break
        if svc_name and svc_name != "unknown":
            services.add(svc_name)

        scope_spans = batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", []))
        for scope in scope_spans:
            for span in scope.get("spans", []):
                total_spans += 1
                status = span.get("status", {})
                code = status.get("code") or status.get("statusCode")
                if code in ("STATUS_CODE_ERROR", "ERROR", 2):
                    error_spans.append({
                        "name": span.get("name", "unknown"),
                        "service": svc_name,
                    })

    return {
        "span_count": total_spans if total_spans else None,
        "services_involved": sorted(services) if services else [],
        "error_spans": error_spans,
    }


def _is_ignored_alert(alert: Dict[str, Any]) -> bool:
    """True bila alert harus disaring (nama atau severity masuk daftar ignore dari settings)."""
    name = (alert.get("name") or "").lower()
    severity = (alert.get("severity") or "").lower()
    if name in settings.observability_ignored_alertnames:
        return True
    if severity in settings.observability_ignored_severities:
        return True
    return False


async def aggregate_observability(
    alertmanager_url: Optional[str] = None,
    prometheus_url: Optional[str] = None,
    tempo_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Kumpulkan temuan dari Alertmanager, Prometheus, dan Tempo.
    Fault-tolerant: satu sumber gagal tidak menggagalkan yang lain.
    Alert yang masuk daftar ignore (nama/severity) disaring sebelum dikelompokkan.
    Override URL per-stack (SCALE plan multi-target); None = settings global.
    Return struktur {checked_at, sources, services}.
    """
    results = await _fetch_all_sources(alertmanager_url, prometheus_url, tempo_url)
    filtered_results = {}
    for source_name, alerts in results.items():
        filtered_results[source_name] = [
            a for a in alerts if not _is_ignored_alert(a)
        ]

    services: Dict[str, List[Dict[str, Any]]] = {}
    for source_name, alerts in filtered_results.items():
        for alert in alerts:
            svc = alert.get("service") or "unknown"
            services.setdefault(svc, []).append(alert)

    for svc in services:
        services[svc].sort(key=lambda a: (a.get("severity", "warning"), a.get("name", "")))

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources": filtered_results,
        "services": services,
    }


async def _fetch_all_sources(
    alertmanager_url: Optional[str] = None,
    prometheus_url: Optional[str] = None,
    tempo_url: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Jalankan ketiga sumber secara paralel; setiap kegagalan menghasilkan daftar kosong."""
    alertmanager_task = get_alertmanager_active(alertmanager_url)
    prometheus_task = get_prometheus_firing(prometheus_url)
    tempo_task = get_tempo_5xx(limit=5, tempo_url_override=tempo_url)

    try:
        alertmanager, prometheus, tempo = await asyncio.gather(
            alertmanager_task, prometheus_task, tempo_task,
            return_exceptions=True,
        )
    except Exception as e:  # sangat defensif; gather dengan return_exceptions jarang raise
        logger.error(f"Observability gather failed: {e}")
        alertmanager, prometheus, tempo = [], [], []

    return {
        "alertmanager": alertmanager if isinstance(alertmanager, list) else [],
        "prometheus": prometheus if isinstance(prometheus, list) else [],
        "tempo": tempo if isinstance(tempo, list) else [],
    }


def _stable_alert_identity(alert: Dict[str, Any]) -> str:
    """Identitas STABIL satu alert utk dedup anti-spam (Fix #84).

    Hanya field identitas: source, service, name|trace_id, severity, active_at.
    Field enrichment volatile (span_count/duration_ms/error_spans/services_involved)
    DIKECUALIKAN — bila enrichment `/api/traces` gagal sesaat, payload berubah → jika
    ikut di-hash, fingerprint berubah → alert yang sama di-broadcast ulang tiap poll.
    """
    name = alert.get("name") or alert.get("trace_id") or "alert"
    active = alert.get("active_at") or alert.get("startsAt") or ""
    return "|".join([
        str(alert.get("source") or ""),
        str(alert.get("service") or ""),
        str(name),
        str(alert.get("severity") or ""),
        str(active),
    ])


def build_fingerprint(aggregate: Dict[str, Any]) -> str:
    """MD5 identitas temuan (tanpa checked_at & tanpa enrichment) utk anti-spam per-target."""
    services = aggregate.get("services", {})
    canonical = {svc: sorted(_stable_alert_identity(a) for a in alerts)
                 for svc, alerts in services.items()}
    return hashlib.md5(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()


def build_content_fingerprint(service: str, alerts: List[Dict[str, Any]]) -> str:
    """Fingerprint KONTEN alert utk dedup LINTAS-target (Fix #84).

    Tanpa observ_id — target berbeda yang mendeteksi alert SAMA menghasilkan key yang sama,
    sehingga broadcast/ticket hanya sekali per window. Pakai identitas stabil tiap alert.
    """
    canonical = [service] + sorted(_stable_alert_identity(a) for a in alerts)
    return hashlib.md5("|".join(canonical).encode("utf-8")).hexdigest()
