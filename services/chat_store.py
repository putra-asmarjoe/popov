"""
Chat store — FE-5 Chat AI.
Collections: chat_sessions, chat_messages (db popovagent_db).
Session milik satu user; opsional terikat project/tiket (konteks).
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
    db = get_db()
    await db[SESSIONS_COLLECTION].create_index([("userId", 1), ("updatedAt", -1)])
    await db[MESSAGES_COLLECTION].create_index([("sessionId", 1), ("createdAt", 1)])
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
    try:
        oid = ObjectId(session_id)
    except Exception:
        return None
    return await get_db()[SESSIONS_COLLECTION].find_one({"_id": oid})


async def list_sessions(user_id: str, project_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"userId": user_id}
    if project_id:
        query["projectId"] = project_id
    db = get_db()
    cursor = db[SESSIONS_COLLECTION].find(query).sort("updatedAt", -1).limit(limit)
    return [doc async for doc in cursor]


async def add_message(
    session_id: str, role: str, content: str, meta: Optional[Dict] = None
) -> Dict[str, Any]:
    now = _now_iso()
    doc = {
        "sessionId": session_id,
        "role": role,  # user | assistant
        "content": content,
        "meta": meta or {},
        "createdAt": now,
    }
    db = get_db()
    result = await db[MESSAGES_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    # touch session
    await db[SESSIONS_COLLECTION].update_one({"_id": ObjectId(session_id)}, {"$set": {"updatedAt": now}})
    return doc


async def get_messages(session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = db[MESSAGES_COLLECTION].find({"sessionId": session_id}).sort("createdAt", 1).limit(limit)
    return [doc async for doc in cursor]
