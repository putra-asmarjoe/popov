"""
Knowledge Embedding — shared embedding helper for knowledge collections.
Fase 1+2 Gap 1: generates embeddings for knowledge_library, agent_docs, workspace_knowledge.

Reuses _get_embedding from second_brain.py (proven for 157 incident_episodes).
Non-blocking, graceful degradation — if embedding fails, store without it.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config.settings import settings

logger = logging.getLogger(__name__)


async def embed_knowledge_content(content: str) -> Dict[str, Any]:
    """
    Generate embedding for a knowledge document content.
    Returns dict with embedding fields to merge into the document.
    Always returns a dict — never raises, never blocks the caller.
    """
    from services.second_brain import _get_embedding
    from services.llm_config_store import get_embedding_cfg

    cfg = await get_embedding_cfg()
    if not cfg:
        return {
            "embedding": None,
            "embedding_model": None,
            "embedding_updated_at": None,
        }

    max_chars = cfg.get("max_chars") or settings.embedding_max_chars
    text = (content or "")[:max_chars].strip()
    if not text:
        return {
            "embedding": None,
            "embedding_model": None,
            "embedding_updated_at": None,
        }

    try:
        vec = await _get_embedding(text)
        if vec:
            return {
                "embedding": vec,
                "embedding_model": cfg.get("model"),
                "embedding_updated_at": datetime.now(timezone.utc).isoformat(),
            }
        logger.info(f"[KnowledgeEmbed] no embedding returned (provider fallback)")
    except Exception as e:
        logger.warning(f"[KnowledgeEmbed] embedding generation failed: {e}")

    return {
        "embedding": None,
        "embedding_model": None,
        "embedding_updated_at": None,
    }


def fire_and_forget_embed(content: str, collection: str, doc_filter: Dict[str, Any]) -> None:
    """
    Schedule embedding generation as a background task.
    Updates the document with embedding fields after generation completes.
    Non-blocking — returns immediately.
    """
    async def _bg_embed():
        try:
            emb_fields = await embed_knowledge_content(content)
            if emb_fields.get("embedding") is not None:
                from services.mongodb_client import get_db
                db = get_db()
                await db[collection].update_one(doc_filter, {"$set": emb_fields})
                logger.info(f"[KnowledgeEmbed] embedding saved to {collection} filter={doc_filter}")
        except Exception as e:
            logger.warning(f"[KnowledgeEmbed] background embed failed for {collection}: {e}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_bg_embed())
        else:
            loop.create_task(_bg_embed())
    except RuntimeError:
        asyncio.get_event_loop().create_task(_bg_embed())
