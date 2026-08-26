"""
Watchdog Worker — SCALE_ESCALATION_PLAN Layer 1 (B2)

A separate process from the FastAPI web server. Run it with:

    python watchdog_worker.py

This process is a SINGLETON — exactly one instance must run at all times
(see deploy/watchdog-deployment.yaml: replicas: 1, Recreate strategy).

Responsibilities:
1. WatchdogScheduler.run_forever()   — hybrid polling/push observability checks
                                       across multiple targets (master tick every 30s)
2. start_auto_feedback_loop(300s)    — Phase 2B Auto Feedback loop
                                       (moved out of the FastAPI lifespan)

FastAPI (main.py) no longer runs either of these loops, so API pods can be
scaled out safely without duplicating observability polling.
"""
import asyncio
import logging
from contextlib import AsyncExitStack

from config.settings import settings
from services.mongodb_client import close as close_mongo
from services.request_log import ensure_indexes
from services.observability_watchdog import get_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("watchdog_worker")


async def main() -> None:
    logger.info("[WatchdogWorker] starting dedicated watchdog process")

    # Fix #107: proses ini TIDAK memegang koneksi WS browser — enable relay agar
    # event tiket/notifikasi yang lahir di sini diteruskan ke bus proses API.
    from services.event_relay import enable_event_relay
    enable_event_relay()

    # Ensure indexes exist (idempotent) before the scheduler starts writing alerts
    try:
        await ensure_indexes()
    except Exception as e:
        logger.warning(f"[WatchdogWorker] ensure_indexes failed (non-fatal): {e}")

    # ticket_alerts indexes (1 ticket : N alerts, auto-ticket dedup window).
    # This worker is what writes those alerts, so the indexes must exist in this process too.
    try:
        from services.ticket_alert_store import ensure_ticket_alert_indexes
        await ensure_ticket_alert_indexes()
    except Exception as e:
        logger.warning(f"[WatchdogWorker] ticket_alert indexes failed (non-fatal): {e}")

    # Fix #54: BYOK LLM — load config from the DB into the factory cache
    # (this process is separate from the API). Watchdog alert formatting does NOT use
    # an LLM (template-based), but if an LLM path is ever added here, the config must be
    # available — no fallback to settings, since the env-based keys have been removed.
    try:
        from services.llm_factory import load_llm_config_from_db
        await load_llm_config_from_db()
        logger.info("[WatchdogWorker] LLM config loaded from DB (BYOK)")
    except Exception as e:
        logger.warning(f"[WatchdogWorker] failed to load LLM config (non-fatal): {e}")

    # Fix #54: warm the grounding docs cache (agent_docs) — if this process ever needs
    # service docs, it won't have to hit the DB at runtime.
    try:
        from services.doc_loader import load_all_docs
        await load_all_docs()
    except Exception as e:
        logger.warning(f"[WatchdogWorker] doc loader warm-up failed (non-fatal): {e}")

    stack = AsyncExitStack()
    tasks = []

    # 1. Watchdog scheduler (master tick every 30s → per-target due check)
    scheduler = get_scheduler()
    tasks.append(asyncio.create_task(scheduler.run_forever(), name="watchdog-scheduler"))

    # 2. Auto Feedback loop (Phase 2B) — moved out of the FastAPI lifespan
    try:
        from services.auto_feedback import start_auto_feedback_loop
        tasks.append(asyncio.create_task(start_auto_feedback_loop(interval_sec=300), name="auto-feedback"))
        logger.info("[WatchdogWorker] auto-feedback loop started")
    except Exception as e:
        logger.warning(f"[WatchdogWorker] auto_feedback not started: {e}")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_mongo()
        await stack.aclose()
        logger.info("[WatchdogWorker] stopped cleanly")


if __name__ == "__main__":
    logger.info(f"[WatchdogWorker] observability_enabled={settings.observability_enabled}")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass