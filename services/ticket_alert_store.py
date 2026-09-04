"""
Ticket alert store — pemisahan Alert dari Tiket.

Model: 1 tiket : N alert notifikasi.
- Alert PERTAMA dengan konten tertentu (contentFp) memicu tiket baru (status "new")
  + 1 dokumen alert ter-link.
- Alert BERIKUTNYA dengan konten sama dalam window dedup (TICKET_ALERT_DEDUP_HOURS)
  TIDAK membuat tiket lagi — disimpan sebagai dokumen alert ter-link ke tiket lama.

Collection: ticket_alerts (db popovagent_db). Field camelCase mengikuti konvensi tickets.
Counter tiket (alertsCount/lastAlertAt) diupdate via ticket_store.attach_alert_to_ticket.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

TICKET_ALERTS_COLLECTION = "ticket_alerts"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_alert(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "alertId": doc.get("alertId", ""),
        "ticketId": doc.get("ticketId", ""),
        "workspaceId": doc.get("workspaceId", ""),
        "projectId": doc.get("projectId", ""),
        "observId": doc.get("observId"),
        "serviceName": doc.get("serviceName", ""),
        "name": doc.get("name", ""),
        "severity": doc.get("severity", "warning"),
        "source": doc.get("source", "watchdog"),
        "traceIds": doc.get("traceIds", []),
        "occurredAt": doc.get("occurredAt"),
        "createdAt": doc.get("createdAt"),
    }


async def ensure_ticket_alert_indexes() -> None:
    db = get_db()
    coll = db[TICKET_ALERTS_COLLECTION]
    # lookup alert per tiket (detail tiket + FE list)
    await coll.create_index([("ticketId", 1), ("occurredAt", -1)])
    # dedup window per project + konten
    await coll.create_index([("projectId", 1), ("contentFp", 1), ("occurredAt", -1)])
    # alert feed per project (overview card) — query sort occurredAt desc
    await coll.create_index([("projectId", 1), ("occurredAt", -1)])
    logger.info("Ticket alert indexes ensured")


async def record_ticket_alert(
    *,
    ticket: Dict[str, Any],
    service: str,
    name: str,
    severity: str,
    trace_ids: Optional[List[str]] = None,
    content_fp: Optional[str] = None,
    workspace_id: Optional[str] = None,
    observ_id: Optional[str] = None,
    source: str = "watchdog",
    note: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Simpan dokumen alert ter-link ke tiket + update counter tiket.

    note: bila diisi → entry ProgressLog di tiket (untuk alert ke-2 dst.;
    alert pertama cukup initial_note tiket). Total alert di-append otomatis
    DARI HASIL inkrement (bukan bacaan awal — aman utk alert paralel).
    Gagal simpan TIDAK melempar — watchdog harus tetap jalan. Return doc alert atau None.
    """
    now = _now_iso()
    doc = {
        "alertId": f"alt-{uuid.uuid4().hex[:8]}",
        "ticketId": str(ticket["_id"]),
        "workspaceId": str(workspace_id or ticket.get("workspaceId", "") or ""),
        "projectId": str(ticket.get("projectId", "")),
        "observId": observ_id or None,
        "serviceName": service,
        "contentFp": content_fp,
        "name": name,
        "severity": severity,
        "source": source or "watchdog",
        "traceIds": [t for t in (trace_ids or []) if t],
        "occurredAt": now,
        "createdAt": now,
    }
    try:
        await get_db()[TICKET_ALERTS_COLLECTION].insert_one(doc)
    except Exception as e:
        logger.error(f"[ticket-alert] gagal simpan alert utk tiket {doc['ticketId']}: {e}")
        return None

    try:
        from services.ticket_store import attach_alert_to_ticket

        updated = await attach_alert_to_ticket(ticket)
        # catat jumlah FINAL di progress log (post-increment, anti race paralel)
        if note and updated is not None:
            from services.ticket_store import add_progress_note_watchdog

            await add_progress_note_watchdog(
                updated,
                f"{note} — total {int(updated.get('alertsCount') or 1)} alerts",
            )
    except Exception as e:
        logger.warning(f"[ticket-alert] counter tiket {doc['ticketId']} gagal diupdate: {e}")
    return doc


async def list_alerts_for_ticket(ticket_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Daftar alert ter-link ke tiket, terbaru dulu."""
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        return []
    cursor = (
        get_db()[TICKET_ALERTS_COLLECTION]
        .find({"ticketId": str(oid)})
        .sort("occurredAt", -1)
        .limit(max(1, min(limit, 500)))
    )
    return [doc async for doc in cursor]


async def list_alerts_for_project(project_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Daftar alert ter-link ke tiket milik project (overview alert feed).

    Sumber kebenaran card alert = ticket_alerts (alert yang TERTIKET-kan), BUKAN
    watchdog_alerts (broadcast log tanpa project_id). ticket_alerts membawa
    projectId+ticketId eksplisit → scoping per project tanpa join observ_id dan
    tanpa fallback workspace-wide (yang bocor lintas project saat project tanpa stack).
    """
    try:
        oid = ObjectId(str(project_id))
    except Exception:
        return []
    cursor = (
        get_db()[TICKET_ALERTS_COLLECTION]
        .find({"projectId": str(oid)})
        .sort("occurredAt", -1)
        .limit(max(1, min(limit, 100)))
    )
    return [doc async for doc in cursor]


async def count_alerts(ticket_id: str) -> int:
    return await get_db()[TICKET_ALERTS_COLLECTION].count_documents({"ticketId": str(ticket_id)})
