"""
Secret Crypto — enkripsi at-rest untuk secret notification channel (Fix: Email channel).

Pola identik `services/llm_config_store.py` (Fernet + master key `DATA_ENCRYPTION_KEY`),
tapi BEST-EFFORT: tanpa key di .env, secret disimpan plaintext + logger.warning
(dev tanpa key tidak crash). Nilai terenkripsi diberi prefix `f:` agar bisa dibedakan
dari legacy plaintext (lazy migrate on read).

Dipakai `notification_store` (smtp_pass, bot_token) — bukan mengganti `llm_config_store`
yang strict (tetap butuh key wajib untuk LLM keys).
"""
from __future__ import annotations

import logging
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

_PREFIX = "f:"


def _fernet():
    from cryptography.fernet import Fernet

    key = (settings.data_encryption_key or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception as e:
        logger.warning(f"[SecretCrypto] DATA_ENCRYPTION_KEY tidak valid: {e}")
        return None


def has_key() -> bool:
    return _fernet() is not None


def encrypt_secret(plain: Optional[str]) -> Optional[str]:
    """Enkripsi best-effort. Tanpa key → plaintext + warning. None bila input None/kosong."""
    if not plain:
        return None
    f = _fernet()
    if f is None:
        logger.warning("[SecretCrypto] DATA_ENCRYPTION_KEY kosong — secret disimpan PLAINTEXT (dev only)")
        return plain
    try:
        return _PREFIX + f.encrypt(plain.encode()).decode()
    except Exception as e:
        logger.error(f"[SecretCrypto] encrypt gagal: {e}")
        return plain


def decrypt_secret(token: Optional[str]) -> Optional[str]:
    """Dekripsi. Prefix `f:` → Fernet; tanpa prefix → legacy plaintext (return as-is)."""
    if not token:
        return None
    if not token.startswith(_PREFIX):
        return token  # legacy plaintext (belum pernah di-encrypt)
    f = _fernet()
    if f is None:
        logger.error("[SecretCrypto] DATA_ENCRYPTION_KEY hilang — tidak bisa dekripsi secret terenkripsi")
        return None
    try:
        return f.decrypt(token[len(_PREFIX):].encode()).decode()
    except Exception as e:
        logger.error(f"[SecretCrypto] decrypt gagal (master key salah/hilang?): {e}")
        return None


def reencrypt_if_needed(plain_or_enc: Optional[str]) -> Optional[str]:
    """Migrasi on-update: nilai terenkripsi dibiarkan; plaintext di-encrypt (lazy migrate)."""
    if not plain_or_enc:
        return None
    if plain_or_enc.startswith(_PREFIX):
        return plain_or_enc
    return encrypt_secret(plain_or_enc)
