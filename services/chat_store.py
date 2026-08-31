"""
Chat store — FE-5 Chat AI.
Collections: chat_sessions, chat_messages (db popovagent_db).
Session milik satu user; opsional terikat project/tiket (konteks).

Fix #118: sesi chat project mendukung soft-delete (deletedAt + deletedBy) —
pola mengikuti FE-8.4 projects. Sesi terikat tiket (ticketId) tidak melalui
jalur ini; endpoint API menolak delete sesi tiket (arsip komunikasi tiket).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

SESSIONS_COLLECTION = "chat_sessions"
MESSAGES_COLLECTION = "chat_messages"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_session(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "userId": doc.get("userId", ""),
        "projectId": doc.get("projectId"),
        "ticketId": doc.get("ticketId"),
        "title": doc.get("title", ""),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "deletedAt": doc.get("deletedAt"),
    }


def _public_message(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "sessionId": doc.get("sessionId", ""),
        "role": doc.get("role", "user"),
        "content": doc.get("content", ""),
        "meta": doc.get("meta"),
        "createdAt": doc.get("createdAt"),
    }


async def ensure_chat_indexes() -> None:
    """Index chat: (userId, deletedAt, updatedAt) + (sessionId, deletedAt, createdAt).
    Index baru menggantikan index lama agar filter `deletedAt: None` (sesi aktif)
    berjalan optimal baik untuk list maupun get-by-id.
    """
    db = get_db()
    try:
        await db[SESSIONS_COLLECTION].drop_index("userId_1_updatedAt_-1")
    except Exception:
        # Index belum ada atau nama berbeda — abaikan
        pass
    await db[SESSIONS_COLLECTION].create_index(
        [("userId", 1), ("deletedAt", 1), ("updatedAt", -1)]
    )
    try:
        await db[MESSAGES_COLLECTION].drop_index("sessionId_1_createdAt_1")
    except Exception:
        pass
    await db[MESSAGES_COLLECTION].create_index(
        [("sessionId", 1), ("deletedAt", 1), ("createdAt", 1)]
    )
    logger.info("Chat indexes ensured")


async def create_session(
    user_id: str, project_id: Optional[str] = None, ticket_id: Optional[str] = None, title: str = ""
) -> Dict[str, Any]:
    doc = {
        "userId": user_id,
        "projectId": project_id,
        "ticketId": ticket_id,
        "title": title or "Chat baru",
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
    }
    db = get_db()
    result = await db[SESSIONS_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Ambil sesi AKTIF saja (deletedAt: None). Soft-deleted = 404 untuk caller."""
    try:
        oid = ObjectId(session_id)
    except Exception:
        return None
    return await get_db()[SESSIONS_COLLECTION].find_one({"_id": oid, "deletedAt": None})


async def list_sessions(user_id: str, project_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """List sesi AKTIF user (filter deletedAt). Sesi arsip tak muncul di UI."""
    query: Dict[str, Any] = {"userId": user_id, "deletedAt": None}
    if project_id:
        query["projectId"] = project_id
    db = get_db()
    cursor = db[SESSIONS_COLLECTION].find(query).sort("updatedAt", -1).limit(limit)
    return [doc async for doc in cursor]


async def add_message(
    session_id: str, role: str, content: str, meta: Optional[Dict] = None
) -> Dict[str, Any]:
    """Tambah pesan ke sesi. Sesi HARUS aktif — soft-deleted menolak pesan baru."""
    now = _now_iso()
    doc = {
        "sessionId": session_id,
        "role": role,  # user | assistant
        "content": content,
        "meta": meta or {},
        "createdAt": now,
    }
    db = get_db()
    # Defensive: tolak persist bila sesi ter-soft-delete (konsisten dgn _owned_session)
    try:
        oid = ObjectId(session_id)
    except Exception:
        raise ValueError(f"Invalid session_id: {session_id!r}")
    session = await db[SESSIONS_COLLECTION].find_one({"_id": oid, "deletedAt": None}, {"_id": 1})
    if session is None:
        raise ValueError(f"Session {session_id} not found or archived")
    result = await db[MESSAGES_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    # touch session
    await db[SESSIONS_COLLECTION].update_one({"_id": oid}, {"$set": {"updatedAt": now}})
    return doc


async def get_messages(session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Pesan AKTIF saja (filter deletedAt) — cascade soft-delete pesan tersembunyi."""
    db = get_db()
    cursor = (
        db[MESSAGES_COLLECTION]
        .find({"sessionId": session_id, "deletedAt": None})
        .sort("createdAt", 1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def update_session_title(session_id: str, title: str) -> Optional[Dict[str, Any]]:
    """Update session title (owner only)."""
    try:
        oid = ObjectId(session_id)
    except Exception:
        return None
    db = get_db()
    now = _now_iso()
    updated = await db[SESSIONS_COLLECTION].find_one_and_update(
        {"_id": oid, "deletedAt": None},
        {"$set": {"title": title.strip(), "updatedAt": now}},
        return_document=True,
    )
    if updated is None:
        return None
    return {
        "id": str(updated["_id"]),
        "userId": updated.get("userId", ""),
        "projectId": updated.get("projectId"),
        "ticketId": updated.get("ticketId"),
        "title": updated.get("title", ""),
        "createdAt": updated.get("createdAt"),
        "updatedAt": updated.get("updatedAt"),
        "deletedAt": updated.get("deletedAt"),
    }


async def soft_delete_session(session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fix #118: soft-delete sesi chat project (owner only).

    Idempotent + race-safe: hanya mark bila `deletedAt: None`. Cascade set
    flag `deletedAt` ke semua pesan milik sesi agar history lenyap dari
    endpoint. Data tetap utuh di DB untuk pemulihan manual (operator via Mongo).

    Return dict {deleted, archivedAt, messagesArchived, title} atau None bila
    sesi tidak ditemukan / sudah arsip.
    """
    try:
        oid = ObjectId(session_id)
    except Exception:
        return None
    db = get_db()
    # Validasi sesi ada & aktif
    existing = await db[SESSIONS_COLLECTION].find_one({"_id": oid, "deletedAt": None})
    if existing is None:
        return None
    now = _now_iso()
    # Race-safe update: hanya set bila deletedAt masih None
    updated = await db[SESSIONS_COLLECTION].find_one_and_update(
        {"_id": oid, "deletedAt": None},
        {"$set": {"deletedAt": now, "deletedBy": user_id}},
        return_document=True,
    )
    if updated is None:
        return None
    # Cascade: tandai semua pesan aktif sebagai arsip (best-effort, non-fatal)
    cascade = await db[MESSAGES_COLLECTION].update_many(
        {"sessionId": session_id, "deletedAt": None},
        {"$set": {"deletedAt": now}},
    )
    logger.info(
        f"Chat session soft-deleted: id={session_id} by={user_id} "
        f"messages_archived={cascade.modified_count}"
    )
    return {
        "deleted": session_id,
        "archivedAt": now,
        "messagesArchived": cascade.modified_count,
        "title": updated.get("title", ""),
    }
