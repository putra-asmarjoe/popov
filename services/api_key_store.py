"""
API Key Store — Modular API Key Management.

Collection: api_keys
Schema:
    _id, workspaceId, name, type ("web"|"public"), key_hash (bcrypt),
    key_prefix, scopes[], created_by, last_used_at, expires_at,
    rate_limit, is_active, created_at

Key format:
    pk_web_<token>  — web/internal keys (full access)
    pk_pub_<token>  — public/external keys (limited scopes, stricter rate limit)

Security:
    - Plaintext key shown ONLY at creation time
    - Stored as bcrypt hash (never plaintext)
    - Rate limiting per key (in-memory sliding window)
"""
import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from passlib.context import CryptContext

from config.settings import settings
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

COLLECTION = "api_keys"

# bcrypt — reuse same context as user_store
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Key Generation ───────────────────────────────────────────────────────────

def generate_api_key(key_type: str = "web") -> tuple[str, str, str]:
    """
    Generate new API key.
    Returns: (plaintext_key, key_hash, key_prefix)
    """
    token = secrets.token_urlsafe(32)
    prefix = f"pk_{key_type[:3]}_"  # pk_web_ or pk_pub_
    plaintext = f"{prefix}{token}"
    key_hash = _pwd_context.hash(plaintext)
    key_prefix = plaintext[:12] + "..."  # pk_web_xxxx...
    return plaintext, key_hash, key_prefix


def hash_api_key(plaintext: str) -> str:
    """Hash API key for verification (bcrypt)."""
    return _pwd_context.hash(plaintext)


def verify_api_key_hash(plaintext: str, key_hash: str) -> bool:
    """Verify plaintext against stored bcrypt hash."""
    try:
        return _pwd_context.verify(plaintext, key_hash)
    except Exception:
        return False


# ── Rate Limiting (in-memory sliding window) ─────────────────────────────────

class _RateLimiter:
    """In-memory sliding window rate limiter per API key."""

    def __init__(self):
        self._windows: Dict[str, List[float]] = {}
        self._cleanup_interval = 300  # 5 min
        self._last_cleanup = time.time()

    def _cleanup(self):
        """Remove old entries periodically."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        cutoff = now - 3600  # 1 hour window
        for key_id in list(self._windows.keys()):
            self._windows[key_id] = [
                t for t in self._windows[key_id] if t > cutoff
            ]
            if not self._windows[key_id]:
                del self._windows[key_id]

    def check(self, key_id: str, rate_limit: int) -> tuple[bool, int]:
        """
        Check rate limit for a key.
        Returns: (allowed, retry_after_seconds)
        """
        self._cleanup()
        now = time.time()
        cutoff = now - 3600  # 1 hour window

        if key_id not in self._windows:
            self._windows[key_id] = []

        # Remove old entries
        self._windows[key_id] = [
            t for t in self._windows[key_id] if t > cutoff
        ]

        if len(self._windows[key_id]) >= rate_limit:
            # Rate limit exceeded
            oldest = self._windows[key_id][0]
            retry_after = int(oldest + 3600 - now) + 1
            return False, retry_after

        # Allow request
        self._windows[key_id].append(now)
        return True, 0

    def reset(self, key_id: str):
        """Reset rate limit window for a key."""
        self._windows.pop(key_id, None)


_rate_limiter = _RateLimiter()


def check_rate_limit(key_id: str, rate_limit: int) -> tuple[bool, int]:
    """Check rate limit for a key. Returns (allowed, retry_after_seconds)."""
    return _rate_limiter.check(key_id, rate_limit)


def reset_rate_limit(key_id: str):
    """Reset rate limit for a key."""
    _rate_limiter.reset(key_id)


# ── Scopes ───────────────────────────────────────────────────────────────────

SCOPES = {
    "knowledge:write": {"description": "Ingest knowledge from external systems", "public": True},
    "knowledge:read": {"description": "Read knowledge items", "public": True},
    "tickets:read": {"description": "List/view tickets", "public": False},
    "tickets:write": {"description": "Create/update tickets", "public": False},
    "tickets:delete": {"description": "Soft delete tickets", "public": False},
    "alerts:write": {"description": "Ingest alerts from external systems", "public": True},
    "users:read": {"description": "List workspace users", "public": False},
    "chat:read": {"description": "View chat sessions", "public": False},
    "chat:write": {"description": "Send chat messages", "public": False},
}

# Default scopes per key type
DEFAULT_SCOPES = {
    "web": list(SCOPES.keys()),  # all scopes
    "public": [s for s, v in SCOPES.items() if v["public"]],  # public-only scopes
}

# Default rate limits per key type
DEFAULT_RATE_LIMITS = {
    "web": 1000,   # req/hour
    "public": 200,  # req/hour
}


# ── Collection ───────────────────────────────────────────────────────────────

def _collection():
    return get_db()[COLLECTION]


# ── CRUD ─────────────────────────────────────────────────────────────────────

async def ensure_indexes():
    """Create indexes for api_keys collection."""
    coll = _collection()
    await coll.create_index("workspaceId")
    await coll.create_index("key_hash", unique=True)
    await coll.create_index("is_active")
    logger.info("API Key indexes ensured")


async def create_key(
    workspace_id: str,
    name: str,
    key_type: str = "web",
    scopes: Optional[List[str]] = None,
    created_by: str = "",
    expires_at: Optional[str] = None,
    rate_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Create new API key.
    Returns: {id, name, type, key (plaintext ONLY here), key_prefix, scopes, ...}
    """
    if key_type not in ("web", "public"):
        raise ValueError("key_type must be 'web' or 'public'")

    # Use default scopes if not provided
    if scopes is None:
        scopes = DEFAULT_SCOPES[key_type]

    # Validate scopes
    invalid_scopes = [s for s in scopes if s not in SCOPES]
    if invalid_scopes:
        raise ValueError(f"Invalid scopes: {invalid_scopes}")

    # Public keys can only have public scopes
    if key_type == "public":
        non_public = [s for s in scopes if not SCOPES[s].get("public")]
        if non_public:
            raise ValueError(f"Public keys cannot have these scopes: {non_public}")

    # Generate key
    plaintext, key_hash, key_prefix = generate_api_key(key_type)

    # Default rate limit
    if rate_limit is None:
        rate_limit = DEFAULT_RATE_LIMITS[key_type]

    doc = {
        "workspaceId": workspace_id,
        "name": name,
        "type": key_type,
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "scopes": scopes,
        "created_by": created_by,
        "last_used_at": None,
        "expires_at": expires_at,
        "rate_limit": rate_limit,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    result = await _collection().insert_one(doc)
    doc["_id"] = result.inserted_id

    logger.info(f"API key created: {name} (type={key_type}, workspace={workspace_id})")

    # Return with plaintext key (ONLY time it's shown)
    return {
        "id": str(result.inserted_id),
        "name": name,
        "type": key_type,
        "key": plaintext,  # ⚠️ ONLY shown at creation
        "key_prefix": key_prefix,
        "scopes": scopes,
        "rate_limit": rate_limit,
        "expires_at": expires_at,
        "created_at": doc["created_at"],
    }


async def verify_key(plain_key: str) -> Optional[Dict[str, Any]]:
    """
    Verify API key and return principal info.
    Returns: {id, workspaceId, name, type, scopes, rate_limit} or None
    """
    if not plain_key or not plain_key.startswith("pk_"):
        return None

    # Find by prefix (fast lookup)
    key_prefix = plain_key[:12] + "..."
    coll = _collection()

    # Search active keys with matching prefix
    cursor = coll.find({
        "key_prefix": key_prefix,
        "is_active": True,
    })

    async for doc in cursor:
        # Verify bcrypt hash
        if verify_api_key_hash(plain_key, doc.get("key_hash", "")):
            # Check expiry
            if doc.get("expires_at"):
                expires_str = doc["expires_at"].replace("Z", "+00:00")
                expires = datetime.fromisoformat(expires_str)
                if datetime.now(timezone.utc) > expires:
                    logger.warning(f"API key expired: {doc.get('name')}")
                    return None

            # Update last_used_at (fire and forget)
            await coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}}
            )

            return {
                "id": str(doc["_id"]),
                "workspaceId": doc.get("workspaceId"),
                "name": doc.get("name"),
                "type": doc.get("type"),
                "scopes": doc.get("scopes", []),
                "rate_limit": doc.get("rate_limit", 200),
            }

    return None


async def list_keys(workspace_id: str) -> List[Dict[str, Any]]:
    """List all API keys for a workspace (no plaintext)."""
    cursor = _collection().find(
        {"workspaceId": workspace_id},
        {"key_hash": 0}  # exclude hash
    ).sort("created_at", -1)

    keys = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        keys.append(doc)
    return keys


async def get_key(key_id: str) -> Optional[Dict[str, Any]]:
    """Get API key by ID (no plaintext)."""
    from bson import ObjectId
    try:
        doc = await _collection().find_one(
            {"_id": ObjectId(key_id)},
            {"key_hash": 0}
        )
    except Exception:
        return None
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def revoke_key(key_id: str) -> bool:
    """Revoke (deactivate) an API key."""
    from bson import ObjectId
    try:
        result = await _collection().update_one(
            {"_id": ObjectId(key_id)},
            {"$set": {"is_active": False}}
        )
        return result.matched_count > 0
    except Exception:
        return False


async def update_key(
    key_id: str,
    name: Optional[str] = None,
    scopes: Optional[List[str]] = None,
    expires_at: Optional[str] = None,
    rate_limit: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Update API key metadata."""
    from bson import ObjectId

    update_fields = {}
    if name is not None:
        update_fields["name"] = name
    if scopes is not None:
        # Validate scopes
        invalid = [s for s in scopes if s not in SCOPES]
        if invalid:
            raise ValueError(f"Invalid scopes: {invalid}")
        update_fields["scopes"] = scopes
    if expires_at is not None:
        update_fields["expires_at"] = expires_at
    if rate_limit is not None:
        update_fields["rate_limit"] = rate_limit

    if not update_fields:
        return await get_key(key_id)

    try:
        await _collection().update_one(
            {"_id": ObjectId(key_id)},
            {"$set": update_fields}
        )
        return await get_key(key_id)
    except Exception:
        return None


async def rotate_key(key_id: str) -> Optional[Dict[str, Any]]:
    """Rotate an API key — revoke old, create new with same settings."""
    old_key = await get_key(key_id)
    if not old_key:
        return None

    # Revoke old key
    await revoke_key(key_id)

    # Create new key with same settings
    new_key = await create_key(
        workspace_id=old_key["workspaceId"],
        name=f"{old_key['name']} (rotated)",
        key_type=old_key["type"],
        scopes=old_key["scopes"],
        created_by=old_key.get("created_by", ""),
        expires_at=old_key.get("expires_at"),
        rate_limit=old_key.get("rate_limit"),
    )

    logger.info(f"API key rotated: {old_key['name']} → {new_key['name']}")
    return new_key
