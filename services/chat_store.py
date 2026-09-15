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


async def get_conversation_state(session_id: str) -> dict:
    """CHAT3 §5.3 (P2, D-P2.11) — baca `conversation_state` dari doc chat_sessions.

    Contract: SELALU return dict ({} bila tidak ada/invalid/DB error) — TIDAK
    pernah raise. Caller (chat_agent / response_agent) menganggap ini non-fatal.
    `_public_session` sengaja TIDAK diperluas (FE P2 tidak butuh — pill datang
    via message meta; D-P2.11 debt).
    """
    try:
        oid = ObjectId(session_id)
    except Exception:
        return {}
    try:
        doc = await get_db()[SESSIONS_COLLECTION].find_one(
            {"_id": oid}, {"conversation_state": 1}
        )
        cs = (doc or {}).get("conversation_state")
        return dict(cs) if isinstance(cs, dict) else {}
    except Exception as e:
        logger.warning(f"[ChatStore] get_conversation_state failed: {e}")
        return {}

async def update_conversation_state(
    session_id: str,
    *,
    topic_context: Optional[Dict[str, Any]] = None,
    investigation_context: Optional[Dict[str, Any]] = None,
    current_intent: Optional[str] = None,
    reset_investigation: bool = False,
    conversation_summary: Optional[str] = None,  # CHAT3 P3B (D-P3.2)
    turn_count: Optional[int] = None,  # CHAT3 P3B (D-P3.2)
    session_tool_count: Optional[int] = None,  # CHAT3 P4 (C3)
    last_tool_used: Optional[str] = None,  # CHAT6 P6.3 (chip context)
) -> bool:
    """CHAT3 §5.3 (P2, D-P2.11) — tulis sub-block `conversation_state` ($set).

    Doc shape (satu objek, tiga bagian + P3B summary — Rev 5 + D-P3.2):
        conversation_state {
          updated_at,
          current_intent,
          topic_context         {active_service, ticket_id, current_topic, updated_at},
          investigation_context {last_findings, last_root_cause, updated_at},
          conversation_summary  str (EN-canonical, cap 800),
          turn_count            int (default 0, increment tiap turn chat_agent),
          session_tool_count    int (default 0, cumulative tool calls chat_agent P4),
          last_tool_used        str (CHAT6 P6.3 — tool read-only terakhir chat_agent),
        }

    - HANYA sub-block yang diberikan yang ditimpa (dotted-path $set — sub-block
      producer lain tidak hilang; investigation_context ditulis response_agent,
      topic_context/current_intent ditulis chat_agent end-of-turn).
    - reset_investigation=True = TOPIC SHIFT first-class (CHAT3 §5.3):
      investigation_context DI-RESET ({} bila caller tidak memberi yang baru) —
      stale last_findings TIDAK boleh lolos ke topic baru (bug paling berbahaya,
      test §5.6.5).
    - Return True bila update terkirim; False bila session_id invalid/DB gagal
      (non-fatal — caller log, delivery tidak pernah tergantung ini).
    """
    try:
        oid = ObjectId(session_id)
    except Exception:
        return False
    now = _now_iso()
    set_fields: Dict[str, Any] = {"conversation_state.updated_at": now}
    if topic_context is not None:
        set_fields["conversation_state.topic_context"] = topic_context
    if investigation_context is not None:
        set_fields["conversation_state.investigation_context"] = investigation_context
    if reset_investigation:
        # Topic shift: re-anchor investigation_context (reset atau replace).
        set_fields["conversation_state.investigation_context"] = investigation_context or {}
    if current_intent is not None:
        set_fields["conversation_state.current_intent"] = current_intent
    if conversation_summary is not None:
        # CHAT3 P3B (D-P3.2): rolling summary — top-level sibling (bukan sub-doc).
        set_fields["conversation_state.conversation_summary"] = conversation_summary
    if turn_count is not None:
        # CHAT3 P3B (D-P3.2): increment TIAP turn (termasuk non-summary turn)
        # agar gating % N tetap benar; int() guard — non-int diabaikan.
        try:
            set_fields["conversation_state.turn_count"] = int(turn_count)
        except (TypeError, ValueError):
            pass
    if session_tool_count is not None:
        # CHAT3 P4 (C3): cumulative session tool budget — int() guard.
        try:
            set_fields["conversation_state.session_tool_count"] = int(session_tool_count)
        except (TypeError, ValueError):
            pass
    if last_tool_used is not None:
        # CHAT6 P6.3: nama tool read-only terakhir yang dieksekusi chat_agent —
        # konteks chip follow-up (offer_planner context mapping).
        _ltu = str(last_tool_used).strip()
        if _ltu:
            set_fields["conversation_state.last_tool_used"] = _ltu
    try:
        await get_db()[SESSIONS_COLLECTION].update_one({"_id": oid}, {"$set": set_fields})
        return True
    except Exception as e:
        logger.warning(f"[ChatStore] update_conversation_state failed: {e}")
        return False

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
