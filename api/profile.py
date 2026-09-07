"""User Profile API — Phase 1 (USER_PROFILE_PLAN.md §3).

GET    /api/v1/profile?workspace_id=...     → profil (manual fields + counters)
PATCH  /api/v1/profile?workspace_id=...     → set manual fields (enum-validated)
DELETE /api/v1/profile/counters?workspace_id=... → reset counter pasif

Scope: user pemilik profil sendiri (JWT). Workspace di-validasi membership —
profil per (user_id, workspace_id), TIDAK global (plan D6/D7).
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_current_user
from services.user_profile import (
    get_profile,
    reset_counters,
    set_manual_fields,
)

router = APIRouter(tags=["profile"])


async def _require_workspace_member(workspace_id: Optional[str], user: Dict[str, Any]) -> str:
    """Validasi workspace_id ada + user member. Return workspace_id (str)."""
    if not workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required")
    try:
        from services.workspace_store import find_workspace_by_id, get_membership

        ws = await find_workspace_by_id(workspace_id)
        if ws is None or get_membership(ws, str(user["_id"])) is None:
            raise HTTPException(status_code=403, detail="Not a member of this workspace")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workspace check failed: {e}")
    return str(workspace_id)


@router.get("/profile")
async def get_my_profile(
    workspace_id: str = Query(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    ws = await _require_workspace_member(workspace_id, current_user)
    return await get_profile(str(current_user["_id"]), ws)


@router.patch("/profile")
async def update_my_profile(
    body: Dict[str, Any],
    workspace_id: str = Query(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    ws = await _require_workspace_member(workspace_id, current_user)
    allowed = ("verbosity", "tone", "format_preference", "default_chat_depth")
    fields = {k: v for k, v in (body or {}).items() if k in allowed}
    if not fields:
        raise HTTPException(status_code=422, detail="No valid profile fields in body")
    try:
        return await set_manual_fields(str(current_user["_id"]), ws, fields)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/profile/counters")
async def reset_my_counters(
    workspace_id: str = Query(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    ws = await _require_workspace_member(workspace_id, current_user)
    return await reset_counters(str(current_user["_id"]), ws)


# ── Phase 4: batch inferensi — approve/reject saran ───────────────────────────

@router.post("/profile/inference/approve")
async def approve_profile_inference(
    workspace_id: str = Query(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Approve saran batch (pending_suggestion) → field jadi manual (D3)."""
    ws = await _require_workspace_member(workspace_id, current_user)
    try:
        from services.user_profile_infer import apply_pending

        return await apply_pending(str(current_user["_id"]), ws)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/profile/inference/reject")
async def reject_profile_inference(
    workspace_id: str = Query(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Tolak saran batch → pending dibuang + baseline reset (tidak auto-apply)."""
    ws = await _require_workspace_member(workspace_id, current_user)
    from services.user_profile_infer import reject_pending

    ok = await reject_pending(str(current_user["_id"]), ws)
    if not ok:
        raise HTTPException(status_code=422, detail="No pending suggestion to reject")
    return await get_profile(str(current_user["_id"]), ws)
