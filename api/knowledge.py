"""
Knowledge router — FE-7 Knowledge Workspace + Library Pribadi.

Kepemilikan ketat (dipaksa di router DAN store):
- Library: hanya owner (admin global pun tidak bisa akses item orang lain).
- Link ke workspace: owner library + admin workspace target.
- Lepas link: admin workspace. Baca via workspace: member workspace.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from services import knowledge_store
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


class KnowledgeItemPatchRequest(BaseModel):
    name: Optional[str] = None
    folder: Optional[str] = None
    content: Optional[str] = None


class LinkRequest(BaseModel):
    libraryId: str


class CascadeDeleteRequest(BaseModel):
    confirm: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid(user: dict) -> str:
    return str(user["_id"])


async def _owned_item_or_404(item_id: str, user: dict) -> dict:
    """Item library HANYA milik owner — admin global tidak dikecualikan (desain ketat)."""
    item = await knowledge_store.get_item(item_id)
    if item is None or item.get("ownerId") != _uid(user):
        # 404 (bukan 403) agar tidak membocorkan keberadaan item orang lain
        raise HTTPException(404, "Dokumen knowledge tidak ditemukan")
    return item


async def _workspace_and_membership(ws_id: str, user: dict):
    ws = await find_workspace_by_id(ws_id)
    if ws is None:
        raise HTTPException(404, "Workspace tidak ditemukan")
    member = get_membership(ws, _uid(user))
    if member is None and ws.get("ownerId") != _uid(user):
        raise HTTPException(403, "Bukan member workspace ini")
    return ws, member


# ── Library Pribadi (management?tab=knowledge) ────────────────────────────────

@router.get("/library")
async def my_library(current_user: dict = Depends(get_current_user)):
    items = await knowledge_store.list_items_for_owner(_uid(current_user))
    return {"items": items}


@router.post("/library", status_code=201)
async def create_library_item(
    body: KnowledgeItemRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        doc = await knowledge_store.create_item(
            _uid(current_user), body.name, body.folder, body.content
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
    try:
        doc = await knowledge_store.update_item(
            item_id, _uid(current_user),
            {"name": body.name, "folder": body.folder, "content": body.content},
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    if doc is None:
        raise HTTPException(404, "Dokumen knowledge tidak ditemukan")
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
    usage = await knowledge_store.list_usage(item_id)
    if usage and not confirm:
        raise HTTPException(409, {
            "message": f"Knowledge masih dipakai {len(usage)} workspace",
            "workspaces": usage,
        })
    ok = await knowledge_store.delete_item(item_id, _uid(current_user))
    if not ok:
        raise HTTPException(404, "Dokumen knowledge tidak ditemukan")
    return {"deleted": item_id, "refsRemoved": len(usage)}


# ── Knowledge Workspace (/w/:slug/settings → section Knowledge) ──────────────

@router.get("/workspaces/{ws_id}")
async def workspace_knowledge_list(ws_id: str, current_user: dict = Depends(get_current_user)):
    await _workspace_and_membership(ws_id, current_user)
    refs = await knowledge_store.list_refs_for_workspace(ws_id)
    return {"items": refs}


@router.get("/workspaces/{ws_id}/{ref_id}")
async def workspace_knowledge_detail(
    ws_id: str, ref_id: str, current_user: dict = Depends(get_current_user),
):
    """Preview konten — semua member workspace boleh baca."""
    await _workspace_and_membership(ws_id, current_user)
    detail = await knowledge_store.get_ref_with_content(ws_id, ref_id)
    if detail is None:
        raise HTTPException(404, "Referensi knowledge tidak ditemukan")
    return detail


@router.post("/workspaces/{ws_id}", status_code=201)
async def link_knowledge_to_workspace(
    ws_id: str,
    body: LinkRequest,
    current_user: dict = Depends(get_current_user),
):
    """Link item library ke workspace. Syarat: owner library DAN admin workspace."""
    user_id = _uid(current_user)
    ws, _member = await _workspace_and_membership(ws_id, current_user)
    if not is_workspace_admin(ws, user_id):
        raise HTTPException(403, "Hanya admin workspace yang bisa menambah knowledge")
    # ownership library dicek ketat (404 bila bukan miliknya)
    await _owned_item_or_404(body.libraryId, current_user)
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
    if not is_workspace_admin(ws, user_id):
        raise HTTPException(403, "Hanya admin workspace yang bisa melepas knowledge")
    ok = await knowledge_store.remove_ref(ws_id, ref_id)
    if not ok:
        raise HTTPException(404, "Referensi knowledge tidak ditemukan")
    return {"removed": ref_id}
