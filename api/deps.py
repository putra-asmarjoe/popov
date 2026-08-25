"""
Shared API dependencies — FE-1.
get_current_user: validasi Bearer JWT → dokumen user (atau 401).
require_admin: khusus role admin global (dipakai FE-6 management panel).
Dipakai semua router fase FE berikutnya (workspaces, tickets, chat, config).
"""
import logging
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException

from services.user_store import decode_token, get_user

logger = logging.getLogger(__name__)


async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Dependency FastAPI: ekstrak user dari header Authorization: Bearer <JWT>."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token tidak valid atau kadaluarsa")
    user = await get_user(payload.get("sub", ""))
    if user is None:
        raise HTTPException(status_code=401, detail="User tidak ditemukan")
    return user


async def require_admin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency: hanya user role=admin (403 untuk lainnya) — FE-6 management."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Hanya admin yang boleh mengakses")
    return current_user


async def require_ws_admin_or_global(
    ws_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Fix #41: akses edit registry level workspace.
    Global admin ATAU ws-admin workspace terkait yang boleh lewat; selain itu 403.
    """
    if current_user.get("role") == "admin":
        return current_user
    from services.workspace_store import find_workspace_by_id, is_workspace_admin

    ws = await find_workspace_by_id(ws_id)
    if ws and is_workspace_admin(ws, str(current_user["_id"])):
        return current_user
    raise HTTPException(status_code=403, detail="Hanya workspace admin yang boleh mengakses")
