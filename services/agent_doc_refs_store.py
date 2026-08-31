"""
Agent Doc Refs Store — reference/pointer dari workspace ke grounding docs (agent_docs).

Collection (popovagent_db):
- agent_doc_refs: {workspaceId, docCategory, docKey, addedBy, createdAt}

Sifat:
- Read-only reference: isi doc tetap di agent_docs, tidak disalin.
- CRUD hanya admin workspace.
- Dipakai build_workspace_context() untuk inject grounding docs ke agent prompt.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

COLLECTION = "agent_doc_refs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes() -> None:
    db = get_db()
    await db[COLLECTION].create_index(
        [("workspaceId", 1), ("docCategory", 1), ("docKey", 1)], unique=True
    )
    await db[COLLECTION].create_index("workspaceId")
    logger.info("Agent doc refs indexes ensured")


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def add_ref(ws_id: str, doc_category: str, doc_key: str, user_id: str) -> Dict[str, Any]:
    """Link agent_doc ke workspace. Raise ValueError bila duplikat."""
    db = get_db()
    try:
        result = await db[COLLECTION].insert_one({
            "workspaceId": ws_id,
            "docCategory": doc_category,
            "docKey": doc_key,
            "addedBy": user_id,
            "createdAt": _now_iso(),
        })
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise ValueError("Grounding doc sudah ter-link ke workspace ini")
        raise
    from services.workspace_knowledge import invalidate_cache
    invalidate_cache()
    doc = await db[COLLECTION].find_one({"_id": result.inserted_id})
    return doc


async def remove_ref(ws_id: str, ref_id: str) -> bool:
    """Hapus satu ref. Return True bila ditemukan + dihapus."""
    db = get_db()
    try:
        rid = ObjectId(ref_id)
    except Exception:
        return False
    result = await db[COLLECTION].delete_one({"_id": rid, "workspaceId": ws_id})
    if result.deleted_count:
        from services.workspace_knowledge import invalidate_cache
        invalidate_cache()
        return True
    return False


async def list_refs_for_workspace(ws_id: str) -> List[Dict[str, Any]]:
    """Daftar semua agent_doc refs untuk workspace (tanpa body doc)."""
    db = get_db()
    cursor = db[COLLECTION].find({"workspaceId": ws_id}).sort("createdAt", 1)
    refs = []
    async for doc in cursor:
        refs.append({
            "id": str(doc["_id"]),
            "workspaceId": doc.get("workspaceId", ""),
            "docCategory": doc.get("docCategory", ""),
            "docKey": doc.get("docKey", ""),
            "addedBy": doc.get("addedBy", ""),
            "createdAt": doc.get("createdAt", ""),
        })
    return refs


async def list_refs_as_keys(ws_id: str) -> List[Dict[str, str]]:
    """Return list of {docCategory, docKey} — dipakai build_workspace_context."""
    db = get_db()
    cursor = db[COLLECTION].find(
        {"workspaceId": ws_id}, {"_id": 0, "docCategory": 1, "docKey": 1}
    )
    return [doc async for doc in cursor]


async def remove_all_for_workspace(ws_id: str) -> int:
    """Hapus semua refs untuk workspace (cascade delete). Return jumlah yang dihapus."""
    db = get_db()
    result = await db[COLLECTION].delete_many({"workspaceId": ws_id})
    if result.deleted_count:
        from services.workspace_knowledge import invalidate_cache
        invalidate_cache()
    return result.deleted_count


async def count_for_doc(doc_category: str, doc_key: str) -> int:
    """Hitung berapa workspace yang me-link agent_doc ini."""
    db = get_db()
    return await db[COLLECTION].count_documents({
        "docCategory": doc_category,
        "docKey": doc_key,
    })
