"""
Knowledge router — FE-7 Knowledge Workspace + Library Pribadi.

Kepemilikan ketat (dipaksa di router DAN store):
- Library: hanya owner (admin global pun tidak bisa akses item orang lain).
- Link ke workspace: owner library + admin workspace target.
- Lepas link: admin workspace. Baca via workspace: member workspace.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from api.messages import msg, M
from services import knowledge_store
from services import agent_doc_refs_store
from services.user_store import get_user_locale
from services.workspace_store import (
    find_workspace_by_id,
    get_membership,
    is_workspace_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# ── Request schemas ───────────────────────────────────────────────────────────

class KnowledgeItemRequest(BaseModel):
    name: str
    folder: str = "general"
    content: str
    meta: Optional[Dict[str, Any]] = None


class KnowledgeItemPatchRequest(BaseModel):
    name: Optional[str] = None
    folder: Optional[str] = None
    content: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class LinkRequest(BaseModel):
    libraryId: str


class WorkspaceKnowledgeRequest(BaseModel):
    name: str
    folder: str = "general"
    content: str


class WorkspaceKnowledgePatchRequest(BaseModel):
    name: Optional[str] = None
    folder: Optional[str] = None
    content: Optional[str] = None


class AgentDocLinkRequest(BaseModel):
    category: str
    key: str


class CascadeDeleteRequest(BaseModel):
    confirm: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid(user: dict) -> str:
    return str(user["_id"])


async def _get_user_locale(user_id: str) -> str:
    return await get_user_locale(user_id)


async def _owned_item_or_404(item_id: str, user: dict) -> dict:
    """Item library milik owner, system workspace tempat user jadi member, atau management library."""
    locale = await _get_user_locale(_uid(user))
    item = await knowledge_store.get_item(item_id)
    if item is None:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_DOC_NOT_FOUND))

    user_id = _uid(user)
    owner_id = item.get("ownerId", "")

    # 1. Owner langsung
    if owner_id == user_id:
        return item

    # 2. System owner ("system:<ws_id>") — ijinkan jika user adalah member/owner workspace tersebut
    if owner_id.startswith("system:"):
        ws_id = owner_id.split(":", 1)[1]
        from services.workspace_store import find_workspace_by_id, get_membership
        ws = await find_workspace_by_id(ws_id)
        if ws and (get_membership(ws, user_id) is not None or ws.get("ownerId") == user_id):
            return item

    # 3. Terkoneksi ke service/workspace di mana user adalah member
    db = knowledge_store.get_db()
    sk_refs = await db["service_knowledge_refs"].find({"knowledgeLibraryId": item_id}).to_list(10)
    for sk in sk_refs:
        added_by = sk.get("addedBy", "")
        if added_by.startswith("system:"):
            ws_id = added_by.split(":", 1)[1]
            from services.workspace_store import find_workspace_by_id, get_membership
            ws = await find_workspace_by_id(ws_id)
            if ws and (get_membership(ws, user_id) is not None or ws.get("ownerId") == user_id):
                return item

    # 4. Management library item
    mgmt_items = await knowledge_store.list_management_library()
    if any(i["id"] == item_id for i in mgmt_items):
        return item

    # 404 agar tidak membocorkan keberadaan item milik user lain
    raise HTTPException(404, msg(locale, M.KNOWLEDGE_DOC_NOT_FOUND))


async def _workspace_and_membership(ws_id: str, user: dict):
    locale = await _get_user_locale(_uid(user))
    ws = await find_workspace_by_id(ws_id)
    if ws is None:
        raise HTTPException(404, msg(locale, M.WORKSPACE_NOT_FOUND))
    member = get_membership(ws, _uid(user))
    if member is None and ws.get("ownerId") != _uid(user):
        raise HTTPException(403, msg(locale, M.NOT_WORKSPACE_MEMBER))
    return ws, member


# ── Library Pribadi (management?tab=knowledge) ────────────────────────────────

@router.get("/library")
async def my_library(current_user: dict = Depends(get_current_user)):
    items = await knowledge_store.list_items_for_owner(_uid(current_user))
    return {"items": items}


@router.get("/management-library")
async def management_library(current_user: dict = Depends(get_current_user)):
    """Library pusat Management — read-only untuk semua member (untuk picker workspace)."""
    items = await knowledge_store.list_management_library()
    return {"items": items}


@router.get("/management-library/{item_id}")
async def get_management_library_item(item_id: str, current_user: dict = Depends(get_current_user)):
    """Detail management doc — boleh dibaca semua authenticated (untuk preview picker)."""
    locale = await _get_user_locale(_uid(current_user))
    item = await knowledge_store.get_item(item_id)
    if item is None:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_DOC_NOT_FOUND))
    mgmt_items = await knowledge_store.list_management_library()
    mgmt_ids = {i["id"] for i in mgmt_items}
    if item_id not in mgmt_ids:
        # fallback owner check untuk personal preview
        if item.get("ownerId") != _uid(current_user):
            raise HTTPException(404, msg(locale, M.KNOWLEDGE_DOC_NOT_FOUND))
    return knowledge_store._public_item(item, include_content=True)


@router.post("/library", status_code=201)
async def create_library_item(
    body: KnowledgeItemRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        doc = await knowledge_store.create_item(
            _uid(current_user), body.name, body.folder, body.content, meta=body.meta
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    from services.workspace_knowledge import invalidate_cache
    invalidate_cache()
    return knowledge_store._public_item(doc, include_content=True)


@router.get("/library/{item_id}")
async def get_library_item(item_id: str, current_user: dict = Depends(get_current_user)):
    """Detail + konten dokumen library — owner only."""
    item = await _owned_item_or_404(item_id, current_user)
    return knowledge_store._public_item(item, include_content=True)


@router.patch("/library/{item_id}")
async def update_library_item(
    item_id: str,
    body: KnowledgeItemPatchRequest,
    current_user: dict = Depends(get_current_user),
):
    locale = await _get_user_locale(_uid(current_user))
    try:
        doc = await knowledge_store.update_item(
            item_id, _uid(current_user),
            {"name": body.name, "folder": body.folder, "content": body.content, "meta": body.meta},
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    if doc is None:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_DOC_NOT_FOUND))
    from services.workspace_knowledge import invalidate_cache
    invalidate_cache()
    return knowledge_store._public_item(doc, include_content=True)


@router.get("/library/{item_id}/usage")
async def library_item_usage(item_id: str, current_user: dict = Depends(get_current_user)):
    await _owned_item_or_404(item_id, current_user)
    usage = await knowledge_store.list_usage(item_id)
    return {"usage": usage}


@router.delete("/library/{item_id}")
async def delete_library_item(
    item_id: str,
    confirm: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Hapus dokumen library. Bila masih dipakai workspace dan confirm=false → 409 + daftar."""
    await _owned_item_or_404(item_id, current_user)
    locale = await _get_user_locale(_uid(current_user))
    usage = await knowledge_store.list_usage(item_id)
    if usage and not confirm:
        raise HTTPException(409, {
            "message": msg(locale, M.KNOWLEDGE_IN_USE, count=len(usage)),
            "workspaces": usage,
        })
    ok = await knowledge_store.delete_item(item_id, _uid(current_user))
    if not ok:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_DOC_NOT_FOUND))
    return {"deleted": item_id, "refsRemoved": len(usage)}


# ── Knowledge Workspace (/w/:slug/settings → section Knowledge) ──────────────

@router.get("/workspaces/{ws_id}")
async def workspace_knowledge_list(ws_id: str, current_user: dict = Depends(get_current_user)):
    await _workspace_and_membership(ws_id, current_user)
    refs = await knowledge_store.list_refs_for_workspace(ws_id)
    ws_items = await knowledge_store.list_workspace_items(ws_id)
    return {"items": refs, "workspaceItems": ws_items}


@router.get("/workspaces/{ws_id}/items/{item_id}")
async def get_workspace_knowledge_item(
    ws_id: str, item_id: str, current_user: dict = Depends(get_current_user),
):
    """Detail workspace knowledge — semua member workspace boleh baca."""
    await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(_uid(current_user))
    item = await knowledge_store.get_workspace_item(item_id)
    if item is None or item.get("workspaceId") != ws_id:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_NOT_FOUND))
    return knowledge_store._public_workspace_item(item, include_content=True)


@router.post("/workspaces/{ws_id}/items", status_code=201)
async def create_workspace_knowledge(
    ws_id: str,
    body: WorkspaceKnowledgeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Buat knowledge baru yang spesifik workspace — admin workspace only."""
    user_id = _uid(current_user)
    ws, _member = await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(user_id)
    if not is_workspace_admin(ws, user_id):
        raise HTTPException(403, msg(locale, M.ADMIN_ONLY_ADD_KNOWLEDGE))
    try:
        doc = await knowledge_store.create_workspace_item(
            str(ws["_id"]), user_id, body.name, body.folder, body.content
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return knowledge_store._public_workspace_item(doc, include_content=True)


@router.patch("/workspaces/{ws_id}/items/{item_id}")
async def update_workspace_knowledge(
    ws_id: str,
    item_id: str,
    body: WorkspaceKnowledgePatchRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update workspace knowledge — owner only."""
    user_id = _uid(current_user)
    await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(user_id)
    try:
        doc = await knowledge_store.update_workspace_item(
            item_id, user_id,
            {"name": body.name, "folder": body.folder, "content": body.content},
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    if doc is None:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_NOT_FOUND))
    return knowledge_store._public_workspace_item(doc, include_content=True)


@router.delete("/workspaces/{ws_id}/items/{item_id}")
async def delete_workspace_knowledge(
    ws_id: str,
    item_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Hapus workspace knowledge — owner only."""
    user_id = _uid(current_user)
    await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(user_id)
    ok = await knowledge_store.delete_workspace_item(item_id, user_id)
    if not ok:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_NOT_FOUND))
    return {"deleted": item_id}


# ── Agent Doc Refs (Grounding Docs → Workspace) ──────────────────────────────
# WAJIB sebelum /{ref_id} catch-all routes — hindari route conflict

@router.get("/workspaces/{ws_id}/agent-docs")
async def list_agent_doc_refs(ws_id: str, current_user: dict = Depends(get_current_user)):
    """Daftar grounding docs yang ter-link ke workspace (read-only refs)."""
    await _workspace_and_membership(ws_id, current_user)
    refs = await agent_doc_refs_store.list_refs_for_workspace(ws_id)
    return {"items": refs}


@router.post("/workspaces/{ws_id}/agent-docs", status_code=201)
async def link_agent_doc(
    ws_id: str,
    body: AgentDocLinkRequest,
    current_user: dict = Depends(get_current_user),
):
    """Link grounding doc ke workspace. Admin workspace only. Read-only — tidak ada CRUD doc."""
    user_id = _uid(current_user)
    ws, _member = await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(user_id)
    if not is_workspace_admin(ws, user_id):
        raise HTTPException(403, msg(locale, M.ADMIN_ONLY_CONNECT_GROUNDING))
    from services.agent_docs_store import get_doc
    doc = await get_doc(body.category, body.key)
    if doc is None:
        raise HTTPException(404, msg(locale, M.GROUNDING_DOC_NOT_FOUND))
    try:
        ref = await agent_doc_refs_store.add_ref(
            str(ws["_id"]), body.category, body.key, user_id
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    logger.info(
        f"Agent doc linked ws={ws.get('slug')} doc={body.category}/{body.key} by {current_user.get('email')}"
    )
    return {
        "id": str(ref["_id"]),
        "workspaceId": ref.get("workspaceId", ""),
        "docCategory": ref.get("docCategory", ""),
        "docKey": ref.get("docKey", ""),
        "addedBy": ref.get("addedBy", ""),
        "createdAt": ref.get("createdAt", ""),
    }


@router.get("/workspaces/{ws_id}/agent-docs/available")
async def available_agent_docs(ws_id: str, current_user: dict = Depends(get_current_user)):
    """List semua grounding docs yang BELUM ter-link ke workspace (untuk picker)."""
    await _workspace_and_membership(ws_id, current_user)
    from services.agent_docs_store import list_docs
    all_docs = await list_docs()
    existing = await agent_doc_refs_store.list_refs_for_workspace(ws_id)
    linked_keys = {(r["docCategory"], r["docKey"]) for r in existing}
    available = [
        {
            "category": d.get("category", ""),
            "key": d.get("key", ""),
            "body_len": len(d.get("body", "")),
            "updatedAt": d.get("updatedAt"),
            "meta": d.get("meta", {}),
        }
        for d in all_docs
        if (d.get("category", ""), d.get("key", "")) not in linked_keys
    ]
    return {"items": available}


@router.delete("/workspaces/{ws_id}/agent-docs/{ref_id}")
async def unlink_agent_doc(
    ws_id: str, ref_id: str, current_user: dict = Depends(get_current_user),
):
    """Lepas koneksi grounding doc dari workspace. Admin workspace only. Doc TIDAK terhapus."""
    user_id = _uid(current_user)
    ws, _member = await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(user_id)
    if not is_workspace_admin(ws, user_id):
        raise HTTPException(403, msg(locale, M.ADMIN_ONLY_UNLINK_GROUNDING))
    ok = await agent_doc_refs_store.remove_ref(ws_id, ref_id)
    if not ok:
        raise HTTPException(404, msg(locale, M.GROUNDING_REF_NOT_FOUND))
    return {"removed": ref_id}


# ── Catch-all routes (WAJIB di akhir) ────────────────────────────────────────

@router.get("/workspaces/{ws_id}/{ref_id}")
async def workspace_knowledge_detail(
    ws_id: str, ref_id: str, current_user: dict = Depends(get_current_user),
):
    """Preview konten — semua member workspace boleh baca."""
    await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(_uid(current_user))
    detail = await knowledge_store.get_ref_with_content(ws_id, ref_id)
    if detail is None:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_REF_NOT_FOUND))
    return detail


@router.post("/workspaces/{ws_id}", status_code=201)
async def link_knowledge_to_workspace(
    ws_id: str,
    body: LinkRequest,
    current_user: dict = Depends(get_current_user),
):
    """Link item library ke workspace. Syarat: admin workspace + item dari Management library (admin-owned)."""
    user_id = _uid(current_user)
    ws, _member = await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(user_id)
    if not is_workspace_admin(ws, user_id):
        raise HTTPException(403, msg(locale, M.ADMIN_ONLY_ADD_KNOWLEDGE))
    # Management library: boleh link item milik admin mana pun (read-only picker)
    item = await knowledge_store.get_item(body.libraryId)
    if item is None:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_DOC_NOT_FOUND))
    mgmt_items = await knowledge_store.list_management_library()
    mgmt_ids = {i["id"] for i in mgmt_items}
    if body.libraryId not in mgmt_ids and item.get("ownerId") != user_id:
        raise HTTPException(403, msg(locale, M.ONLY_MANAGEMENT_DOCS))
    try:
        ref = await knowledge_store.add_ref(str(ws["_id"]), body.libraryId, user_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    logger.info(f"Knowledge linked ws={ws.get('slug')} lib={body.libraryId} by {current_user.get('email')}")
    refs = await knowledge_store.list_refs_for_workspace(str(ws["_id"]))
    for r in refs:
        if r["id"] == str(ref["_id"]):
            return r
    return refs[-1] if refs else {"id": str(ref["_id"])}


@router.delete("/workspaces/{ws_id}/{ref_id}")
async def unlink_knowledge_from_workspace(
    ws_id: str, ref_id: str, current_user: dict = Depends(get_current_user),
):
    """Lepas link dari workspace (library TIDAK terhapus). Admin workspace saja."""
    user_id = _uid(current_user)
    ws, _member = await _workspace_and_membership(ws_id, current_user)
    locale = await _get_user_locale(user_id)
    if not is_workspace_admin(ws, user_id):
        raise HTTPException(403, msg(locale, M.ADMIN_ONLY_UNLINK_KNOWLEDGE))
    ok = await knowledge_store.remove_ref(ws_id, ref_id)
    if not ok:
        raise HTTPException(404, msg(locale, M.KNOWLEDGE_REF_NOT_FOUND))
    return {"removed": ref_id}
