"""
startup_checks.py — Fix #294 (First Launch Setup)

Laporan kesehatan env saat boot. LOG ONLY — tidak pernah sys.exit.
Alasan: env punya default valid (config/settings.py), dan jika server mati,
setup wizard FE tidak bisa reach /api/v1/setup/status untuk memandu user.
Ops visibility tetap terjaga via Docker HEALTHCHECK / K8s readiness probe
yang men-query endpoint status tersebut.

Dipanggil pertama di lifespan() main.py, SEBELUM ensure_indexes().
"""
import logging

from config.settings import settings

logger = logging.getLogger(__name__)

# Harus identik dengan default settings.jwt_secret — dipakai untuk deteksi
# "masih memakai secret bawaan dev" di production.
_DEV_JWT_SECRET = "popov-dev-secret-change-me"


def validate_fernet_key(key: str) -> bool:
    """Reuse pola services/secret_crypto.py:27-31."""
    try:
        from cryptography.fernet import Fernet

        Fernet(key.encode() if isinstance(key, str) else key)
        return True
    except Exception:
        return False


async def _ping_mongodb() -> tuple[bool, str]:
    """Ping via client yang SAMA dengan app (get_client_for_uri) —
    jangan buka koneksi kedua. Error diringkas jadi type name saja agar
    URI+password tidak ikut tercetak ke log."""
    from services.mongodb_client import get_client_for_uri

    try:
        client = get_client_for_uri(settings.mongodb_uri)
        await client.admin.command("ping")
        return True, "ok"
    except Exception as e:  # noqa: BLE001 — banner, bukan crash path
        return False, type(e).__name__


async def run_startup_checks() -> None:
    """Banner kesehatan env ke log. Tidak raise, tidak exit."""
    errors: list[str] = []
    warnings: list[str] = []

    mongo_ok, mongo_err = await _ping_mongodb()
    if not mongo_ok:
        errors.append(
            f"  ✗ MongoDB unreachable ({mongo_err}) — is MongoDB running?\n"
            f"    → Cek MONGODB_URI di .env (db aktif: {settings.mongodb_db!r})"
        )

    enc_key = (settings.data_encryption_key or "").strip()
    if not enc_key:
        errors.append(
            "  ✗ DATA_ENCRYPTION_KEY is not set — secrets will be stored PLAINTEXT.\n"
            '    → Generate: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    elif not validate_fernet_key(enc_key):
        errors.append(
            "  ✗ DATA_ENCRYPTION_KEY is not a valid Fernet key.\n"
            "    ⚠  JANGAN regenerate bila sudah ada data terenkripsi di MongoDB —\n"
            "       LLM API keys yang tersimpan jadi unrecoverable."
        )

    jwt_secret = (settings.jwt_secret or "").strip()
    if not jwt_secret:
        warnings.append("  ⚠  JWT_SECRET is empty — auth tokens cannot be signed.")
    elif jwt_secret == _DEV_JWT_SECRET:
        warnings.append(
            "  ⚠  JWT_SECRET masih default dev — set secret asli untuk production.\n"
            "    → Generate: openssl rand -hex 32"
        )
    elif len(jwt_secret) < 32:
        warnings.append("  ⚠  JWT_SECRET < 32 chars — ok untuk dev, tidak untuk production.")

    border = "=" * 62
    if warnings:
        logger.warning(
            f"\n{border}\n  POPOV STARTUP WARNINGS\n{border}\n"
            + "\n".join(warnings)
            + f"\n{border}"
        )
    if errors:
        logger.error(
            f"\n{border}\n"
            "  POPOV STARTUP CHECKS FAILED (server tetap start —\n"
            "  buka web UI untuk panduan setup interaktif)\n"
            f"{border}\n"
            + "\n".join(errors)
            + f"\n{border}"
        )
    else:
        logger.info("✓ Startup checks passed — Popov is starting")
