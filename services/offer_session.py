"""
Offer Session — tawaran aksi lanjutan dari agent ke user (web chat + Telegram).

Generalisasi pola diagnostic_session: selain menyimpan "pertanyaan berstatus",
offer menyimpan AKSI yang akan dieksekusi saat user setuju.

Status machine:
  active          → user ditawari aksi (accept / decline)
  awaiting_param  → accept tapi butuh 1 parameter lagi (mis. isi catatan progress)
  accepted        → (transisi) siap dieksekusi
  executed        → sudah dijalankan ticket_agent / pipeline
  cancelled       → user menolak

Kunci:
  web chat      → session_id (sender.session_id)
  telegram      → (chat_id, notif_id)
TTL pendek (10 menit) via index expireAfterSeconds:0.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

COLLECTION = "chat_offers"
TTL_MINUTES = 10

ACTIVE_STATUSES = ("active", "awaiting_param")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_offer_indexes() -> None:
    db = get_db()
    coll = db[COLLECTION]
    await coll.create_index("offer_id", unique=True)
    await coll.create_index([("session_id", 1), ("status", 1), ("created_at", -1)])
    await coll.create_index([("chat_id", 1), ("notif_id", 1), ("status", 1), ("created_at", -1)])
    await coll.create_index([("expires_at", 1)], expireAfterSeconds=0)


async def create_offer(
    *,
    type_: str,
    params: dict,
    question: str,
    needs_param: str | None = None,
    session_id: str | None = None,
    chat_id: str | None = None,
    notif_id: str | None = None,
    ticket_id: str | None = None,
) -> str | None:
    """Buat tawaran baru. Return offer_id atau None (non-fatal)."""
    # ganti offer aktif lama utk key yang sama (jangan menumpuk)
    try:
        db = get_db()
        coll = db[COLLECTION]
        q: dict = {"status": {"$in": list(ACTIVE_STATUSES)}}
        if session_id:
            q["session_id"] = session_id
        elif chat_id:
            q["chat_id"] = str(chat_id)
            if notif_id:
                q["notif_id"] = str(notif_id)
        await coll.update_many(q, {"$set": {"status": "cancelled"}})
    except Exception as e:
        logger.warning(f"[Offer] cancel-old failed: {e}")

    offer_id = uuid.uuid4().hex[:12]
    now = _now()
    doc = {
        "offer_id": offer_id,
        "type": type_,
        "params": params,
        "question": question,
        "needs_param": needs_param,
        "session_id": session_id,
        "chat_id": str(chat_id) if chat_id else None,
        "notif_id": str(notif_id) if notif_id else None,
        "ticket_id": ticket_id,
        "status": "active",
        "created_at": now,
        "expires_at": now + timedelta(minutes=TTL_MINUTES),
    }
    try:
        await db[COLLECTION].insert_one(doc)
        logger.info(f"[Offer] created {offer_id} type={type_} key=session:{session_id}/chat:{chat_id}")
        return offer_id
    except Exception as e:
        logger.warning(f"[Offer] create failed: {e}")
        return None


async def get_active_offer(
    session_id: str | None = None,
    chat_id: str | None = None,
    notif_id: str | None = None,
) -> dict | None:
    """Ambil offer aktif/awaiting terbaru untuk key."""
    try:
        db = get_db()
        now = _now()
        q: dict = {"status": {"$in": list(ACTIVE_STATUSES)}, "expires_at": {"$gt": now}}
        if session_id:
            q["session_id"] = session_id
        elif chat_id:
            q["chat_id"] = str(chat_id)
            if notif_id:
                q["notif_id"] = str(notif_id)
        doc = await db[COLLECTION].find_one(q, sort=[("created_at", -1)])
        if doc:
            doc["_id"] = str(doc["_id"])
            return doc
    except Exception as e:
        logger.warning(f"[Offer] get_active failed: {e}")
    return None


async def has_offer_type(session_id: str, type_: str) -> bool:
    """True bila pernah ada offer tipe tertentu utk sesi ini (status bukan cancelled).
    Dipakai response_agent utk anti-reoffer investigasi (Fix #189) — tawarkan
    "investigate lebih dalam" maksimal sekali per sesi agar tidak loop "ya"."""
    try:
        db = get_db()
        doc = await db[COLLECTION].find_one(
            {
                "session_id": session_id,
                "type": type_,
                "status": {"$ne": "cancelled"},
            },
            projection={"_id": 1},
        )
        return doc is not None
    except Exception as e:
        logger.warning(f"[Offer] has_offer_type({session_id},{type_}) failed: {e}")
        return False


async def set_offer_status(offer_id: str, status: str) -> None:
    try:
        await get_db()[COLLECTION].update_one({"offer_id": offer_id}, {"$set": {"status": status}})
    except Exception as e:
        logger.warning(f"[Offer] set_status({offer_id},{status}) failed: {e}")


async def get_offer(offer_id: str) -> dict | None:
    try:
        doc = await get_db()[COLLECTION].find_one({"offer_id": offer_id})
        if doc:
            doc["_id"] = str(doc["_id"])
            return doc
    except Exception as e:
        logger.warning(f"[Offer] get_offer({offer_id}) failed: {e}")
    return None


async def accept_offer(offer_id: str) -> None:
    await set_offer_status(offer_id, "accepted")


async def cancel_offer(offer_id: str) -> None:
    await set_offer_status(offer_id, "cancelled")


async def set_awaiting(offer_id: str, awaiting_field: str) -> None:
    """Transisi active → awaiting_param, catat field yang ditunggu."""
    try:
        await get_db()[COLLECTION].update_one(
            {"offer_id": offer_id}, {"$set": {"status": "awaiting_param", "awaiting_field": awaiting_field}}
        )
    except Exception as e:
        logger.warning(f"[Offer] set_awaiting({offer_id}) failed: {e}")


async def expire_old_offers() -> None:
    try:
        res = await get_db()[COLLECTION].delete_many({"expires_at": {"$lt": _now()}})
        if res.deleted_count:
            logger.info(f"[Offer] expired {res.deleted_count}")
    except Exception as e:
        logger.warning(f"[Offer] expire failed: {e}")
