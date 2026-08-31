"""
Notifier — dispatch pengiriman alert multi-channel (telegram + email), FIRE-AND-FORGET.

`deliver_alert(...)` spawn `asyncio.create_task` dan return None segera — proses
pengiriman TIDAK menunggu return (pola `event_bus.emit` / `second_brain`).
Task di-track dgn done_callback utk log error tak ter-handle.

Per channel dispatch:
- channel == "telegram" → `telegram_client.broadcast([ch], text, reply_markup=...)`
- channel == "email"   → `email_client.send_email(cfg, subject, text, html)`

Setiap attempt dicatat ke `notification_delivery_logs` (detail ringkas, bukan isi pesan).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_alert_subject(service: str, alert_name: str, locale: str = "en") -> str:
    """Subject default alert — bilingual. Fallback: [ALERT] {service}: {alert_name}."""
    name = alert_name or "alert"
    if locale == "id":
        return f"[ALERT] {service}: {name}"
    return f"[ALERT] {service}: {name}"


async def _deliver_alert_async(
    channels: List[dict],
    text: str,
    html: Optional[str] = None,
    subject: Optional[str] = None,
    telegram_reply_markup: Optional[dict] = None,
    alert_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> None:
    """Kirim ke semua channel match (1 pass), catat delivery log per attempt."""
    from services.email_client import broadcast_email
    from services.notification_delivery_logs import log_broadcast_report
    from services.telegram_client import broadcast as telegram_broadcast

    reports: List[Dict[str, Any]] = []
    tg_channels = [c for c in channels if c.get("channel") == "telegram"]
    em_channels = [c for c in channels if c.get("channel") == "email"]

    if tg_channels:
        try:
            sent = await telegram_broadcast(tg_channels, text, reply_markup=telegram_reply_markup)
            for ch in tg_channels:
                reports.append({
                    "notif_id": ch.get("notif_id"),
                    "name": ch.get("name"),
                    "channel": "telegram",
                    "target": ((ch.get("config") or {}).get("telegram") or {}).get("chat_id") or "",
                    "ok": sent > 0,
                    "detail": f"telegram_sent:{sent}/{len(tg_channels)}",
                })
        except Exception as e:
            logger.error(f"[Notifier] telegram broadcast gagal: {e}")
            reports.append({
                "notif_id": None, "name": None, "channel": "telegram",
                "target": "", "ok": False, "detail": f"error:{str(e)[:200]}",
            })

    if em_channels:
        try:
            em_reports = await broadcast_email(em_channels, subject or "", text, html)
            reports.extend(em_reports)
        except Exception as e:
            logger.error(f"[Notifier] email broadcast gagal: {e}")
            reports.append({
                "notif_id": None, "name": None, "channel": "email",
                "target": "", "ok": False, "detail": f"error:{str(e)[:200]}",
            })

    if reports:
        await log_broadcast_report(workspace_id, reports, alert_id=alert_id)
    # Log ringkas per-attempt ke app.log (debug "alert fire tapi tidak sampai").
    for r in reports:
        logger.info(
            f"[Notifier] delivery channel={r.get('channel')} "
            f"notif={r.get('notif_id')} target={r.get('target') or '-'} "
            f"ok={r.get('ok')} detail={r.get('detail') or '-'} "
            f"alert={alert_id or '-'}"
        )
    logger.info(f"[Notifier] deliver_alert: {len(reports)} attempt ({workspace_id or 'global'})")


def deliver_alert(
    channels: List[dict],
    text: str,
    html: Optional[str] = None,
    subject: Optional[str] = None,
    telegram_reply_markup: Optional[dict] = None,
    alert_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> None:
    """FIRE-AND-FORGET: spawn task pengiriman, return None segera.
    Tidak menunggu SMTP/Telegram — watchdog tidak terblokir."""
    if not channels:
        logger.warning("[Notifier] deliver_alert: 0 channel — tidak ada yang dikirim")
        return
    try:
        task = asyncio.create_task(
            _deliver_alert_async(
                channels=channels,
                text=text,
                html=html,
                subject=subject,
                telegram_reply_markup=telegram_reply_markup,
                alert_id=alert_id,
                workspace_id=workspace_id,
            ),
            name=f"deliver-alert-{alert_id or 'anon'}",
        )
        task.add_done_callback(_on_delivery_done)
    except RuntimeError:
        # Tidak ada event loop (sync context) — jalankan inline agar tidak hilang
        logger.warning("[Notifier] no event loop — fallback inline (blocking)")
        asyncio.run(
            _deliver_alert_async(
                channels=channels,
                text=text,
                html=html,
                subject=subject,
                telegram_reply_markup=telegram_reply_markup,
                alert_id=alert_id,
                workspace_id=workspace_id,
            )
        )


def _on_delivery_done(task: asyncio.Task) -> None:
    try:
        task.result()  # re-raise exception kalau ada
    except asyncio.CancelledError:
        logger.warning("[Notifier] deliver task cancelled")
    except Exception as e:
        logger.error(f"[Notifier] deliver task error: {e}")


__all__ = ["deliver_alert", "build_alert_subject"]
