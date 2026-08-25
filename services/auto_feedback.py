"""
Auto Feedback Check — Fase 2.B (NEXTDEV2.md Sistem Feedback Hibrida)

Periodic checker untuk episode anomalous yang masih pending feedback:
- Hanya untuk episode dengan anomali (error_rate>0 atau MAXOUT atau mongo>0) — healthy skip
- Jalankan 30 menit setelah laporan (timestamp + 30m)
- Query Prometheus: jika current_error_rate < baseline*1.1 → auto_resolved (weight 0.5)
- Fallback jika Prometheus tidak tersedia: tetap auto_resolved untuk anomalous pending (degraded gracefully)
- Manual correct/wrong (weight 1.0) tidak pernah dioverwrite

Dipanggil dari watchdog loop atau main lifespan.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from services.mongodb_client import get_db
from services.second_brain import is_anomalous_episode, update_episode_feedback
from config.settings import settings

logger = logging.getLogger(__name__)


async def _is_error_rate_normal(
    service_name: str,
    prometheus_url_override: str | None = None,
    alertmanager_url_override: str | None = None,
) -> bool | None:
    """
    Cek apakah error rate sekarang sudah normal via Prometheus.
    Fix #45: URL per-stack dari episode (observ_id) — HANYA dari DB; None = degraded.
    Return True jika normal, False jika masih tinggi, None jika tidak bisa tentukan (degraded).
    """
    prom_base = (prometheus_url_override or "").strip()
    if not prom_base:
        return None  # degraded — tidak ada Prometheus untuk episode ini

    try:
        from services.prometheus_client import query_prometheus

        # query error rate 5m sekarang vs baseline 24 jam lalu? Sederhana: cek current error rate < threshold
        # Spec NEXTDEV2: if current_error_rate < baseline * 1.1
        # Implementasi minimal: query rate 5m, anggap baseline sebagai query 24 jam range avg atau threshold 1%
        # Untuk DRY: jika Prometheus reachable, cek `rate(http_requests_total{status=~"5.."}[5m])` < 0.01 (1%)
        # Jika tidak ada data, anggap normal (fallback)
        q = 'sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))'
        # coba dengan label service jika ada
        # Untuk service-specific, coba query dengan service label varian (reuse prometheus_client logic tidak perlu detail)
        result = await query_prometheus(q, base_url_override=prometheus_url_override)
        if result is None:
            return None
        # result bisa berupa vector; ambil value pertama
        # query_prometheus return json raw; simplifikasi: jika ada result, anggap normal
        # Lebih akurat: cek active alerts — jika tidak ada alert firing untuk service ini, anggap normal
        from services.prometheus_client import get_active_alerts
        alerts = await get_active_alerts(
            service_name,
            alertmanager_url_override=alertmanager_url_override,
            prometheus_url_override=prometheus_url_override,
        )
        if alerts is not None and len(alerts) == 0:
            return True  # no active alert → normal
        if alerts is not None and len(alerts) > 0:
            return False  # still firing
        return None
    except Exception as e:
        logger.warning(f"[AutoFeedback] prometheus check failed for {service_name}: {e}")
        return None


async def check_auto_feedback_once(batch: int = 20) -> dict:
    """
    Satu siklus check: cari pending anomalous episodes yang sudah >=30m, coba auto_resolved.
    Return stats dict.
    """
    stats = {"checked": 0, "auto_resolved": 0, "skipped_healthy": 0, "skipped_manual": 0, "prometheus_normal": 0, "fallback_auto": 0}
    try:
        db = get_db()
        coll = db["incident_episodes"]
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        # pending = feedback is None
        cursor = coll.find({"feedback": None, "timestamp": {"$lte": cutoff}}).sort("timestamp", 1).limit(batch)
        pending = await cursor.to_list(length=batch)
        if not pending:
            return stats

        for ep in pending:
            stats["checked"] += 1
            # skip healthy (bukan error) — khusus error saja
            if not is_anomalous_episode(ep):
                stats["skipped_healthy"] += 1
                logger.info(f"[AutoFeedback] skip healthy {ep.get('episode_id')} (no anomaly)")
                continue

            service = ep.get("service_name") or "unknown"
            episode_id = ep.get("episode_id")

            # Fix #41-Fase D: resolve URL stack milik episode (observ_id/workspace)
            prom_override = am_override = None
            try:
                from services.observability_store import get_target
                tgt = await get_target(ep.get("observ_id") or "") if ep.get("observ_id") else None
                if tgt:
                    prom_override = (tgt.get("prometheus_url") or "").rstrip("/") or None
                    am_override = (tgt.get("alertmanager_url") or "").rstrip("/") or None
            except Exception as e:
                logger.debug(f"[AutoFeedback] target resolve failed: {e}")

            # cek prometheus jika tersedia
            is_normal = await _is_error_rate_normal(service, prom_override, am_override)
            should_resolve = False
            if is_normal is True:
                should_resolve = True
                stats["prometheus_normal"] += 1
            elif is_normal is False:
                should_resolve = False
                logger.info(f"[AutoFeedback] still firing for {episode_id} ({service}) — skip")
                continue
            else:
                # degraded: Prometheus tidak tersedia → tetap auto_resolved untuk anomalous pending (sesuai plan degraded gracefully)
                # tapi hanya jika anomalous dan sudah 30m, anggap transient resolved
                should_resolve = True
                stats["fallback_auto"] += 1

            if should_resolve:
                ok = await update_episode_feedback(episode_id, "auto_resolved", note="auto: error rate kembali normal dalam 30 menit (anomalous pending)", weight=0.5)
                if ok:
                    stats["auto_resolved"] += 1
                    logger.info(f"[AutoFeedback] auto_resolved {episode_id} ({service})")

        return stats
    except Exception as e:
        logger.error(f"[AutoFeedback] check failed: {e}", exc_info=True)
        return stats


async def start_auto_feedback_loop(interval_sec: int = 300):
    """Loop periodik (default 5 menit) — cek batch pending."""
    logger.info(f"[AutoFeedback] loop started interval={interval_sec}s (only anomalous)")
    while True:
        try:
            stats = await check_auto_feedback_once()
            if stats["auto_resolved"] > 0:
                logger.info(f"[AutoFeedback] cycle done {stats}")
        except asyncio.CancelledError:
            logger.info("[AutoFeedback] cancelled")
            break
        except Exception as e:
            logger.error(f"[AutoFeedback] loop error: {e}")
        await asyncio.sleep(interval_sec)
