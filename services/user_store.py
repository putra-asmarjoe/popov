"""
User store — FE-1 Fondasi & Auth.
Collection: users (db popovagent_db). Field: name, email, passwordHash, role, createdAt.

User PERTAMA yang register otomatis role=admin, sisanya member.
Respons ke client tidak boleh mengandung passwordHash (gunakan public_user()).
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from passlib.context import CryptContext
from pymongo.errors import DuplicateKeyError

from config.settings import settings
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

USERS_COLLECTION = "users"

# bcrypt — passlib 1.7.4 kompatibel dengan bcrypt <4.1 (lihat pyproject pin)
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── Password & JWT helpers ────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:
        return False


def create_token(user: Dict[str, Any]) -> str:
    """Buat JWT access token (HS256, exp sesuai JWT_EXPIRY_HOURS)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["_id"]),
        "email": user["email"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expiry_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode + validasi JWT. None bila kadaluarsa/tidak valid."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ── Serialisasi ───────────────────────────────────────────────────────────────

def public_user(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Dokumen user aman untuk dikirim ke client (tanpa passwordHash)."""
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "email": doc.get("email", ""),
        "role": doc.get("role", "member"),
        "localePreference": doc.get("locale_preference") or "en",
        "createdAt": doc.get("createdAt"),
    }


async def update_locale(user_id: str, locale: str) -> bool:
    """Simpan preferensi bahasa user (Fix #90 / MULTILANG_PLAN Fase 1)."""
    from bson import ObjectId

    oid = ObjectId(user_id) if len(user_id) == 24 else None
    if oid is None:
        return False
    db = get_db()
    result = await db[USERS_COLLECTION].update_one(
        {"_id": oid}, {"$set": {"locale_preference": locale}}
    )
    return result.matched_count > 0


async def get_user_locale(user_id: Optional[str]) -> str:
    """Preferensi bahasa user ("en"/"id") utk pesan fallback backend (Fix #113).
    user_id bukan ObjectId / tidak ditemukan → "id" (perilaku legacy pesan ID)."""
    try:
        from bson import ObjectId
        if not user_id or len(str(user_id)) != 24:
            return "id"
        doc = await get_db()[USERS_COLLECTION].find_one(
            {"_id": ObjectId(str(user_id))}, {"locale_preference": 1}
        )
        loc = (doc or {}).get("locale_preference") or "id"
        return loc if loc in ("en", "id") else "id"
    except Exception:
        return "id"


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def ensure_user_indexes() -> None:
    db = get_db()
    await db[USERS_COLLECTION].create_index("email", unique=True)
    logger.info("User indexes ensured (users.email unique)")


async def find_by_email(email: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    return await db[USERS_COLLECTION].find_one({"email": email.strip().lower()})


async def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    from bson import ObjectId
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None
    db = get_db()
    return await db[USERS_COLLECTION].find_one({"_id": oid})


async def count_users() -> int:
    db = get_db()
    return await db[USERS_COLLECTION].count_documents({})


async def create_user(name: str, email: str, password: str) -> Dict[str, Any]:
    """
    Buat user baru. User pertama → admin, sisanya member.

    Returns:
        Dokumen user baru (public_user-ready).
    Raises:
        ValueError — input tidak valid (nama/email/password kosong, email format salah).
        DuplicateKeyError — email sudah terdaftar.
    """
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name or len(name) < 2:
        raise ValueError("Nama minimal 2 karakter")
    if not EMAIL_RE.match(email):
        raise ValueError("Format email tidak valid")
    if not password or len(password) < 8:
        raise ValueError("Password minimal 8 karakter")

    # User pertama jadi admin (bootstrap tanpa seed script)
    role = "admin" if await count_users() == 0 else "member"

    doc = {
        "name": name,
        "email": email,
        "passwordHash": hash_password(password),
        "role": role,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    db = get_db()
    try:
        result = await db[USERS_COLLECTION].insert_one(doc)
    except DuplicateKeyError:
        raise
    doc["_id"] = result.inserted_id
    logger.info(f"User created: {email} (role={role})")
    return doc
