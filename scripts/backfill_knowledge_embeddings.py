#!/usr/bin/env python3
"""
Backfill Knowledge Embeddings — Gap 1 Fase 3.

One-time script: generate embeddings for all existing documents in:
  - knowledge_library (field: content)
  - agent_docs (field: body)
  - workspace_knowledge (field: content)

Idempotent — safe to re-run. Skips docs that already have embeddings.
Usage:
  python scripts/backfill_knowledge_embeddings.py [--dry-run] [--delay 0.5]
"""
import argparse
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional

from services.mongodb_client import get_db
from services.llm_config_store import get_embedding_cfg
from config.settings import settings

logger = logging.getLogger("backfill_embeddings")

LIBRARY_COLLECTION = "knowledge_library"
AGENT_DOCS_COLLECTION = "agent_docs"
WORKSPACE_KB_COLLECTION = "workspace_knowledge"


async def get_embedding(text: str, cfg: dict) -> Optional[list]:
    """Reuse _get_embedding from second_brain."""
    from services.second_brain import _get_embedding
    return await _get_embedding(text)


async def backfill_collection(
    db,
    collection: str,
    content_field: str,
    filter_query: dict,
    delay: float,
    dry_run: bool,
) -> dict:
    """Backfill one collection. Returns stats."""
    stats = {"total": 0, "embedded": 0, "skipped_empty": 0, "skipped_has_embedding": 0, "failed": 0}

    cursor = db[collection].find(filter_query)
    docs = await cursor.to_list(length=1000)
    stats["total"] = len(docs)

    if not docs:
        return stats

    cfg = await get_embedding_cfg()
    if not cfg:
        logger.warning(f"[{collection}] No embedding config — all docs will be skipped")
        stats["skipped_empty"] = stats["total"]
        return stats

    for doc in docs:
        doc_id = doc.get("_id")
        content = doc.get(content_field) or ""

        if not content.strip():
            stats["skipped_empty"] += 1
            continue

        if doc.get("embedding") is not None:
            stats["skipped_has_embedding"] += 1
            continue

        if dry_run:
            logger.info(f"[{collection}] DRY RUN: would embed doc {doc_id} ({len(content)} chars)")
            stats["embedded"] += 1
            continue

        text = content[:cfg.get("max_chars") or settings.embedding_max_chars].strip()
        try:
            vec = await get_embedding(text, cfg)
            if vec:
                from datetime import datetime, timezone
                await db[collection].update_one(
                    {"_id": doc_id},
                    {"$set": {
                        "embedding": vec,
                        "embedding_model": cfg.get("model"),
                        "embedding_updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                stats["embedded"] += 1
                logger.info(f"[{collection}] Embedded doc {doc_id} (dim={len(vec)})")
            else:
                stats["failed"] += 1
                logger.warning(f"[{collection}] No vector returned for doc {doc_id}")
        except Exception as e:
            stats["failed"] += 1
            logger.warning(f"[{collection}] Embed failed for doc {doc_id}: {e}")

        if delay > 0:
            await asyncio.sleep(delay)

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Backfill knowledge embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Don't write, just count")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between docs (seconds)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    db = get_db()

    collections = [
        (LIBRARY_COLLECTION, "content", {}),
        (AGENT_DOCS_COLLECTION, "body", {}),
        (WORKSPACE_KB_COLLECTION, "content", {}),
    ]

    total_stats = {"total": 0, "embedded": 0, "skipped_empty": 0, "skipped_has_embedding": 0, "failed": 0}

    for coll_name, field, filter_q in collections:
        logger.info(f"--- Backfilling {coll_name} ---")
        stats = await backfill_collection(db, coll_name, field, filter_q, args.delay, args.dry_run)
        for k, v in stats.items():
            total_stats[k] += v
        logger.info(f"[{coll_name}] done: {stats}")

    logger.info(f"=== TOTAL: {total_stats} ===")

    if args.dry_run:
        logger.info("DRY RUN — no changes written")


if __name__ == "__main__":
    asyncio.run(main())
