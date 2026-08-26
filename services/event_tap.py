"""
Event tap — sisi API dari relay realtime (Fix #107).

Proses watchdog menulis event ke collection `realtime_events` (via
services/event_relay.py). Task ini berjalan di proses API: poll doc baru
(setiap 1 detik, cursor `_id` monotonic), publish ke bus in-process sehingga
sampai ke koneksi WS browser, lalu hapus doc yang sudah diproses.

Catatan operasional:
- Polling 1s dipilih di atas Mongo change stream karena tidak mewajibkan
  replica set (jalan di standalone mongod lokal maupun Atlas).
- Aman utk topologi saat ini (API 1 instance — lihat constraint singleton);
  multi-replica API akan double-deliver (invalidate ganda = harmless, tapi
  tetap disiplin singleton).
- Event yang terkirim saat API mati tetap tersampai saat restart (replay) —
  invalidate ganda di FE bersifat harmless.
"""

import asyncio
import logging

from services.event_bus import bus
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

REALTIME_EVENTS_COLLECTION = "realtime_events"
POLL_INTERVAL_SEC = 1.0


async def _tap_once(last_id) -> object:
    """Baca & publish doc baru sejak last_id. Return last_id terbaru."""
    db = get_db()
    query = {"_id": {"$gt": last_id}} if last_id is not None else {}
    docs = (
        await db[REALTIME_EVENTS_COLLECTION]
        .find(query)
        .sort("_id", 1)
        .to_list(length=200)
    )
    for doc in docs:
        last_id = doc["_id"]
        channel = doc.get("channel")
        event = doc.get("event")
        if channel and isinstance(event, dict):
            await bus.publish(str(channel), event)
    if docs:
        # Hapus yang sudah diproses (batch) — jaga koleksi tetap kecil.
        await db[REALTIME_EVENTS_COLLECTION].delete_many(
            {"_id": {"$lte": last_id}}
        )
    return last_id


async def run_event_tap() -> None:
    """Loop tap — dijalankan sebagai task lifespan proses API."""
    last_id = None
    logger.info("[event-tap] started — polling realtime_events setiap 1s")
    while True:
        try:
            last_id = await _tap_once(last_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[event-tap] poll gagal (retry {POLL_INTERVAL_SEC}s): {e}")
        await asyncio.sleep(POLL_INTERVAL_SEC)


def start_event_tap() -> asyncio.Task:
    return asyncio.create_task(run_event_tap(), name="event-tap")
