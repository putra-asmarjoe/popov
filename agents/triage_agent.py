"""
Triage Agent — Fase 3 (silent, <30s)
Kumpulkan 4 sinyal: error rate vs baseline + alert aktif + deploy via Loki + Second Brain READ
Output hypothesis prioritas: regression_post_deploy > hpa_maxout > db_connection > downstream_timeout > traffic_spike > unknown
Reuse prometheus_client + second_brain (DRY), degraded gracefully.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from state.schema import AgentState
from config.settings import settings

logger = logging.getLogger(__name__)

# Hypothesis constants
HYPOTHESES = ["regression_post_deploy", "hpa_maxout", "db_connection", "downstream_timeout", "traffic_spike", "unknown"]


async def triage_agent(state: AgentState) -> dict:
    """
    Silent triage. Dipanggil watchdog sebelum fan-out. Tidak kirim Telegram.
    Return triage_result dict + agents_visited.
    Exception safe — selalu return unknown jika gagal.
    """
    service = state.get("service_name") or state.get("preset_service_name") or "unknown"
    agents_visited = ["triage_agent"]
    logger.info(f"TriageAgent start service='{service}'")

    # Kumpulkan 4 sinyal paralel (timeout masing-masing)
    error_rate_now: Optional[float] = None
    baseline_rate: Optional[float] = None
    has_alert: Optional[bool] = None
    deploy_detected: bool = False
    deploy_info: Optional[dict] = None
    second_brain_ctx: Optional[dict] = None

    # Fase D: resolve URL stack per workspace/project (fallback .env global)
    from services.observability_store import get_observ_config_for_state
    obs_cfg = await get_observ_config_for_state(state)
    prom_override = (obs_cfg or {}).get("prometheus_url")
    am_override = (obs_cfg or {}).get("alertmanager_url")
    loki_override = (obs_cfg or {}).get("loki_url")

    async def _fetch_error_rate():
        try:
            from services.prometheus_client import query_prometheus
            # Error rate 5m now
            q_now = 'sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))'
            # Baseline 24h: avg_over_time 1h range? Simplifikasi: query sama tapi fallback None jika tidak ada
            res = await asyncio.wait_for(query_prometheus(q_now, base_url_override=prom_override), timeout=2.0)
            # query_prometheus return raw json; extract value if possible
            if res and isinstance(res, dict):
                # try to parse vector result
                results = res.get("data", {}).get("result", [])
                if results and results[0].get("value"):
                    return float(results[0]["value"][1])
                # fallback: if res is already float-like
            return None
        except Exception as e:
            logger.debug(f"Triage error rate fetch failed: {e}")
            return None

    async def _fetch_alert():
        try:
            from services.prometheus_client import get_active_alerts
            alerts = await asyncio.wait_for(get_active_alerts(service, alertmanager_url_override=am_override, prometheus_url_override=prom_override), timeout=2.0)
            if alerts is None:
                return None
            return len(alerts) > 0
        except Exception as e:
            logger.debug(f"Triage alert fetch failed: {e}")
            return None

    async def _fetch_deploy():
        try:
            from services.deploy_checker import check_deploy_via_loki
            detected, info = await asyncio.wait_for(
                check_deploy_via_loki(service, minutes=60, loki_url_override=loki_override),
                timeout=3.0,
            )
            return detected, info
        except Exception as e:
            logger.debug(f"Triage deploy check failed: {e}")
            return False, None

    async def _fetch_brain():
        try:
            from services.second_brain import read_similar_episodes
            # Build minimal state for brain READ (reuse metrics/mongo summary if available)
            # Saat triage, metrics/mongo belum ada → pakai intent + service saja
            brain_state = {"service_name": service, "intent": state.get("intent", ""), "mongo_summary": "", "metrics_summary": "", "trace_summary": "", "workspace_id": state.get("workspace_id")}
            ctx = await asyncio.wait_for(read_similar_episodes(brain_state, limit=5, days=30), timeout=1.5)
            return ctx
        except Exception as e:
            logger.debug(f"Triage brain read failed: {e}")
            return None

    # Jalankan paralel dengan gather (toleran gagal per sinyal)
    try:
        results = await asyncio.gather(
            _fetch_error_rate(),
            _fetch_alert(),
            _fetch_deploy(),
            _fetch_brain(),
            return_exceptions=True,
        )
        # results[0]=error_rate, [1]=has_alert, [2]=(deploy,info), [3]=brain
        if not isinstance(results[0], Exception):
            error_rate_now = results[0]
        if not isinstance(results[1], Exception):
            has_alert = results[1]
        if not isinstance(results[2], Exception) and isinstance(results[2], tuple):
            deploy_detected, deploy_info = results[2]
        if not isinstance(results[3], Exception):
            second_brain_ctx = results[3]
    except Exception as e:
        logger.warning(f"Triage gather failed: {e}")

    # Tentukan hipotesis prioritas
    hypothesis = "unknown"
    confidence = 0.5
    severity = "low"
    focus_hints: list[str] = []
    skip_hints: list[str] = []

    # Prioritas 1: deploy dalam 60m → regression_post_deploy
    if deploy_detected:
        hypothesis = "regression_post_deploy"
        confidence = 0.82
        severity = "high"
        focus_hints = ["mongo error pattern", "first error trace"]
        skip_hints = ["hpa_metrics"]
    elif has_alert:
        # Cek HPA maxout via metrics: jika alert HPA firing → hpa_maxout
        # Simplifikasi: jika has_alert true, anggap hpa_maxout (akan dikoreksi metrics_agent nanti)
        # Untuk DRY, hpa check sebenarnya di metrics_agent, tapi triage cukup flag
        hypothesis = "hpa_maxout"
        confidence = 0.71
        severity = "high"
        focus_hints = ["hpa_metrics", "traffic spike"]
        skip_hints = ["trace detail"]
    else:
        # Gunakan second brain jika ada pattern
        if second_brain_ctx and second_brain_ctx.get("similar_episodes", 0) >= 5:
            prob = second_brain_ctx.get("probable_cause")
            if prob == "downstream":
                hypothesis = "downstream_timeout"
                confidence = 0.71
                severity = "high"
                focus_hints = ["boundary_traces", "dependency_health"]
                skip_hints = ["cpu_metrics", "memory_metrics"]
            elif prob == "service-fault":
                hypothesis = "db_connection"
                confidence = 0.68
                severity = "high"
                focus_hints = ["db connection", "mongo error"]
                skip_hints = ["prometheus metrics"]
        # Fallback unknown
        if hypothesis == "unknown":
            # Jika error_rate tinggi tapi tidak ada sinyal lain → traffic_spike?
            if error_rate_now is not None and error_rate_now > 0.05:
                hypothesis = "traffic_spike"
                confidence = 0.55
                severity = "medium"
                focus_hints = ["request rate", "latency"]
                skip_hints = ["health check"]
            else:
                hypothesis = "unknown"
                confidence = 0.45
                severity = "medium"
                focus_hints = ["full fan-out"]
                skip_hints = []

    # Severity override via second brain tier
    if second_brain_ctx:
        tier = second_brain_ctx.get("confidence_tier")
        if tier == "FULL":
            confidence = min(0.92, confidence + second_brain_ctx.get("confidence_boost", 0))
        elif tier == "PARTIAL":
            confidence = min(0.85, confidence + second_brain_ctx.get("confidence_boost", 0))

    triage_result = {
        "hypothesis": hypothesis,
        "confidence": round(confidence, 2),
        "severity": severity,
        "proceed_to_stage2": severity in ("high", "medium"),
        "deploy_detected": deploy_detected,
        "deploy_info": deploy_info,
        "focus_hints": focus_hints,
        "skip_hints": skip_hints,
        "second_brain_context": second_brain_ctx,
        "signals": {
            "error_rate_now": error_rate_now,
            "has_alert": has_alert,
            "deploy_detected": deploy_detected,
        },
    }

    logger.info(f"Triage done service='{service}' hypothesis='{hypothesis}' confidence={confidence:.2f} deploy={deploy_detected} alert={has_alert}")

    return {
        "triage_result": triage_result,
        "next_agent": "mongo_agent",
        "agents_visited": agents_visited,
    }
