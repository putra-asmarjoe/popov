"""
API Keys Management Router — CRUD endpoints for API key management.

All endpoints require JWT auth (admin only).
Key is shown ONLY at creation time.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user, require_admin
from services import api_key_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


# ── Request Schema ───────────────────────────────────────────────────────────

class ApiKeyCreateRequest(BaseModel):
    """Create new API key."""
    name: str                          # "n8n Production"
    key_type: str = "web"              # "web" | "public"
    scopes: Optional[List[str]] = None  # None = default scopes per type
    expires_at: Optional[str] = None   # ISO datetime or null
    rate_limit: Optional[int] = None   # req/hour or null (default per type)


class ApiKeyUpdateRequest(BaseModel):
    """Update API key metadata."""
    name: Optional[str] = None
    scopes: Optional[List[str]] = None
    expires_at: Optional[str] = None
    rate_limit: Optional[int] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_api_keys(
    ws_id: str,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    """List all API keys for workspace (admin only)."""
    keys = await api_key_store.list_keys(ws_id)
    return {"items": keys}


@router.post("")
async def create_api_key(
    ws_id: str,
    body: ApiKeyCreateRequest,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    """
    Create new API key (admin only).

    ⚠️ Key is shown ONLY at creation time. Copy it immediately.
    """
    if body.key_type not in ("web", "public"):
        raise HTTPException(400, "key_type harus 'web' atau 'public'")

    try:
        result = await api_key_store.create_key(
            workspace_id=ws_id,
            name=body.name,
            key_type=body.key_type,
            scopes=body.scopes,
            created_by=str(current_user["_id"]),
            expires_at=body.expires_at,
            rate_limit=body.rate_limit,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"[APIKeys] Create failed: {e}")
        raise HTTPException(500, "Gagal membuat API key")

    return result


@router.get("/{key_id}")
async def get_api_key(
    ws_id: str,
    key_id: str,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    """Get API key details (admin only, no plaintext)."""
    key = await api_key_store.get_key(key_id)
    if not key:
        raise HTTPException(404, "API key tidak ditemukan")
    if key.get("workspaceId") != ws_id:
        raise HTTPException(404, "API key tidak ditemukan")
    return key


@router.patch("/{key_id}")
async def update_api_key(
    ws_id: str,
    key_id: str,
    body: ApiKeyUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    """Update API key metadata (admin only)."""
    key = await api_key_store.get_key(key_id)
    if not key:
        raise HTTPException(404, "API key tidak ditemukan")
    if key.get("workspaceId") != ws_id:
        raise HTTPException(404, "API key tidak ditemukan")

    try:
        updated = await api_key_store.update_key(
            key_id=key_id,
            name=body.name,
            scopes=body.scopes,
            expires_at=body.expires_at,
            rate_limit=body.rate_limit,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return updated


@router.delete("/{key_id}")
async def revoke_api_key(
    ws_id: str,
    key_id: str,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    """Revoke (deactivate) API key (admin only)."""
    key = await api_key_store.get_key(key_id)
    if not key:
        raise HTTPException(404, "API key tidak ditemukan")
    if key.get("workspaceId") != ws_id:
        raise HTTPException(404, "API key tidak ditemukan")

    ok = await api_key_store.revoke_key(key_id)
    if not ok:
        raise HTTPException(500, "Gagal revoke API key")

    return {"status": "revoked", "key_id": key_id}


@router.post("/{key_id}/rotate")
async def rotate_api_key(
    ws_id: str,
    key_id: str,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    """
    Rotate API key (admin only).
    Revokes old key and creates new one with same settings.
    ⚠️ New key is shown ONLY at creation time.
    """
    key = await api_key_store.get_key(key_id)
    if not key:
        raise HTTPException(404, "API key tidak ditemukan")
    if key.get("workspaceId") != ws_id:
        raise HTTPException(404, "API key tidak ditemukan")

    try:
        new_key = await api_key_store.rotate_key(key_id)
    except Exception as e:
        logger.error(f"[APIKeys] Rotate failed: {e}")
        raise HTTPException(500, "Gagal rotate API key")

    if not new_key:
        raise HTTPException(500, "Gagal rotate API key")

    return new_key


@router.get("/scopes/list")
async def list_scopes():
    """List all available scopes and their descriptions."""
    return {"scopes": api_key_store.SCOPES}


@router.get("/endpoints/public")
async def list_public_endpoints():
    """List all registered public endpoints."""
    from api.public_routes import list_public_endpoints
    return {"endpoints": list_public_endpoints()}
