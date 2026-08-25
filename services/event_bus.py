"""
Event bus in-process — FE-4 Realtime.
Channel-based pub/sub WebSocket: {"channel": set[WebSocket]}.
Channel: "project:{projectId}" untuk event tiket, "user:{userId}" untuk notifikasi.
Satu container — tanpa Redis (keep it small).
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectionManager:
    def __init__(self) -> None:
        self._channels: Dict[str, Set[WebSocket]] = {}

    def connect(self, channel: str, websocket: WebSocket) -> None:
        """Daftarkan koneksi ke channel (accept dilakukan SEKALI oleh pemanggil)."""
        self._channels.setdefault(channel, set()).add(websocket)
        logger.info(f"WS connect: {channel} (total {len(self._channels[channel])})")

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        conns = self._channels.get(channel)
        if conns:
            conns.discard(websocket)
            if not conns:
                self._channels.pop(channel, None)
            logger.info(f"WS disconnect: {channel}")

    async def publish(self, channel: str, event: Dict) -> None:
        """Kirim event JSON ke semua koneksi channel; buang koneksi mati."""
        conns = self._channels.get(channel)
        if not conns:
            return
        event = {"at": _now_iso(), **event}
        dead = []
        for ws in list(conns):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(channel, ws)


bus = ConnectionManager()


def emit(channel: str, event: Dict) -> None:
    """Publish fire-and-forget — tidak boleh menggantung caller (store/route)."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(bus.publish(channel, event))
    except RuntimeError:
        # tidak ada event loop (mis. sync context) — lewati
        pass
