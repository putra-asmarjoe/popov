"""
Webhook Validator — SCALE_ESCALATION_PLAN Layer 2 (L2-2/L2-3)

Validasi header X-Alertmanager-Token per-tenant untuk endpoint
POST /api/v1/webhook/alert/{observ_id}.

Token disimpan sebagai sha256 hash di observability_targets.webhook_secret_hash
(bukan plaintext). Compare constant-time via hmac.compare_digest.
"""
from __future__ import annotations

import logging
from typing import Optional

from services.observability_store import get_target, hash_token

logger = logging.getLogger(__name__)


async def validate_alertmanager_token(observ_id: str, token: Optional[str]) -> Optional[dict]:
    """
    Return target dict bila observ_id ada + enabled + token cocok.
    None bila target tidak ditemukan / disabled / token salah / hilang.
    Endpoint wajib membedakan hanya 404 vs 401 — jangan bocorkan detail.
    """
    import hmac
    if not token:
        return None
    target = await get_target(observ_id)
    if not target or not target.get("enabled", True):
        return None
    stored_hash = target.get("webhook_secret_hash")
    if not stored_hash:
        return None
    if not hmac.compare_digest(hash_token(token), stored_hash):
        logger.warning(f"[WebhookValidator] invalid token for observ_id={observ_id}")
        return None
    return target