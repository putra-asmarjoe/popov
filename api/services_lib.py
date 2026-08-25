"""
Services router — FE-8 Services Layer (library + project refs + knowledge links).

Kepemilikan ketat (dipaksa di store DAN router):
- Library service: hanya owner (admin global pun tidak).
- Link service → project: owner library + admin workspace.
- Link knowledge → service: owner service + owner knowledge.
- Baca via project: semua member workspace.

GET /services/registry: daftar service_id monitoring GLOBAL untuk validasi form
(read-only, authenticated user apa pun, TANPA URI/kredensial).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from services import service_store
from services.knowledge_store import get_item as get_knowledge_item
from services.workspace_store import (
    find_project_by_id,
    find_workspace_by_id,
    get_membership,
    is_workspace_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/services", tags=["services"])


# ── Request schemas ───────────────────────────────────────────────────────────

class DbConfigRequest(BaseModel):
    type: str = "mongodb"            # mongodb | mysql
    uri: str
    db: str
    collection: Optional[str] = None


class ServiceItemRequest(BaseModel):
    service_id: str
    label: Optional[str] = None
    description: Optional[str] = None
    # Fix #38: koneksi log transaksi per-service (opsional) — service bebas dibuat
    db_config: Optional[DbConfigRequest] = None


class ServiceItemPatchRequest(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    # kirim {} / field kosong untuk menghapus koneksi
    db_config: Optional[DbConfigRequest] = None


class LinkProjectRequest(BaseModel):
    libraryServiceId: str


class LinkKnowledgeRequest(BaseModel):
    knowledgeLibraryId: str


def _uid(user: dict) -> str:
    return str(user["_id"])


async def _owned_service_or_404(item_id: str, user: dict) -> dict:
    item = await service_store.get_item(item_id)
    if item is None or item.get("ownerId") != _uid(user):
        # 404 (bukan 403) agar tidak membocorkan keberadaan item orang lain
        raise HTTPException(404, "Service tidak ditemukan")
    return item


async def _project_ws_admin_guard(project_id: str, user: dict, require_admin: bool):
    """Project harus ada; user member workspace; opsional ws-admin."""
    project = await find_project_by_id(project_id)
    if project is None:
        raise HTTPException(404, "Project tidak ditemukan")
    ws = await find_workspace_by_id(str(project["workspaceId"]))
    if ws is None:
        raise HTTPException(404, "Workspace project tidak ditemukan")
    uid = _uid(user)
    if get_membership(ws, uid) is None and str(ws.get("ownerId", "")) != uid:
        raise HTTPException(403, "Bukan member workspace ini")
    if require_admin and not is_workspace_admin(ws, uid):
        raise HTTPException(403, "Hanya admin workspace yang bisa mengubah services project")
    return project, ws


# ── Registry global (validasi form — tanpa kredensial) ────────────────────────

@router.get("/registry")
async def service_registry(current_user: dict = Depends(get_current_user)):
    return {"services": [{"service_id": s} for s in await service_store.global_service_ids()]}


# ── Library pribadi ───────────────────────────────────────────────────────────

@router.get("/library")
async def my_services(current_user: dict = Depends(get_current_user)):
    items = await service_store.list_items_for_owner(_uid(current_user))
    return {"items": items}


@router.post("/library", status_code=201)
async def create_service_item(body: ServiceItemRequest, current_user: dict = Depends(get_current_user)):
    # FE-8.5: koneksi log-DB menyangkut sumber data pipeline — global admin only
    if body.db_config is not None and current_user.get("role") != "admin":
        raise HTTPException(
            403,
            "Koneksi database hanya bisa didaftarkan admin global — "
            "simpan service tanpa DB config, lalu hubungi admin",
        )
    try:
        doc = await service_store.create_item(
            _uid(current_user), body.service_id, body.label or "", body.description or "",
            db_config=body.db_config.model_dump() if body.db_config else None,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return await service_store._public_item(doc)


@router.get("/library/{item_id}")
async def get_service_item(item_id: str, current_user: dict = Depends(get_current_user)):
    item = await _owned_service_or_404(item_id, current_user)
    usage = await service_store.list_usage(item_id)
    links = await service_store.list_knowledge_links(item_id)
    out = await service_store._public_item(item, len(usage), len(links))
    out["description"] = item.get("description") or ""
    return out


@router.patch("/library/{item_id}")
async def update_service_item(
    item_id: str,
    body: ServiceItemPatchRequest,
    current_user: dict = Depends(get_current_user),
):
    # FE-8.5: guard yang sama dengan create — db_config global-admin only
    if body.db_config is not None and current_user.get("role") != "admin":
        raise HTTPException(403, "Koneksi database hanya bisa diubah admin global")
    doc = await service_store.update_item(
        item_id, _uid(current_user),
        {
            "label": body.label,
            "description": body.description,
            "db_config": body.db_config.model_dump() if body.db_config else {},
        },
    )
    if doc is None:
        raise HTTPException(404, "Service tidak ditemukan")
    return await service_store._public_item(doc)


@router.delete("/library/{item_id}")
async def delete_service_item(
    item_id: str,
    confirm: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Hapus service library. Bila masih dipakai project dan confirm=false → 409 + daftar."""
    await _owned_service_or_404(item_id, current_user)
    usage = await service_store.list_usage(item_id)
    if usage and not confirm:
        raise HTTPException(409, {
            "message": f"Service masih dipakai {len(usage)} project",
            "projects": usage,
        })
    ok = await service_store.delete_item(item_id, _uid(current_user))
    if not ok:
        raise HTTPException(404, "Service tidak ditemukan")
    return {"deleted": item_id, "refsRemoved": len(usage)}


@router.get("/library/{item_id}/usage")
async def service_item_usage(item_id: str, current_user: dict = Depends(get_current_user)):
    await _owned_service_or_404(item_id, current_user)
    return {"usage": await service_store.list_usage(item_id)}


# ── Knowledge links pada service ──────────────────────────────────────────────

@router.get("/library/{item_id}/knowledge")
async def service_knowledge_links(item_id: str, current_user: dict = Depends(get_current_user)):
    await _owned_service_or_404(item_id, current_user)
    return {"links": await service_store.list_knowledge_links(item_id)}


@router.post("/library/{item_id}/knowledge", status_code=201)
async def link_service_knowledge(
    item_id: str,
    body: LinkKnowledgeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Owner service DAN owner knowledge — dua-duanya dicek ketat."""
    svc = await _owned_service_or_404(item_id, current_user)
    kb = await get_knowledge_item(body.knowledgeLibraryId)
    if kb is None or kb.get("ownerId") != _uid(current_user):
        raise HTTPException(404, "Dokumen knowledge tidak ditemukan (bukan milikmu)")
    try:
        ref = await service_store.link_knowledge(str(svc["_id"]), body.knowledgeLibraryId, _uid(current_user))
    except ValueError as e:
        raise HTTPException(409, str(e))
    logger.info(f"Knowledge linked to service '{svc.get('serviceId')}' by {current_user.get('email')}")
    return service_store._public_knowledge_ref(ref, kb)


@router.delete("/library/{item_id}/knowledge/{ref_id}")
async def unlink_service_knowledge(
    item_id: str, ref_id: str, current_user: dict = Depends(get_current_user),
):
    await _owned_service_or_404(item_id, current_user)
    ok = await service_store.unlink_knowledge(item_id, ref_id)
    if not ok:
        raise HTTPException(404, "Link knowledge tidak ditemukan")
    return {"removed": ref_id}


# ── Services dalam project ────────────────────────────────────────────────────

@router.get("/workspace/{ws_id}")
async def workspace_services_grouped(ws_id: str, current_user: dict = Depends(get_current_user)):
    """Semua service ter-link di seluruh project workspace (grouped per project).

    FE-8.1: pengelolaan dipindah ke halaman settings workspace. Member boleh baca.
    """
    ws = await find_workspace_by_id(ws_id)
    if ws is None:
        raise HTTPException(404, "Workspace tidak ditemukan")
    uid = _uid(current_user)
    if get_membership(ws, uid) is None and str(ws.get("ownerId", "")) != uid:
        raise HTTPException(403, "Bukan member workspace ini")
    groups = await service_store.list_refs_for_workspace_grouped(ws_id)
    return {"groups": groups}


@router.get("/projects/{project_id}")
async def project_services(project_id: str, current_user: dict = Depends(get_current_user)):
    """Member workspace boleh lihat services project."""
    await _project_ws_admin_guard(project_id, current_user, require_admin=False)
    return {"items": await service_store.list_refs_for_project(project_id)}


@router.post("/projects/{project_id}", status_code=201)
async def link_service_to_project(
    project_id: str,
    body: LinkProjectRequest,
    current_user: dict = Depends(get_current_user),
):
    """Admin workspace + owner service library."""
    await _project_ws_admin_guard(project_id, current_user, require_admin=True)
    svc = await _owned_service_or_404(body.libraryServiceId, current_user)
    try:
        ref = await service_store.add_project_ref(project_id, body.libraryServiceId, _uid(current_user))
    except ValueError as e:
        raise HTTPException(409, str(e))
    logger.info(f"Service linked to project={project_id} svc='{svc.get('serviceId')}' by {current_user.get('email')}")
    return service_store._public_project_ref(ref, svc)


@router.delete("/projects/{project_id}/{ref_id}")
async def unlink_service_from_project(
    project_id: str, ref_id: str, current_user: dict = Depends(get_current_user),
):
    """Lepas service dari project (library tetap utuh). Admin workspace saja."""
    await _project_ws_admin_guard(project_id, current_user, require_admin=True)
    ok = await service_store.remove_project_ref(project_id, ref_id)
    if not ok:
        raise HTTPException(404, "Referensi service tidak ditemukan")
    return {"removed": ref_id}
