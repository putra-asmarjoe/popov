"""
Triage Agent — Fase 3 (silent, <30s)
Kumpulkan 4 sinyal: error rate vs baseline + alert aktif + deploy via Loki + Second Brain READ
Output hypothesis prioritas: regression_post_deploy > hpa_maxout > db_connection > downstream_timeout > traffic_spike > unknown
Reuse prometheus_client + second_brain (DRY), degraded gracefully.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from state.schema import AgentState
from config.settings import settings

logger = logging.getLogger(__name__)

# Hypothesis constants
HYPOTHESES = ["regression_post_deploy", "hpa_maxout", "db_connection", "downstream_timeout", "traffic_spike", "unknown"]

# ── GAP-6: konstanta fusi multi-signal (bukan magic numbers inline) ──────────
ERROR_SPIKE_THRESHOLD = 0.05        # reuse dari fallback traffic_spike (line 173 lama)
DEPLOY_CONFIRMATION_BOOST = 0.10    # confidence naik saat error spike konfirmasi
DEPLOY_NO_SPIKE_PENALTY = 0.15      # confidence turun saat tidak ada error spike
DEPLOY_CONF_FLOOR = 0.45            # minimum confidence regression_post_deploy
DEPLOY_CONF_CEILING = 0.95          # maximum confidence (tidak boleh 1.0)
DEPLOY_BASE_CONFIDENCE = 0.82       # base regression_post_deploy (tidak berubah)


def _parse_deployed_at(deploy_info: Optional[dict]):
    """Normalisasi `deployed_at` dari dua sumber deploy signal (GAP-6).

    Sumber tipe tidak konsisten:
    - Loki (`deploy_checker.py:150`): ISO string (`datetime.fromtimestamp(...).isoformat()`)
    - deploy_events fallback (`deploy_event_store.py:106`): datetime object

    Return: datetime UTC aware, atau None bila tidak tersedia / gagal parse.
    TIDAK pernah raise — apapun input, kembalikan None kalau tidak bisa.
    """
    if not isinstance(deploy_info, dict):
        return None
    raw = deploy_info.get("deployed_at")
    if raw is None:
        return None
    try:
        if isinstance(raw, datetime):
            dt = raw
        elif isinstance(raw, (int, float)):
            dt = datetime.fromtimestamp(raw, tz=timezone.utc)
        elif isinstance(raw, str):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _compute_deploy_confidence(minutes_since_deploy: Optional[float]) -> float:
    """Time-decay curve (GAP-6): semakin lama sejak deploy, semakin kecil keyakinan
    error sekarang disebabkan deploy itu. None (unknown timing) → 0.85 conservative.

        minutes_since_deploy  multiplier
        0 – 15 min            1.00
        15 – 30 min           0.90
        30 – 45 min           0.75
        45 – 60 min           0.60
        > 60 min              0.50 (floor)
        None                  0.85
    """
    if minutes_since_deploy is None:
        return 0.85
    if minutes_since_deploy <= 15:
        return 1.00
    if minutes_since_deploy <= 30:
        return 0.90
    if minutes_since_deploy <= 45:
        return 0.75
    if minutes_since_deploy <= 60:
        return 0.60
    return 0.50


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
            # Gap 4: fallback non-K8s — Loki miss → cek deploy_events (sinyal CI/CD, TTL 2 jam)
            if not detected:
                from services.deploy_event_store import check_deploy_recent
                detected, info = await asyncio.wait_for(
                    check_deploy_recent(service, minutes=60),
                    timeout=2.0,
                )
                if detected and info:
                    info = {**info, "source": "deploy_events_fallback"}
                    logger.info(f"[Triage] deploy detected via deploy_events_fallback svc={service} version={info.get('version')}")
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
    verification_note = None
    minutes_since_deploy = None

    # Prioritas 1: deploy dalam 60m → regression_post_deploy
    # GAP-6: fusi multi-signal — time-decay (deployed_at) + error spike modifier.
    # Koreksi deep check: skip_hints=["hpa_metrics"] DIHAPUS di jalur fusi — kalau
    # tetap ada, planner `_apply_skip_hints` (TERAKHIR) membuang metrics yang baru
    # saja di-ADD oleh focus_hints → verifikasi error spike gagal total.
    if deploy_detected:
        deployed_at = _parse_deployed_at(deploy_info)
        if deployed_at is not None:
            minutes_since_deploy = (datetime.now(timezone.utc) - deployed_at).total_seconds() / 60
        base_conf = DEPLOY_BASE_CONFIDENCE * _compute_deploy_confidence(minutes_since_deploy)
        if error_rate_now is not None and error_rate_now > ERROR_SPIKE_THRESHOLD:
            # Error spike KONFIRMASI deploy hypothesis — tetap verifikasi penuh (metrics+trace)
            confidence = min(DEPLOY_CONF_CEILING, base_conf + DEPLOY_CONFIRMATION_BOOST)
            focus_hints = ["verify_error_rate", "check_metrics", "check_trace"]
            verification_note = "deploy_and_error_spike_confirmed"
        elif error_rate_now is not None and error_rate_now <= ERROR_SPIKE_THRESHOLD:
            # Deploy ada TAPI error rate normal — possible false positive
            confidence = max(DEPLOY_CONF_FLOOR, base_conf - DEPLOY_NO_SPIKE_PENALTY)
            focus_hints = ["verify_error_rate", "check_metrics"]
            verification_note = "deploy_detected_but_no_error_spike"
        else:
            # error_rate_now = None (Prometheus down / no data) — conservative
            confidence = base_conf
            focus_hints = ["verify_error_rate"]
            verification_note = "error_rate_unavailable"
        hypothesis = "regression_post_deploy"
        severity = "high"
        skip_hints = []
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
        # GAP-6: field baru utk audit/transparency
        "verification_note": verification_note,
        "minutes_since_deploy": round(minutes_since_deploy, 1) if minutes_since_deploy is not None else None,
        "signals": {
            "error_rate_now": error_rate_now,
            "has_alert": has_alert,
            "deploy_detected": deploy_detected,
        },
    }

    logger.info(f"Triage done service='{service}' hypothesis='{hypothesis}' confidence={confidence:.2f} deploy={deploy_detected} alert={has_alert}")

    # Gap 3 Fase 5: lookup service_type dari registry (Opsi A — triage async, planner tetap sync)
    service_type = None
    try:
        from services.workspace_service_registry import get_by_service
        svc = state.get("service_name") or service
        ws_id = state.get("workspace_id")
        if ws_id and svc:
            reg = await get_by_service(ws_id, svc) or await get_by_service(ws_id, svc.replace("-", "_"))
            if reg:
                service_type = reg.get("service_type") or None
    except Exception as e:
        logger.warning(f"Triage service_type lookup failed (non-fatal): {e}")

    return {
        "triage_result": triage_result,
        "next_agent": "mongo_agent",
        "service_type": service_type,
        "agents_visited": agents_visited,
    }
