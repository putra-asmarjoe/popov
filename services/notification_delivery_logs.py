"""
Notification Delivery Logs — catatan ringkas pengiriman alert per channel (debug).

Field `detail` RINGKAS (status SMTP/HTTP/error), BUKAN isi pesan penuh.
Dipakai debugging "alert fire tapi tidak sampai" tanpa buka log aplikasi.
Collection: `notification_delivery_logs` — index (at desc), (workspace_id, at desc).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

COLLECTION = "notification_delivery_logs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_delivery_log_indexes() -> None:
    try:
        coll = get_db()[COLLECTION]
        await coll.create_index([("at", -1)])
        await coll.create_index([("workspace_id", 1), ("at", -1)])
        logger.info(f"Indexes ensured on '{COLLECTION}'")
    except Exception as e:
        logger.warning(f"Failed to ensure {COLLECTION} indexes: {e}")


async def log_delivery(entry: Dict[str, Any]) -> None:
    """Simpan satu attempt pengiriman. `detail` ringkas — bukan isi pesan."""
    doc = {
        "at": entry.get("at") or _now_iso(),
        "workspace_id": entry.get("workspace_id") or None,
        "notif_id": entry.get("notif_id") or None,
        "name": entry.get("name") or "",
        "channel": entry.get("channel") or "",
        "target": entry.get("target") or "",
        "ok": bool(entry.get("ok")),
        "detail": (entry.get("detail") or "")[:500],
        "alert_id": entry.get("alert_id") or None,
    }
    try:
        await get_db()[COLLECTION].insert_one(doc)
    except Exception as e:
        logger.warning(f"[delivery-log] insert failed: {e}")


async def list_delivery_logs(
    workspace_id: Optional[str] = None,
    since_hours: float = 24.0,
    limit: int = 50,
) -> List[dict]:
    """Log pengiriman terbaru (read-only, utk debug FE/ops). Urut terbaru dulu."""
    import time

    cutoff = datetime.now(timezone.utc).timestamp() - since_hours * 3600
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    q: Dict[str, Any] = {"at": {"$gte": cutoff_iso}}
    if workspace_id:
        q["workspace_id"] = workspace_id
    try:
        coll = get_db()[COLLECTION]
        cursor = coll.find(q).sort("at", -1).limit(limit)
        out = []
        async for d in cursor:
            d["_id"] = str(d["_id"])
            out.append(d)
        return out
    except Exception as e:
        logger.warning(f"[delivery-log] list failed: {e}")
        return []


# ── Combo: log hasil broadcast telegram + email dalam satu fire ──────────────

async def log_broadcast_report(
    workspace_id: Optional[str],
    reports: List[Dict[str, Any]],
    alert_id: Optional[str] = None,
) -> None:
    """Catat delivery-report (list dari telegram/email broadcast) ke log."""
    for r in reports:
        await log_delivery({
            "workspace_id": workspace_id,
            "notif_id": r.get("notif_id"),
            "name": r.get("name"),
            "channel": r.get("channel"),
            "target": r.get("target"),
            "ok": r.get("ok"),
            "detail": r.get("detail"),
            "alert_id": alert_id,
        })


# Re-export
__all__ = [
    "log_delivery",
    "list_delivery_logs",
    "log_broadcast_report",
    "ensure_delivery_log_indexes",
]
