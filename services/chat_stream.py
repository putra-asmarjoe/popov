"""
Chat stream registry — FE-5 SSE.
Satu asyncio.Queue per session: task pipeline publish event, endpoint stream
membaca dan mem-forward sebagai Server-Sent Events. Queue berfungsi sebagai
buffer bila task mulai sebelum subscriber terhubung.

Sentinel DONE menutup stream dengan data "[DONE]" (kontrak frontend FE-5).
"""
import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DONE = "__done__"
ERROR = "__error__"

_registry: Dict[str, Dict[str, Any]] = {}


def register(session_id: str) -> "asyncio.Queue[str]":
    """Buat antrian baru untuk session (dipanggil saat /send)."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _registry[session_id] = {"queue": queue, "has_reader": False, "loop": loop}
    return queue


def is_active(session_id: str) -> bool:
    return session_id in _registry


def try_set_reader(session_id: str) -> bool:
    """Klaim posisi reader (satu subscriber aktif per session). False bila sudah ada."""
    entry = _registry.get(session_id)
    if entry is None:
        return False
    if entry["has_reader"]:
        return False
    entry["has_reader"] = True
    return True


def release_reader(session_id: str) -> None:
    entry = _registry.get(session_id)
    if entry is not None:
        entry["has_reader"] = False


def publish(session_id: str, event: Dict) -> None:
    """Publish event ke antrian session (fire-and-forget, aman bila tak ada subscriber)."""
    entry = _registry.get(session_id)
    if entry is None:
        return
    import json
    entry["queue"].put_nowait(json.dumps(event, ensure_ascii=False))


def publish_sentinel(session_id: str, sentinel: str) -> None:
    entry = _registry.get(session_id)
    if entry is None:
        return
    entry["queue"].put_nowait(sentinel)


def unregister(session_id: str) -> None:
    _registry.pop(session_id, None)
    logger.info(f"Chat stream unregistered: {session_id}")


def get_queue(session_id: str) -> Optional["asyncio.Queue[str]"]:
    entry = _registry.get(session_id)
    return entry["queue"] if entry is not None else None
