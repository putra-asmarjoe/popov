"""
Workspace & project router — FE-2.
Semua endpoint butuh auth (Bearer JWT) + membership workspace.

- GET  /workspaces                     → list workspace milik user (auto-create default bila kosong)
- POST /workspaces                     → buat workspace (creator jadi admin)
- GET  /workspaces/{wsId}              → detail + members (join nama/email user)
- POST /workspaces/{wsId}/members      → invite by email (admin ws only)
- DELETE /workspaces/{wsId}/members/{userId} → remove member (admin ws only, owner terlindungi)
- POST /workspaces/{wsId}/projects     → buat project (member boleh)
- GET  /workspaces/{wsId}/projects     → list project di workspace
- PATCH /workspaces/{wsId}/projects/{projectId} → rename nama project (admin ws)
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from api.messages import msg, M
from services.mongodb_client import get_db
from services.user_store import find_by_email, get_user, get_user_locale
from services.workspace_store import (
    add_member,
    create_project,
    create_workspace,
    find_project_by_id,
    find_workspace_by_id,
    get_membership,
    is_workspace_admin,
    soft_delete_project,
    list_projects,
    list_workspaces_for_user,
    public_project,
    public_workspace,
    remove_member,
    update_project,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ── Request schema ─────────────────────────────────────────────────────────────

class CreateWorkspaceRequest(BaseModel):
    name: str


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"  # admin | member (workspace role)


class CreateProjectRequest(BaseModel):
    name: str
    key: str


class UpdateProjectRequest(BaseModel):
    name: str


# ── Helper ─────────────────────────────────────────────────────────────────────

async def _get_user_locale(user_id: str) -> str:
    return await get_user_locale(user_id)


def _require_membership(ws: Dict[str, Any], user: Dict[str, Any]) -> None:
    if get_membership(ws, str(user["_id"])) is None and str(ws.get("ownerId")) != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Kamu bukan member workspace ini")


def _require_admin(ws: Dict[str, Any], user: Dict[str, Any]) -> None:
    _require_membership(ws, user)
    if not is_workspace_admin(ws, str(user["_id"])):
        raise HTTPException(status_code=403, detail="Hanya workspace admin yang boleh melakukan aksi ini")


async def _get_workspace_or_404(ws_id: str) -> Dict[str, Any]:
    ws = await find_workspace_by_id(ws_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace tidak ditemukan")
    return ws


# ── Workspace ──────────────────────────────────────────────────────────────────

@router.get("")
async def list_my_workspaces(current_user: dict = Depends(get_current_user)):
    """Workspace milik user. Hanya user pertama (admin) yang auto-create workspace default."""
    user_id = str(current_user["_id"])
    workspaces = await list_workspaces_for_user(user_id)
    if not workspaces and current_user.get("role") == "admin":
        default_name = f"Workspace {current_user.get('name', 'Saya')}".strip()
        ws = await create_workspace(default_name, current_user)
        workspaces = [ws]
    return {"workspaces": [public_workspace(w) for w in workspaces]}


@router.post("", status_code=201)
async def create_new_workspace(
    body: CreateWorkspaceRequest,
    current_user: dict = Depends(get_current_user),
):
    locale = await _get_user_locale(str(current_user["_id"]))
    try:
        ws = await create_workspace(body.name, current_user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Create workspace failed: {e}")
        raise HTTPException(status_code=500, detail=msg(locale, M.FAILED_CREATE_WORKSPACE))
    return public_workspace(ws)


@router.get("/{ws_id}")
async def workspace_detail(
    ws_id: str,
    current_user: dict = Depends(get_current_user),
):
    ws = await _get_workspace_or_404(ws_id)
    _require_membership(ws, current_user)

    # Join info user untuk tiap member
    locale = await _get_user_locale(str(current_user["_id"]))
    members: List[Dict[str, Any]] = []
    for m in ws.get("members", []):
        user = await get_user(m.get("userId", ""))
        members.append({
            "userId": m.get("userId"),
            "name": user.get("name", msg(locale, M.DELETED_LABEL)) if user else msg(locale, M.DELETED_LABEL),
            "email": user.get("email", "-") if user else "-",
            "globalRole": user.get("role", "member") if user else "-",
            "wsRole": m.get("role", "member"),
            "joinedAt": m.get("joinedAt"),
        })

    result = public_workspace(ws)
    result["members"] = members
    result["isOwner"] = str(ws.get("ownerId")) == str(current_user["_id"])
    return result


# ── Members ────────────────────────────────────────────────────────────────────

@router.post("/{ws_id}/members", status_code=201)
async def invite_member(
    ws_id: str,
    body: InviteMemberRequest,
    current_user: dict = Depends(get_current_user),
):
    """Invite user (harus sudah terdaftar) ke workspace. Admin workspace only."""
    ws = await _get_workspace_or_404(ws_id)
    _require_admin(ws, current_user)
    locale = await _get_user_locale(str(current_user["_id"]))

    if body.role not in ("admin", "member"):
        raise HTTPException(status_code=422, detail=msg(locale, M.ROLE_MUST_BE_ADMIN_OR_MEMBER))

    target = await find_by_email(body.email)
    if target is None:
        raise HTTPException(status_code=404, detail=msg(locale, M.USER_NOT_REGISTERED, email=body.email))

    target_id = str(target["_id"])
    if target_id == str(ws.get("ownerId")):
        raise HTTPException(status_code=409, detail=msg(locale, M.OWNER_ALREADY_ADMIN))

    await add_member(ws_id, target_id, body.role)
    return {
        "invited": True,
        "member": {
            "userId": target_id,
            "name": target.get("name"),
            "email": target.get("email"),
            "wsRole": body.role,
        },
    }


@router.delete("/{ws_id}/members/{user_id}")
async def kick_member(
    ws_id: str,
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    ws = await _get_workspace_or_404(ws_id)
    _require_admin(ws, current_user)
    locale = await _get_user_locale(str(current_user["_id"]))
    if user_id == str(ws.get("ownerId")):
        raise HTTPException(status_code=403, detail=msg(locale, M.OWNER_CANNOT_BE_REMOVED))
    await remove_member(ws_id, user_id)
    return {"removed": True}


# ── Project ────────────────────────────────────────────────────────────────────

@router.get("/{ws_id}/projects")
async def list_workspace_projects(
    ws_id: str,
    current_user: dict = Depends(get_current_user),
):
    ws = await _get_workspace_or_404(ws_id)
    _require_membership(ws, current_user)
    projects = await list_projects(ws_id)
    return {"projects": [public_project(p) for p in projects]}


@router.post("/{ws_id}/projects", status_code=201)
async def create_new_project(
    ws_id: str,
    body: CreateProjectRequest,
    current_user: dict = Depends(get_current_user),
):
    ws = await _get_workspace_or_404(ws_id)
    _require_membership(ws, current_user)
    locale = await _get_user_locale(str(current_user["_id"]))
    try:
        project = await create_project(ws_id, body.name, body.key, str(current_user["_id"]))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Create project failed: {e}")
        raise HTTPException(status_code=500, detail=msg(locale, M.FAILED_CREATE_PROJECT))
    return public_project(project)


@router.patch("/{ws_id}/projects/{project_id}")
async def rename_workspace_project(    ws_id: str,
    project_id: str,
    body: UpdateProjectRequest,
    current_user: dict = Depends(get_current_user),
):
    """Rename nama project (admin workspace). Slug & key tidak berubah —
    URL lama dan nomor tiket (KEY-N) tetap valid."""
    ws = await _get_workspace_or_404(ws_id)
    _require_admin(ws, current_user)
    locale = await _get_user_locale(str(current_user["_id"]))
    # Pastikan project memang milik workspace ini (bukan project workspace lain)
    project = await find_project_by_id(project_id)
    if project is None or str(project.get("workspaceId")) != ws_id:
        raise HTTPException(status_code=404, detail=msg(locale, M.PROJECT_NOT_FOUND))
    try:
        updated = await update_project(project_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail=msg(locale, M.PROJECT_NOT_FOUND))
    return public_project(updated)


@router.delete("/{ws_id}/projects/{project_id}")
async def delete_workspace_project(
    ws_id: str,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Soft-delete project (admin workspace) — FE-8.4.

    - Project ditandai deletedAt + slug/key di-rename (bisa dipakai project baru)
    - Semua service ter-link DILEPAS (library tetap utuh)
    - projectId di-$pull dari observability/notification targets
    - Tiket & chat ikut terarsip (data utuh, guard menutup akses)
    """
    from services.service_store import detach_project_refs

    ws = await _get_workspace_or_404(ws_id)
    _require_admin(ws, current_user)
    locale = await _get_user_locale(str(current_user["_id"]))
    user_id = str(current_user["_id"])

    # Pastikan project milik workspace ini dan masih aktif
    project = await find_project_by_id(project_id)
    if project is None or str(project.get("workspaceId")) != ws_id:
        raise HTTPException(status_code=404, detail=msg(locale, M.PROJECT_NOT_FOUND))

    # 1. Lepas semua service refs
    detached = await detach_project_refs(project_id)

    # 2. $pull projectId dari targets (observability + notification)
    db = get_db()
    r_obs = await db["observability_targets"].update_many(
        {"project_ids": project_id}, {"$pull": {"project_ids": project_id}}
    )
    r_notif = await db["notification_targets"].update_many(
        {"project_ids": project_id}, {"$pull": {"project_ids": project_id}}
    )

    # 3. Soft-delete
    deleted = await soft_delete_project(project_id, user_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail=msg(locale, M.PROJECT_NOT_FOUND))

    logger.info(
        f"Project '{project.get('name')}' soft-deleted by {current_user.get('email')} — "
        f"services detached={detached}, obs targets pulled={r_obs.modified_count}, "
        f"notif targets pulled={r_notif.modified_count}"
    )
    return {
        "deleted": project_id,
        "slugRenamedTo": deleted.get("slug"),
        "servicesDetached": detached,
        "targetsUpdated": r_obs.modified_count + r_notif.modified_count,
        "note": msg(locale, M.ARCHIVE_NOTE),
    }
