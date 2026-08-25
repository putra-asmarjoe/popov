"""
Knowledge store — FE-7 Knowledge Workspace + Library Pribadi.
Collections (popovagent_db):
- knowledge_library:        konten single-source milik satu user (ownerId).
- workspace_knowledge_refs: link workspace → item library (konten TIDAK disalin).

Kepemilikan ketat: hanya owner yang boleh mutasi library; ws-admin + owner
yang boleh membuat link; member workspace boleh membaca lewat link.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

LIBRARY_COLLECTION = "knowledge_library"
REFS_COLLECTION = "workspace_knowledge_refs"

ALLOWED_FOLDERS = ("general", "services", "playbooks", "schemas", "connections", "observability")
MAX_CONTENT_BYTES = 200_000
MIN_CONTENT_CHARS = 50
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,63}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_name(filename_or_title: str) -> str:
    stem = filename_or_title.strip().lower()
    stem = re.sub(r"\.md$", "", stem)
    stem = re.sub(r"[^a-z0-9_\-]+", "-", stem).strip("-")
    return stem


def validate_content(content: str) -> str:
    """Validasi konten markdown (reuse aturan ingest lama): UTF-8 text, ≤200KB, min 50 char."""
    data = content.encode("utf-8", errors="replace")
    if len(data) > MAX_CONTENT_BYTES:
        raise ValueError("Konten terlalu besar (maks 200KB)")
    text = content.strip()
    if len(text) < MIN_CONTENT_CHARS:
        raise ValueError(f"Dokumen terlalu pendek (minimal {MIN_CONTENT_CHARS} karakter)")
    return content


async def ensure_knowledge_indexes() -> None:
    db = get_db()
    await db[LIBRARY_COLLECTION].create_index([("ownerId", 1), ("updatedAt", -1)])
    await db[LIBRARY_COLLECTION].create_index(
        [("ownerId", 1), ("folder", 1), ("name", 1)], unique=True
    )
    await db[REFS_COLLECTION].create_index(
        [("workspaceId", 1), ("libraryId", 1)], unique=True
    )
    await db[REFS_COLLECTION].create_index("libraryId")
    logger.info("Knowledge indexes ensured")


# ── Serialisasi ───────────────────────────────────────────────────────────────

def _public_item(doc: Dict[str, Any], include_content: bool = False, usage_count: int = 0) -> Dict[str, Any]:
    out = {
        "id": str(doc["_id"]),
        "ownerId": doc.get("ownerId", ""),
        "name": doc.get("name", ""),
        "folder": doc.get("folder", "general"),
        "sizeBytes": len((doc.get("content") or "").encode("utf-8")),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "usageCount": usage_count,
    }
    if include_content:
        out["content"] = doc.get("content", "")
    return out


def _public_ref(doc: Dict[str, Any], item: Optional[Dict[str, Any]], ws_name: str = "") -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "workspaceId": doc.get("workspaceId", ""),
        "workspaceName": ws_name,
        "libraryId": doc.get("libraryId", ""),
        "name": (item or {}).get("name", "?"),
        "folder": (item or {}).get("folder", "?"),
        "updatedAt": (item or {}).get("updatedAt"),
        "addedBy": doc.get("addedBy", ""),
        "addedAt": doc.get("addedAt"),
    }


# ── Library (milik owner tunggal) ─────────────────────────────────────────────

async def create_item(owner_id: str, name: str, folder: str, content: str) -> Dict[str, Any]:
    name = slugify_name(name)
    if not NAME_RE.match(name):
        raise ValueError("Nama tidak valid (huruf kecil/angka/-/_ , 2-64 karakter)")
    if folder not in ALLOWED_FOLDERS:
        raise ValueError(f"Folder harus salah satu dari {ALLOWED_FOLDERS}")
    content = validate_content(content)

    doc = {
        "ownerId": owner_id,
        "name": name,
        "folder": folder,
        "content": content,
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
    }
    db = get_db()
    result = await db[LIBRARY_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    logger.info(f"Knowledge item created '{folder}/{name}' by {owner_id}")
    return doc


async def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    try:
        oid = ObjectId(item_id)
    except Exception:
        return None
    return await get_db()[LIBRARY_COLLECTION].find_one({"_id": oid})


async def list_items_for_owner(owner_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = db[LIBRARY_COLLECTION].find({"ownerId": owner_id}).sort("updatedAt", -1)
    items = [doc async for doc in cursor]
    counts = await _usage_counts([str(i["_id"]) for i in items])
    return [_public_item(i, usage_count=counts.get(str(i["_id"]), 0)) for i in items]


async def update_item(item_id: str, owner_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update nama/folder/konten. HANYA owner (dipaksa di sini, bukan cuma di router)."""
    doc = await get_item(item_id)
    if doc is None or doc.get("ownerId") != owner_id:
        return None
    set_fields: Dict[str, Any] = {"updatedAt": _now_iso()}
    if "name" in updates and updates["name"] is not None:
        name = slugify_name(updates["name"])
        if not NAME_RE.match(name):
            raise ValueError("Nama tidak valid")
        set_fields["name"] = name
    if "folder" in updates and updates["folder"] is not None:
        if updates["folder"] not in ALLOWED_FOLDERS:
            raise ValueError("Folder tidak valid")
        set_fields["folder"] = updates["folder"]
    if "content" in updates and updates["content"] is not None:
        set_fields["content"] = validate_content(updates["content"])
    db = get_db()
    await db[LIBRARY_COLLECTION].update_one({"_id": doc["_id"]}, {"$set": set_fields})
    return await get_item(item_id)


async def list_usage(item_id: str) -> List[Dict[str, Any]]:
    """Workspace pemakai sebuah item library (untuk warning cascade delete)."""
    db = get_db()
    refs = [doc async for doc in db[REFS_COLLECTION].find({"libraryId": item_id})]
    if not refs:
        return []
    ws_oids = []
    for r in refs:
        try:
            ws_oids.append(ObjectId(r["workspaceId"]))
        except Exception:
            continue
    ws_docs = await db["workspaces"].find({"_id": {"$in": ws_oids}}, {"name": 1}).to_list(len(ws_oids))
    name_by_id = {str(w["_id"]): w.get("name", "?") for w in ws_docs}
    return [
        {"workspaceId": r["workspaceId"], "name": name_by_id.get(r["workspaceId"], "?")}
        for r in refs
    ]


async def delete_item(item_id: str, owner_id: str) -> bool:
    """Hapus item library + semua referensi workspace (cascade — WAJIB lewat confirm UI)."""
    doc = await get_item(item_id)
    if doc is None or doc.get("ownerId") != owner_id:
        return False
    db = get_db()
    removed_refs = await db[REFS_COLLECTION].delete_many({"libraryId": item_id})
    await db[LIBRARY_COLLECTION].delete_one({"_id": doc["_id"]})
    from services.workspace_knowledge import invalidate_cache
    invalidate_cache()
    logger.info(f"Knowledge item deleted '{doc.get('name')}' by {owner_id} (refs removed: {removed_refs.deleted_count})")
    return True


async def _usage_counts(item_ids: List[str]) -> Dict[str, int]:
    if not item_ids:
        return {}
    db = get_db()
    counts: Dict[str, int] = {i: 0 for i in item_ids}
    async for row in db[REFS_COLLECTION].aggregate([
        {"$match": {"libraryId": {"$in": item_ids}}},
        {"$group": {"_id": "$libraryId", "n": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = row["n"]
    return counts


# ── Referensi workspace ───────────────────────────────────────────────────────

async def add_ref(ws_id: str, library_id: str, user_id: str) -> Dict[str, Any]:
    db = get_db()
    try:
        result = await db[REFS_COLLECTION].insert_one({
            "workspaceId": ws_id,
            "libraryId": library_id,
            "addedBy": user_id,
            "createdAt": _now_iso(),
        })
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise ValueError("Knowledge ini sudah ter-link ke workspace")
        raise
    from services.workspace_knowledge import invalidate_cache
    invalidate_cache()
    doc = await db[REFS_COLLECTION].find_one({"_id": result.inserted_id})
    return doc


async def list_refs_for_workspace(ws_id: str) -> List[Dict[str, Any]]:
    """Daftar referensi workspace, join metadata library (TANPA konten)."""
    db = get_db()
    refs = [doc async for doc in db[REFS_COLLECTION].find({"workspaceId": ws_id}).sort("createdAt", 1)]
    if not refs:
        return []
    lib_oids = []
    for r in refs:
        try:
            lib_oids.append(ObjectId(r["libraryId"]))
        except Exception:
            continue
    items = await db[LIBRARY_COLLECTION].find({"_id": {"$in": lib_oids}}).to_list(len(lib_oids))
    item_by_id = {str(i["_id"]): i for i in items}
    return [_public_ref(r, item_by_id.get(r["libraryId"])) for r in refs]


async def get_ref_with_content(ws_id: str, ref_id: str) -> Optional[Dict[str, Any]]:
    """Satu referensi + konten library (untuk preview oleh member workspace)."""
    db = get_db()
    try:
        rid = ObjectId(ref_id)
    except Exception:
        return None
    ref = await db[REFS_COLLECTION].find_one({"_id": rid, "workspaceId": ws_id})
    if ref is None:
        return None
    item = await get_item(ref.get("libraryId", ""))
    if item is None:
        return None
    out = _public_ref(ref, item)
    out["content"] = item.get("content", "")
    return out


async def remove_ref(ws_id: str, ref_id: str) -> bool:
    db = get_db()
    try:
        rid = ObjectId(ref_id)
    except Exception:
        return False
    result = await db[REFS_COLLECTION].delete_one({"_id": rid, "workspaceId": ws_id})
    if result.deleted_count:
        from services.workspace_knowledge import invalidate_cache
        invalidate_cache()
        return True
    return False
