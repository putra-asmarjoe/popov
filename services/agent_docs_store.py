"""
Agent Docs Store — grounding docs & playbook berbasis DB (editable via UI).

Menggantikan ketergantungan doc_loader ke folder `docs/*.md` (file-driven, git).
Collection (popovagent_db):
- agent_docs:  {category, key, meta, body, updatedAt}

category ∈ services | playbooks | schemas | connections | observability
key          = slug nama dokumen (ex: my_service, high_error_rate)
meta         = dict hasil parse YAML frontmatter (criticality, collections, ...)
body         = markdown body

Pola: sama seperti knowledge_store / service_store (async Motor + get_db).
Bootstrap: bila collection kosong, doc_loader fallback ke file docs/*.md
(zero-downtime). Script import menyalin docs/*.md → DB sekali (idempotent).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.mongodb_client import get_db
from config.settings import settings

logger = logging.getLogger(__name__)

COLLECTION = "agent_docs"
CATEGORIES = ("services", "playbooks", "schemas", "connections", "observability", "general")


def _validate_embedding_limit(body: str) -> None:
    """Raise ValueError if body exceeds embedding max_chars limit."""
    max_chars = settings.embedding_max_chars
    if len(body) > max_chars:
        raise ValueError(
            f"content_too_long|max_chars={max_chars}|actual={len(body)}"
        )

_cache: Optional[Dict[str, Dict[str, dict]]] = None
_cache_loaded = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_agent_docs_indexes() -> None:
    db = get_db()
    await db[COLLECTION].create_index([("category", 1), ("key", 1)], unique=True)
    await db[COLLECTION].create_index("category")
    logger.info("Agent docs indexes ensured")


def invalidate_cache() -> None:
    global _cache, _cache_loaded
    _cache = None
    _cache_loaded = False


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def upsert_doc(category: str, key: str, meta: Dict[str, Any], body: str) -> dict:
    """Insert atau timpa satu dokumen (bootstrap & create API). Return dokumen."""
    if category not in CATEGORIES:
        raise ValueError(f"category harus salah satu dari {CATEGORIES}")
    key = (key or "").strip().lower()
    if not key:
        raise ValueError("key tidak boleh kosong")
    _validate_embedding_limit(body or "")
    db = get_db()
    await db[COLLECTION].update_one(
        {"category": category, "key": key},
        {"$set": {"meta": meta or {}, "body": (body or ""), "updatedAt": _now_iso()}},
        upsert=True,
    )
    invalidate_cache()
    # Gap 1 Fase 2: fire-and-forget embedding
    try:
        from services.knowledge_embed import fire_and_forget_embed
        fire_and_forget_embed(body or "", COLLECTION, {"category": category, "key": key})
    except Exception:
        pass
    return await get_doc(category, key)


async def get_doc(category: str, key: str) -> Optional[dict]:
    try:
        return await get_db()[COLLECTION].find_one(
            {"category": category, "key": (key or "").strip().lower()}, {"_id": 0}
        )
    except Exception as e:
        logger.warning(f"agent_docs get_doc failed: {e}")
        return None


async def update_doc(category: str, key: str, updates: Dict[str, Any]) -> Optional[dict]:
    """Update meta/body. key & category immutable."""
    set_fields: Dict[str, Any] = {"updatedAt": _now_iso()}
    if "meta" in updates and updates["meta"] is not None:
        set_fields["meta"] = updates["meta"]
    if "body" in updates and updates["body"] is not None:
        set_fields["body"] = str(updates["body"])
        _validate_embedding_limit(set_fields["body"])
    if not set_fields:
        return await get_doc(category, key)
    result = await get_db()[COLLECTION].update_one(
        {"category": category, "key": key.strip().lower()}, {"$set": set_fields}
    )
    invalidate_cache()
    # Gap 1 Fase 2: re-embed if body changed
    if "body" in set_fields:
        try:
            from services.knowledge_embed import fire_and_forget_embed
            fire_and_forget_embed(set_fields["body"], COLLECTION, {"category": category, "key": key.strip().lower()})
        except Exception:
            pass
    if result.matched_count == 0:
        return None
    return await get_doc(category, key)


async def delete_doc(category: str, key: str) -> bool:
    result = await get_db()[COLLECTION].delete_one(
        {"category": category, "key": key.strip().lower()}
    )
    if result.deleted_count:
        invalidate_cache()
        return True
    return False


async def list_docs(category: Optional[str] = None) -> List[dict]:
    """List dokumen (tanpa body besar bila perlu? di sini sertakan meta)."""
    query = {"category": category} if category else {}
    cursor = get_db()[COLLECTION].find(query, {"_id": 0}).sort([("category", 1), ("key", 1)])
    return [doc async for doc in cursor]


# ── Konsumsi agent ────────────────────────────────────────────────────────────

async def count_all() -> int:
    try:
        return await get_db()[COLLECTION].count_documents({})
    except Exception as e:
        logger.warning(f"agent_docs count failed: {e}")
        return 0


async def load_all_docs_db() -> Dict[str, Dict[str, dict]]:
    """Load semua dokumen → {category: {key: {meta, body}}}. Tanpa cache level ini
    (cache ditangani doc_loader)."""
    result: Dict[str, Dict[str, dict]] = {c: {} for c in CATEGORIES}
    cursor = get_db()[COLLECTION].find({}, {"_id": 0, "category": 1, "key": 1, "meta": 1, "body": 1})
    async for doc in cursor:
        cat = doc.get("category")
        if cat not in result:
            continue
        result[cat][doc["key"]] = {"meta": doc.get("meta") or {}, "body": doc.get("body") or ""}
    return result
