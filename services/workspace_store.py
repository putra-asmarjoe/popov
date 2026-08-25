"""
Workspace & project store — FE-2.
Collections: workspaces, projects (db popovagent_db).

- workspaces: {_id, name, slug, ownerId, members: [{userId, role, joinedAt}], createdAt}
- projects:   {_id, workspaceId, name, slug, key, ticketCounter, createdBy, createdAt}
  (key 2-5 huruf → nomor tiket "BUG-42" di FE-3; ticketCounter di-[$inc] FE-3)
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

WORKSPACES_COLLECTION = "workspaces"
PROJECTS_COLLECTION = "projects"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Project key: 2-5 karakter, huruf besar di depan (mis. BUG, CORE, POP2)
KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,4}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(name: str, fallback: str = "item") -> str:
    slug = _SLUG_RE.sub("-", (name or "").lower()).strip("-")
    return slug or fallback


def valid_project_key(key: str) -> bool:
    return bool(KEY_RE.match((key or "").strip().upper()))


async def ensure_workspace_indexes() -> None:
    db = get_db()
    await db[WORKSPACES_COLLECTION].create_index("slug", unique=True)
    await db[PROJECTS_COLLECTION].create_index([("workspaceId", 1), ("slug", 1)], unique=True)
    await db[PROJECTS_COLLECTION].create_index([("workspaceId", 1), ("key", 1)], unique=True)
    logger.info("Workspace indexes ensured (workspaces.slug, projects.workspaceId+slug/key unique)")


# ── Serialisasi ───────────────────────────────────────────────────────────────

def public_workspace(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "slug": doc.get("slug", ""),
        "ownerId": str(doc.get("ownerId", "")),
        "memberCount": len(doc.get("members", [])),
        "createdAt": doc.get("createdAt"),
    }


def public_project(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "workspaceId": str(doc.get("workspaceId", "")),
        "name": doc.get("name", ""),
        "slug": doc.get("slug", ""),
        "key": doc.get("key", ""),
        "createdBy": str(doc.get("createdBy", "")),
        "createdAt": doc.get("createdAt"),
    }


# ── Workspace ─────────────────────────────────────────────────────────────────

async def _unique_slug(base_slug: str, collection: str, extra_query: Optional[dict] = None) -> str:
    """Slug unik dengan suffix -2, -3, … (cek existing di collection)."""
    db = get_db()
    slug = base_slug
    n = 2
    while True:
        query = {"slug": slug}
        if extra_query:
            query.update(extra_query)
        if await db[collection].find_one(query, {"_id": 1}) is None:
            return slug
        slug = f"{base_slug}-{n}"
        n += 1


async def create_workspace(name: str, owner: Dict[str, Any]) -> Dict[str, Any]:
    """Buat workspace; creator otomatis member role=admin."""
    name = (name or "").strip()
    if len(name) < 2:
        raise ValueError("Nama workspace minimal 2 karakter")

    owner_id = str(owner["_id"])
    slug = await _unique_slug(slugify(name, fallback="workspace"), WORKSPACES_COLLECTION)
    doc = {
        "name": name,
        "slug": slug,
        "ownerId": owner_id,
        "members": [{"userId": owner_id, "role": "admin", "joinedAt": _now_iso()}],
        "createdAt": _now_iso(),
    }
    db = get_db()
    result = await db[WORKSPACES_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    logger.info(f"Workspace created: {name} ({slug}) by {owner.get('email')}")
    return doc


async def list_workspaces_for_user(user_id: str) -> List[Dict[str, Any]]:
    """Workspace tempat user adalah member (urut terlama dulu — stabil untuk redirect)."""
    db = get_db()
    cursor = db[WORKSPACES_COLLECTION].find({"members.userId": user_id}).sort("createdAt", 1)
    return [doc async for doc in cursor]


async def find_workspace_by_id(ws_id: str) -> Optional[Dict[str, Any]]:
    try:
        oid = ObjectId(ws_id)
    except Exception:
        return None
    return await get_db()[WORKSPACES_COLLECTION].find_one({"_id": oid})


def get_membership(ws: Dict[str, Any], user_id: str) -> Optional[Dict[str, Any]]:
    for m in ws.get("members", []):
        if m.get("userId") == user_id:
            return m
    return None


def is_workspace_admin(ws: Dict[str, Any], user_id: str) -> bool:
    if str(ws.get("ownerId", "")) == user_id:
        return True
    m = get_membership(ws, user_id)
    return bool(m and m.get("role") == "admin")


async def add_member(ws_id: str, user_id_to_add: str, role: str = "member") -> None:
    """Tambah member. Bila sudah member → update role saja (idempotent)."""
    if role not in ("admin", "member"):
        raise ValueError("Role harus admin atau member")
    ws = await find_workspace_by_id(ws_id)
    if ws is None:
        raise ValueError("Workspace tidak ditemukan")
    db = get_db()
    if get_membership(ws, user_id_to_add):
        await db[WORKSPACES_COLLECTION].update_one(
            {"_id": ws["_id"], "members.userId": user_id_to_add},
            {"$set": {"members.$.role": role}},
        )
    else:
        await db[WORKSPACES_COLLECTION].update_one(
            {"_id": ws["_id"]},
            {"$push": {"members": {"userId": user_id_to_add, "role": role, "joinedAt": _now_iso()}}},
        )


async def remove_member(ws_id: str, user_id_to_remove: str) -> None:
    db = get_db()
    await db[WORKSPACES_COLLECTION].update_one(
        {"_id": ObjectId(ws_id)},
        {"$pull": {"members": {"userId": user_id_to_remove}}},
    )


# ── Project ───────────────────────────────────────────────────────────────────

async def create_project(ws_id: str, name: str, key: str, user_id: str) -> Dict[str, Any]:
    name = (name or "").strip()
    key = (key or "").strip().upper()
    if len(name) < 2:
        raise ValueError("Nama project minimal 2 karakter")
    if not valid_project_key(key):
        raise ValueError("Key project 2-5 karakter huruf besar (contoh: BUG, CORE)")

    slug = await _unique_slug(
        slugify(name, fallback="project"), PROJECTS_COLLECTION, extra_query={"workspaceId": ws_id}
    )
    doc = {
        "workspaceId": ws_id,
        "name": name,
        "slug": slug,
        "key": key,
        "ticketCounter": 0,
        "createdBy": user_id,
        "createdAt": _now_iso(),
    }
    db = get_db()
    try:
        result = await db[PROJECTS_COLLECTION].insert_one(doc)
    except DuplicateKeyError:
        raise ValueError(f"Key '{key}' sudah dipakai project lain di workspace ini")
    doc["_id"] = result.inserted_id
    logger.info(f"Project created: {name} ({key}) in workspace {ws_id}")
    return doc


async def list_projects(ws_id: str) -> List[Dict[str, Any]]:
    """Project AKTIF saja (soft-deleted disembunyikan)."""
    db = get_db()
    cursor = db[PROJECTS_COLLECTION].find(
        {"workspaceId": ws_id, "deletedAt": None}
    ).sort("createdAt", 1)
    return [doc async for doc in cursor]


async def find_project_by_id(project_id: str) -> Optional[Dict[str, Any]]:
    """Hanya project aktif — soft-deleted dianggap tidak ada (guard semua API)."""
    try:
        oid = ObjectId(project_id)
    except Exception:
        return None
    return await get_db()[PROJECTS_COLLECTION].find_one({"_id": oid, "deletedAt": None})


async def soft_delete_project(project_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Soft-delete: set flag + rename slug/key agar bisa dipakai project baru.

    Tiket/chat/request-log TIDAK disentuh (ikut terarsip). Return doc ter-update.
    """
    doc = await get_db()[PROJECTS_COLLECTION].find_one({
        "_id": _oid_safe(project_id), "deletedAt": None,
    })
    if doc is None:
        return None
    suffix = str(int(datetime.now(timezone.utc).timestamp()))[-6:]
    new_slug = f"{doc.get('slug', 'project')}__deleted-{suffix}"
    new_key = f"{doc.get('key', 'PRJ')}X{suffix}"[:10]
    result = await get_db()[PROJECTS_COLLECTION].find_one_and_update(
        {"_id": doc["_id"], "deletedAt": None},
        {"$set": {
            "deletedAt": _now_iso(),
            "deletedBy": user_id,
            "slug": new_slug,
            "key": new_key,
        }},
        return_document=True,
    )
    logger.info(f"Project soft-deleted: '{doc.get('name')}' ({doc.get('key')}) by {user_id}")
    return result


def _oid_safe(raw: str) -> Optional[ObjectId]:
    try:
        return ObjectId(raw)
    except Exception:
        return None


async def update_project(project_id: str, name: str) -> Optional[Dict[str, Any]]:
    """Rename nama project. Slug & key sengaja tidak berubah agar URL lama
    dan nomor tiket (KEY-N) tetap valid. Return doc terbaru atau None bila tidak ada."""
    name = (name or "").strip()
    if len(name) < 2:
        raise ValueError("Nama project minimal 2 karakter")
    try:
        oid = ObjectId(project_id)
    except Exception:
        return None
    result = await get_db()[PROJECTS_COLLECTION].find_one_and_update(
        {"_id": oid},
        {"$set": {"name": name}},
        return_document=ReturnDocument.AFTER,
    )
    if result is not None:
        logger.info(f"Project renamed: {project_id} → {name}")
    return result
