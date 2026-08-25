"""
Auth router — FE-1 Fondasi & Auth.
POST /auth/register — user pertama otomatis admin
POST /auth/login    — JWT access token
GET  /auth/me       — profil user dari token
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from api.deps import get_current_user
from services.user_store import (
    create_token,
    create_user,
    find_by_email,
    public_user,
    update_locale,
    verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# MULTILANG_PLAN Fase 1 — perluas saat tambah bahasa (checklist Section 8)
VALID_LOCALES = {"en", "id"}


# ── Request / Response schema ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest):
    """Registrasi user baru. User PERTAMA otomatis role=admin."""
    try:
        user = await create_user(body.name, body.email, body.password)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Email sudah terdaftar")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Register failed: {e}")
        raise HTTPException(status_code=500, detail="Gagal membuat user")
    return AuthResponse(token=create_token(user), user=public_user(user))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    """Login dengan email+password → JWT token."""
    user = await find_by_email(body.email)
    if user is None or not verify_password(body.password, user.get("passwordHash", "")):
        raise HTTPException(status_code=401, detail="Email atau password salah")
    return AuthResponse(token=create_token(user), user=public_user(user))


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    """Profil user pemilik token."""
    return {"user": public_user(current_user)}


class LocalePreferenceRequest(BaseModel):
    localePreference: str


@router.patch("/preferences")
async def update_preferences(
    body: LocalePreferenceRequest,
    current_user: dict = Depends(get_current_user),
):
    """Simpan preferensi bahasa user (MULTILANG_PLAN Fase 1)."""
    if body.localePreference not in VALID_LOCALES:
        raise HTTPException(status_code=400, detail="Invalid locale")
    ok = await update_locale(str(current_user["_id"]), body.localePreference)
    if not ok:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    return {"localePreference": body.localePreference}
