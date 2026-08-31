"""
Verification Agent — epic Gap 5: Closed-Loop Post-Fix Check.

Saat ticket masuk status `in_progress`/`needs_review`, `change_status` set
`verification_due_at` (delay default 10 menit). Watchdog worker scan ticket
pending + due → re-check error rate (Prometheus) + health (DB service) →
verdict (normal/still_degraded/unknown) → progressLog 🤖 + notifikasi.

Prinsip:
- State di DB → restart-safe, watchdog poll (konsisten auto_feedback).
- Auto Feedback TIDAK disentuh — independen.
- unknown → skip notifikasi (anti-spam).
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config.settings import settings
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

TICKETS_COLLECTION = "tickets"

VERIFY_STATUSES = ("in_progress", "needs_review")

_MSG = {
    "id": {
        "normal": "✅ Kondisi kembali normal setelah fix — {svc} (verifikasi otomatis)",
        "degraded": "⚠️ Masih bermasalah setelah fix — {svc}. Perlu tindak lanjut.",
    },
    "en": {
        "normal": "✅ Conditions back to normal after fix — {svc} (auto verification)",
        "degraded": "⚠️ Still degraded after fix — {svc}. Needs follow-up.",
    },
}


async def _resolve_health_for_service(workspace_id: Optional[str], service: Optional[str]) -> Optional[bool]:
    """Cek health DB service via registry db_config. Return True/False/None (tidak bisa ditentukan)."""
    if not workspace_id or not service:
        return None
    try:
        from services.workspace_service_registry import get_by_service
        reg = await get_by_service(workspace_id, service) or await get_by_service(workspace_id, service.replace("-", "_"))
        db_cfg = (reg or {}).get("db_config")
        if not db_cfg:
            return None
        db_type = (db_cfg.get("type") or "mongodb").lower()
        if db_type == "mysql":
            from services.health_checker import check_mysql_health
            res = await check_mysql_health(
                host=db_cfg.get("host"), port=db_cfg.get("port"),
                user=db_cfg.get("user"), password=db_cfg.get("password"),
                db=db_cfg.get("db"), timeout_seconds=3.0,
            )
        else:
            from services.health_checker import check_mongodb_health
            res = await check_mongodb_health(
                uri=db_cfg.get("uri"), db_name=db_cfg.get("db"), timeout_seconds=3.0,
            )
        return bool(res.get("ok", False))
    except Exception as e:
        logger.warning(f"[Verification] health check failed (non-fatal): {e}")
        return None


async def _verify_ticket(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """Re-check error rate + health untuk satu ticket. Return verdict + note."""
    service = ticket.get("serviceName") or ""
    ws_id = ticket.get("workspaceId")
    project_id = ticket.get("projectId")
    state_like = {"workspace_id": ws_id, "project_id": project_id}

    prom_url = am_url = None
    try:
        from services.observability_store import get_observ_config_for_state
        obs_cfg = await get_observ_config_for_state(state_like)
        prom_url = (obs_cfg or {}).get("prometheus_url")
        am_url = (obs_cfg or {}).get("alertmanager_url")
    except Exception as e:
        logger.warning(f"[Verification] observ config failed (non-fatal): {e}")

    error_ok = None
    if service:
        from services.auto_feedback import _is_error_rate_normal
        error_ok = await _is_error_rate_normal(service, prom_url, am_url)

    health_ok = await _resolve_health_for_service(ws_id, service)

    if error_ok is False or health_ok is False:
        verdict = "still_degraded"
    elif error_ok is True or health_ok is True:
        verdict = "normal"
    else:
        verdict = "unknown"

    note = (
        f"verdict={verdict} error_rate={error_ok} health={health_ok} "
        f"service={service or 'n/a'} at {datetime.now(timezone.utc).isoformat()}"
    )
    return {"verdict": verdict, "note": note, "error_ok": error_ok, "health_ok": health_ok, "service": service}


async def _notify(ticket: Dict[str, Any], verdict: str, service: str) -> None:
    """Kirim notifikasi Telegram (bilingual) — fire-and-forget, unknown → skip."""
    if verdict == "unknown":
        return
    try:
        from services.locale_pref import get_workspace_locale
        from services.notification_store import resolve_channels
        from services.notifier import deliver_alert

        locale = await get_workspace_locale(ticket.get("workspaceId"))
        lang = "id" if locale == "id" else "en"
        key = "normal" if verdict == "normal" else "degraded"
        text = _MSG[lang][key].format(svc=service or ticket.get("ticketNumber"))
        channels = await resolve_channels(ticket.get("workspaceId"), ticket.get("projectId"))
        if channels:
            deliver_alert(channels, text=text, workspace_id=ticket.get("workspaceId"))
    except Exception as e:
        logger.warning(f"[Verification] notify failed (non-fatal): {e}")


async def run_verification_once(batch: int = 20) -> dict:
    """Satu siklus: scan ticket pending + due → re-check → update + progressLog 🤖 + notif."""
    stats = {"checked": 0, "normal": 0, "still_degraded": 0, "unknown": 0, "failed": 0}
    db = get_db()
    coll = db[TICKETS_COLLECTION]
    now = datetime.now(timezone.utc)

    try:
        cursor = coll.find({
            "status": {"$in": list(VERIFY_STATUSES)},
            "verification_status": "pending",
            "verification_due_at": {"$lte": now.isoformat()},
        }).sort("verification_due_at", 1).limit(batch)
        tickets = await cursor.to_list(length=batch)
    except Exception as e:
        logger.warning(f"[Verification] scan failed: {e}")
        return stats

    from services.ticket_store import add_progress_note_watchdog

    for t in tickets:
        try:
            result = await _verify_ticket(t)
            verdict = result["verdict"]
            update = {
                "verification_status": "done",
                "verification_result": verdict,
                "verification_note": result["note"],
                "updatedAt": now.isoformat(),
            }
            await coll.update_one({"_id": t["_id"]}, {"$set": update})
            await add_progress_note_watchdog(
                t, f"🤖 Verifikasi otomatis: {verdict} — {result['note']}"
            )
            await _notify(t, verdict, result["service"])
            stats["checked"] += 1
            stats[verdict] = stats.get(verdict, 0) + 1
            logger.info(
                f"[Verification] ticket={t.get('ticketNumber')} svc={result['service']} "
                f"verdict={verdict} error={result['error_ok']} health={result['health_ok']}"
            )
        except Exception as e:
            logger.warning(f"[Verification] ticket {t.get('_id')} failed: {e}")
            stats["failed"] += 1

    return stats


async def start_verification_loop(interval_sec: int = 60) -> None:
    """Loop watchdog (default 60s scan)."""
    logger.info(f"[Verification] loop started interval={interval_sec}s")
    while True:
        try:
            stats = await run_verification_once()
            if stats["checked"] > 0:
                logger.info(f"[Verification] cycle done {stats}")
        except asyncio.CancelledError:
            logger.info("[Verification] cancelled")
            break
        except Exception as e:
            logger.error(f"[Verification] loop error: {e}")
        await asyncio.sleep(interval_sec)