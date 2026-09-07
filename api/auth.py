"""
Auth router — FE-1 Fondasi & Auth.
POST /auth/register — user pertama otomatis admin
POST /auth/login    — JWT access token
GET  /auth/me       — profil user dari token
"""
import logging

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from api.deps import get_current_user
from api.messages import msg, M
from services.user_store import (
    EMAIL_RE,
    create_token,
    create_user,
    find_by_email,
    get_user_locale,
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
        raise HTTPException(status_code=409, detail=msg("id", M.EMAIL_ALREADY_REGISTERED))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Register failed: {e}")
        raise HTTPException(status_code=500, detail=msg("id", M.FAILED_CREATE_USER))
    return AuthResponse(token=create_token(user), user=public_user(user))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    """Login dengan email+password → JWT token."""
    user = await find_by_email(body.email)
    if user is None or not verify_password(body.password, user.get("passwordHash", "")):
        raise HTTPException(status_code=401, detail=msg("id", M.INVALID_CREDENTIALS))
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
        raise HTTPException(status_code=400, detail=msg("id", M.INVALID_LOCALE))
    ok = await update_locale(str(current_user["_id"]), body.localePreference)
    if not ok:
        raise HTTPException(status_code=404, detail=msg("id", M.USER_NOT_FOUND))
    return {"localePreference": body.localePreference}


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.patch("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update nama atau email user."""
    from bson import ObjectId
    from services.user_store import USERS_COLLECTION, get_db, public_user

    user_id = str(current_user["_id"])
    locale = await get_user_locale(user_id)
    oid = ObjectId(user_id) if len(user_id) == 24 else None
    if oid is None:
        raise HTTPException(status_code=404, detail=msg(locale, M.USER_NOT_FOUND))

    update_data = {}
    if body.name is not None:
        name = body.name.strip()
        if len(name) < 2:
            raise HTTPException(status_code=422, detail=msg(locale, M.NAME_TOO_SHORT))
        update_data["name"] = name

    if body.email is not None:
        email = body.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail=msg(locale, M.INVALID_EMAIL_FORMAT))
        # Check if email already exists
        existing = await find_by_email(email)
        if existing and str(existing["_id"]) != user_id:
            raise HTTPException(status_code=409, detail=msg(locale, M.EMAIL_ALREADY_REGISTERED))
        update_data["email"] = email

    if not update_data:
        raise HTTPException(status_code=422, detail=msg(locale, M.NO_DATA_TO_UPDATE))

    db = get_db()
    result = await db[USERS_COLLECTION].update_one({"_id": oid}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=msg(locale, M.USER_NOT_FOUND))

    # Return updated user
    updated_user = await get_db()[USERS_COLLECTION].find_one({"_id": oid})
    return {"user": public_user(updated_user)}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """Ganti password user."""
    from bson import ObjectId
    from services.user_store import USERS_COLLECTION, get_db, hash_password

    user_id = str(current_user["_id"])
    locale = await get_user_locale(user_id)
    oid = ObjectId(user_id) if len(user_id) == 24 else None
    if oid is None:
        raise HTTPException(status_code=404, detail=msg(locale, M.USER_NOT_FOUND))

    # Verify current password
    if not verify_password(body.current_password, current_user.get("passwordHash", "")):
        raise HTTPException(status_code=400, detail=msg(locale, M.CURRENT_PASSWORD_WRONG))

    # Validate new password
    if not body.new_password or len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail=msg(locale, M.PASSWORD_TOO_SHORT))

    # Update password
    db = get_db()
    result = await db[USERS_COLLECTION].update_one(
        {"_id": oid}, {"$set": {"passwordHash": hash_password(body.new_password)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=msg(locale, M.USER_NOT_FOUND))

    return {"message": msg(locale, M.PASSWORD_CHANGED)}
