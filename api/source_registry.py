"""
Source Registry API — 1C roadmap integrasi (Fix #207).

Workspace-scoped CRUD utk source eksternal yang pernah kirim signal.
- GET   /workspaces/{ws_id}/sources          — member read (list + status)
- PATCH /workspaces/{ws_id}/sources/{id}     — ws-admin: enable/disable + rename
- DELETE /workspaces/{ws_id}/sources/{id}    — ws-admin: hapus

Record otomatis terjadi di jalur ingest (public_alerts + deploy_events) —
API ini hanya untuk list/kelola. Pattern guard sama dgn notification_channels.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user
from services.workspace_store import find_workspace_by_id, get_membership, is_workspace_admin

logger = logging.getLogger(__name__)

router = APIRouter()


def _uid(user: dict) -> str:
    return str(user["_id"])


async def _ws_member_or_404(ws_id: str, user: dict) -> dict:
    ws = await find_workspace_by_id(ws_id)
    if ws is None:
        raise HTTPException(404, "Workspace tidak ditemukan")
    uid = _uid(user)
    if get_membership(ws, uid) is None and str(ws.get("ownerId", "")) != uid:
        raise HTTPException(403, "Bukan member workspace ini")
    return ws


class PatchSourceRequest(BaseModel):
    enabled: Optional[bool] = None
    source_label: Optional[str] = None


@router.get("/workspaces/{ws_id}/sources")
async def list_sources(ws_id: str, current_user: dict = Depends(get_current_user)):
    """Daftar source yang pernah kirim signal ke workspace (member read)."""
    await _ws_member_or_404(ws_id, current_user)
    from services.source_registry_store import list_sources
    docs = await list_sources(ws_id)
    return {"sources": docs}


@router.patch("/workspaces/{ws_id}/sources/{source_id}")
async def patch_source(
    ws_id: str,
    source_id: str,
    body: PatchSourceRequest,
    current_user: dict = Depends(get_current_user),
):
    """Enable/disable atau rename source (ws-admin only)."""
    ws = await _ws_member_or_404(ws_id, current_user)
    if not is_workspace_admin(ws, _uid(current_user)):
        raise HTTPException(403, "Hanya admin workspace yang bisa mengelola source registry")

    from services.source_registry_store import rename_source, set_source_enabled

    doc = None
    if body.enabled is not None:
        doc = await set_source_enabled(ws_id, source_id, body.enabled)
    if body.source_label is not None:
        doc = await rename_source(ws_id, source_id, body.source_label)
    if doc is None:
        raise HTTPException(404, "Source tidak ditemukan")
    return {"source": doc}


@router.delete("/workspaces/{ws_id}/sources/{source_id}", status_code=200)
async def delete_source(
    ws_id: str,
    source_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Hapus entri source (ws-admin only). API key tidak ikut terhapus."""
    ws = await _ws_member_or_404(ws_id, current_user)
    if not is_workspace_admin(ws, _uid(current_user)):
        raise HTTPException(403, "Hanya admin workspace yang bisa menghapus source registry")

    from services.source_registry_store import delete_source as _delete
    deleted = await _delete(ws_id, source_id)
    if not deleted:
        raise HTTPException(404, "Source tidak ditemukan")
    return {"ok": True}