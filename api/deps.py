"""
Shared API dependencies — FE-1.
get_current_user: validasi Bearer JWT → dokumen user (atau 401).
require_admin: khusus role admin global (dipakai FE-6 management panel).
get_current_principal: dual auth (JWT + API Key) untuk public API endpoints.
Dipakai semua router fase FE berikutnya (workspaces, tickets, chat, config).

Path-based auth:
  - /api/v1/* → JWT auth only (internal web app)
  - /api/pub/v1/*  → API Key auth only (external integrations)
"""
import logging
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request

from services.user_store import decode_token, get_user

logger = logging.getLogger(__name__)


# ── i18n for Public API Auth Errors ──────────────────────────────────────────

_AUTH_MESSAGES = {
    "en": {
        "api_key_required": "Public API requires API key (pk_pub_*)",
        "api_key_invalid": "API key is invalid or expired",
        "endpoint_not_found": "Endpoint not available: {method} {path}",
        "scope_required": "API key missing required scope: {scopes}",
        "rate_limited": "Rate limit exceeded. Try again in {retry_after} seconds.",
        "jwt_required": "Public API does not accept JWT tokens",
    },
    "id": {
        "api_key_required": "Public API membutuhkan API key (pk_pub_*)",
        "api_key_invalid": "API key tidak valid atau kadaluarsa",
        "endpoint_not_found": "Endpoint tidak tersedia: {method} {path}",
        "scope_required": "API key tidak memiliki scope yang diperlukan: {scopes}",
        "rate_limited": "Rate limit exceeded. Coba lagi dalam {retry_after} detik.",
        "jwt_required": "Public API tidak menerima JWT tokens",
    },
}


def _auth_msg(request: Request, key: str, **kwargs) -> str:
    """Return localized auth error message (default: en)."""
    accept_lang = request.headers.get("accept-language", "")
    locale = "id" if accept_lang.startswith("id") else "en"
    lang = _AUTH_MESSAGES.get(locale, _AUTH_MESSAGES["en"])
    return lang.get(key, _AUTH_MESSAGES["en"].get(key, key)).format(**kwargs)


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


# ── Dual Auth: JWT + API Key ─────────────────────────────────────────────────

class Principal:
    """Unified auth principal — JWT or API Key."""

    def __init__(self, type: str, user: Optional[Dict] = None, api_key: Optional[Dict] = None):
        self.type = type  # "jwt" | "api_key"
        self.user = user
        self.api_key = api_key

    @property
    def is_jwt(self) -> bool:
        return self.type == "jwt"

    @property
    def is_api_key(self) -> bool:
        return self.type == "api_key"

    @property
    def workspace_id(self) -> Optional[str]:
        if self.is_api_key and self.api_key:
            return self.api_key.get("workspaceId")
        return None

    @property
    def user_id(self) -> Optional[str]:
        if self.is_jwt and self.user:
            return str(self.user.get("_id"))
        return None


async def get_current_principal(request: Request) -> Principal:
    """
    Path-based auth dependency:
      - /api/pub/v1/*  → API Key only (pk_pub_*)
      - /api/v1/* → JWT only (web app)
    """
    from api.public_routes import get_public_endpoint_config
    from services.api_key_store import check_rate_limit, verify_key

    path = request.url.path
    method = request.method
    auth = request.headers.get("Authorization", "")

    # ── Public API (/api/pub/v1/*) → API Key only ──────────────────────────
    if path.startswith("/api/pub/"):
        if not auth.startswith("Bearer pk_"):
            raise HTTPException(
                status_code=401,
                detail=_auth_msg(request, "api_key_required")
            )

        key = auth[7:]
        principal_data = await verify_key(key)
        if not principal_data:
            raise HTTPException(status_code=401, detail=_auth_msg(request, "api_key_invalid"))

        # Check endpoint is registered
        endpoint_config = get_public_endpoint_config(method, path)
        if not endpoint_config:
            raise HTTPException(
                status_code=404,
                detail=_auth_msg(request, "endpoint_not_found", method=method, path=path)
            )

        # Check scope
        key_scopes = principal_data.get("scopes", [])
        required_scopes = endpoint_config.get("scopes", [])
        if not any(s in key_scopes for s in required_scopes):
            raise HTTPException(
                status_code=403,
                detail=_auth_msg(request, "scope_required", scopes=required_scopes)
            )

        # Rate limit
        rate_limit = principal_data.get("rate_limit", endpoint_config.get("rate_limit", 200))
        allowed, retry_after = check_rate_limit(principal_data["id"], rate_limit)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=_auth_msg(request, "rate_limited", retry_after=retry_after),
                headers={"Retry-After": str(retry_after)}
            )

        return Principal(type="api_key", api_key=principal_data)

    # ── Internal API (/api/v1/*) → JWT only ───────────────────────────
    if path.startswith("/api/"):
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing authorization header")

        token = auth[7:]
        payload = decode_token(token)
        if payload is None:
            raise HTTPException(status_code=401, detail="Token tidak valid atau kadaluarsa")
        user = await get_user(payload.get("sub", ""))
        if user is None:
            raise HTTPException(status_code=401, detail="User tidak ditemukan")
        return Principal(type="jwt", user=user)

    # ── Fallback: old /api/v1/* → try JWT (backward compat) ─────────────────
    if auth.startswith("Bearer pk_"):
        key = auth[7:]
        principal_data = await verify_key(key)
        if not principal_data:
            raise HTTPException(status_code=401, detail="API key tidak valid atau kadaluarsa")

        endpoint_config = get_public_endpoint_config(method, path)
        if endpoint_config:
            key_scopes = principal_data.get("scopes", [])
            required_scopes = endpoint_config.get("scopes", [])
            if not any(s in key_scopes for s in required_scopes):
                raise HTTPException(
                    status_code=403,
                    detail=f"API key tidak memiliki scope yang diperlukan: {required_scopes}"
                )
            rate_limit = principal_data.get("rate_limit", endpoint_config.get("rate_limit", 200))
            allowed, retry_after = check_rate_limit(principal_data["id"], rate_limit)
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Coba lagi dalam {retry_after} detik.",
                    headers={"Retry-After": str(retry_after)}
                )
        elif principal_data.get("type") != "web":
            raise HTTPException(
                status_code=403,
                detail="Endpoint tidak tersedia untuk public API keys"
            )

        return Principal(type="api_key", api_key=principal_data)

    elif auth.startswith("Bearer "):
        token = auth[7:]
        payload = decode_token(token)
        if payload is None:
            raise HTTPException(status_code=401, detail="Token tidak valid atau kadaluarsa")
        user = await get_user(payload.get("sub", ""))
        if user is None:
            raise HTTPException(status_code=401, detail="User tidak ditemukan")
        return Principal(type="jwt", user=user)

    else:
        raise HTTPException(status_code=401, detail="Missing authorization header")
