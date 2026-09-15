"""
api/setup_api.py — Fix #294 (First Launch Setup)

GET  /api/v1/setup/status    — unauthenticated. Dipakai setup wizard FE,
                              Docker HEALTHCHECK, dan K8s readiness probe.
POST /api/v1/setup/configure — unauthenticated. Tulis .env dari wizard.
                              Validasi MongoDB connection sebelum write.

SECURITY: endpoint tanpa auth — JANGAN bocorkan MONGODB_URI, password,
atau exception mentah. Semua error di-map ke type name singkat.
"""
import logging
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import settings
from services.mongodb_client import get_client_for_uri, get_db
from services.user_store import USERS_COLLECTION
from startup_checks import validate_fernet_key, _DEV_JWT_SECRET

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/setup", tags=["setup"])

# Lokasi .env — project root (satu level di atas api/).
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _detect_needs_configuration() -> bool:
    """True bila .env tidak ada atau ada critical var yang belum di-set.

    Critical var: MONGODB_URI, MONGODB_DB, JWT_SECRET, DATA_ENCRYPTION_KEY.
    Dipakai oleh /status dan startup_checks.
    """
    if not _ENV_PATH.exists():
        return True
    enc_key = (settings.data_encryption_key or "").strip()
    jwt_secret = (settings.jwt_secret or "").strip()
    mongo_uri = (settings.mongodb_uri or "").strip()
    mongo_db = (settings.mongodb_db or "").strip()
    return not (enc_key and jwt_secret and mongo_uri and mongo_db)


# ── Request schema ───────────────────────────────────────────────────────────


class SetupConfig(BaseModel):
    """Body POST /setup/configure. Semua field optional kecuali mongodb_uri."""
    mongodb_uri: str
    mongodb_db: str = "popovagent"
    jwt_secret: str = ""       # auto-generate bila kosong
    data_encryption_key: str = ""  # auto-generate bila kosong (Fernet)


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/status")
async def setup_status():
    """
    Response shape stabil — FE wizard & K8s readiness bergantung pada field ini.
    needs_setup  = belum ada user sama sekali (first launch).
    needs_configuration = .env belum ada / critical var kosong.
    """
    # MongoDB — reuse koneksi existing app, JANGAN buka koneksi baru
    mongo_ok, mongo_err = True, None
    try:
        client = get_client_for_uri(settings.mongodb_uri)
        await client.admin.command("ping")
    except Exception as e:  # noqa: BLE001 — status endpoint, bukan crash path
        mongo_ok, mongo_err = False, type(e).__name__

    enc_key = (settings.data_encryption_key or "").strip()
    jwt_secret = (settings.jwt_secret or "").strip()

    first_user_exists = await get_db()[USERS_COLLECTION].count_documents({}) > 0
    needs_configuration = _detect_needs_configuration()

    return {
        "status": "ok" if mongo_ok else "degraded",
        "needs_setup": not first_user_exists,
        "needs_configuration": needs_configuration,
        "configured": bool(enc_key) and bool(jwt_secret) and mongo_ok,
        "mongodb": {
            "connected": mongo_ok,
            "db": settings.mongodb_db,
            "error": mongo_err,
        },
        "encryption_key": {
            "set": bool(enc_key),
            "valid": validate_fernet_key(enc_key) if enc_key else False,
        },
        "jwt_secret": {
            "set": bool(jwt_secret),
            "strong": bool(jwt_secret) and len(jwt_secret) >= 32,
            "is_default": jwt_secret == _DEV_JWT_SECRET,
        },
        "first_user_registered": first_user_exists,
    }


@router.post("/configure")
async def configure_env(config: SetupConfig):
    """
    Tulis .env file dengan nilai dari wizard.
    - Validasi MongoDB connection SEBELUM tulis .env.
    - Generate Fernet key dan JWT secret bila kosong.
    - Return success → FE reload page → server baca .env baru.
    """
    # ── 1. Validasi MongoDB URI ───────────────────────────────────────────
    try:
        client = get_client_for_uri(config.mongodb_uri)
        await client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        logger.warning("Setup configure: MongoDB connection failed (%s)", type(e).__name__)
        raise HTTPException(
            status_code=400,
            detail="Cannot connect to MongoDB. "
                   "Check your connection string and try again.",
        )

    # ── 2. Generate secrets bila kosong ───────────────────────────────────
    jwt_secret = config.jwt_secret.strip() or secrets.token_hex(32)
    enc_key = config.data_encryption_key.strip()

    if not enc_key:
        enc_key = Fernet.generate_key().decode()
    else:
        # Validasi Fernet key yang diisi user
        if not validate_fernet_key(enc_key):
            raise HTTPException(
                status_code=400,
                detail="DATA_ENCRYPTION_KEY is not a valid Fernet key. "
                       "Leave empty to auto-generate, or provide a valid key.",
            )

    # ── 3. Validasi input: no newline injection ─────────────────────────
    fields_to_check = [
        ("mongodb_uri", config.mongodb_uri),
        ("mongodb_db", config.mongodb_db),
        ("jwt_secret", config.jwt_secret),
        ("data_encryption_key", config.data_encryption_key),
    ]
    for field_name, value in fields_to_check:
        if "\n" in value or "\r" in value:
            raise HTTPException(
                status_code=400,
                detail="Input contains invalid characters",
            )

    # Strip whitespace from all values
    config.mongodb_uri = config.mongodb_uri.strip()
    config.mongodb_db = config.mongodb_db.strip() or "popovagent"

    # ── 4. Tulis .env ────────────────────────────────────────────────────
    env_content = (
        f"# Auto-generated by Popov setup wizard\n"
        f"MONGODB_URI={config.mongodb_uri}\n"
        f"MONGODB_DB={config.mongodb_db}\n"
        f"JWT_SECRET={jwt_secret}\n"
        f"DATA_ENCRYPTION_KEY={enc_key}\n"
    )

    try:
        _ENV_PATH.write_text(env_content, encoding="utf-8")
        _ENV_PATH.chmod(0o600)  # owner-only read/write
    except OSError as e:
        logger.error("Setup configure: failed to write .env: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to write .env file",
        )

    # ── 5. Update settings in-memory agar backend langsung menggunakan config baru ──
    settings.mongodb_uri = config.mongodb_uri
    settings.mongodb_db = config.mongodb_db
    settings.jwt_secret = jwt_secret
    settings.data_encryption_key = enc_key

    logger.info(
        "Setup configure: .env written at %s (mongodb_db=%s, jwt_generated=%s, enc_key_generated=%s)",
        _ENV_PATH,
        config.mongodb_db,
        not config.jwt_secret.strip(),
        not config.data_encryption_key.strip(),
    )

    return {
        "success": True,
        "message": "Configuration saved. Memory settings updated.",
    }
