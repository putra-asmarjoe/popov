"""
Event relay — Fix #107: jembatan event realtime lintas-proses VIA MONGODB.

Masalah: bus realtime (services/event_bus.py) in-process. Koneksi WS browser
terdaftar di proses API (uvicorn), sedangkan tiket/notifikasi yang dibuat
oleh watchdog_worker lahir di proses TERPISAH → emit() ke bus kosong,
event tidak pernah sampai ke browser.

Solusi: worker meng-enable relay di startup; setiap emit() juga ditulis ke
collection kecil `realtime_events` (MongoDB yang sama — tanpa URL/dependency
baru). Proses API menjalankan event tap (services/event_tap.py) yang membaca
doc baru tiap 1 detik dan meneruskannya ke bus proses API.

Fire-and-forget — gagal menulis tidak boleh memengaruhi pembuatan tiket.
"""

import logging
from datetime import datetime, timezone

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

REALTIME_EVENTS_COLLECTION = "realtime_events"

_enabled = False


def enable_event_relay() -> None:
    """Dipanggil SEKALI oleh proses non-API (watchdog_worker) saat startup."""
    global _enabled
    _enabled = True
    logger.info("[event-relay] enabled — emit() akan diteruskan via MongoDB")


def is_enabled() -> bool:
    return _enabled


async def forward_event(channel: str, event: dict) -> None:
    """Tulis event ke realtime_events utk di-tap oleh proses API. Selalu non-fatal."""
    if not channel or not _enabled:
        return
    try:
        await get_db()[REALTIME_EVENTS_COLLECTION].insert_one(
            {
                "channel": channel,
                "event": event,
                "createdAt": datetime.now(timezone.utc),
            }
        )
    except Exception as e:
        logger.warning(f"[event-relay] gagal forward '{channel}' (non-fatal): {e}")
