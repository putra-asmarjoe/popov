"""
Pattern Miner Agent — Fase 5 (orchestrator, DRY, tebak file-driven)
Trigger event: N episode baru (default 5), plus manual via POST /brain/mine
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from services.mongodb_client import get_db
from services.pattern_miner_service import load_episodes, cluster_episodes, aggregate_clusters, generate_narrative_with_llm

logger = logging.getLogger(__name__)

PATTERN_MINER_TRIGGER_N = 5  # event-driven threshold


async def _update_learned_patterns_section(svc: str, new_content: str):
    """Update section `## Learned Patterns` pada agent_docs (DB), BUKAN file docs/.

    Sumber kebenaran knowledge = DB (UI). Service doc body di-timpa section-nya."""
    from services.agent_docs_store import get_doc, update_doc, upsert_doc

    key = (svc or "").strip().lower()
    if not key:
        logger.warning("[PatternMiner] svc kosong — skip update learned patterns")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"## Learned Patterns (auto-generated, last updated {today})"
    marker = "<!-- DO NOT EDIT MANUALLY"
    if "## Learned Patterns" in new_content:
        new_section = new_content
    else:
        new_section = f"{header}\n{marker} — dikelola oleh Pattern Miner Agent -->\n\n{new_content}"

    doc = await get_doc("services", key)
    if doc is None:
        # Service doc belum ada di DB — buat entri baru berisi learned patterns
        await upsert_doc("services", key, {"id": svc, "collections": {"primary": f"logs_{key}"}},
                         f"{new_section}\n")
        logger.info(f"[PatternMiner] created agent_docs services/{key} (learned patterns)")
        return

    content = doc.get("body") or ""
    pattern = r"(## Learned Patterns.*?)(?=\n## |\Z)"
    if "## Learned Patterns" in content:
        updated = re.sub(pattern, new_section, content, flags=re.DOTALL)
    else:
        updated = content.rstrip() + f"\n\n{new_section}\n"
    await update_doc("services", key, {"body": updated})
    logger.info(f"[PatternMiner] updated agent_docs services/{key} learned patterns")


async def run_pattern_miner(
    service: Optional[str] = None,
    days: int = 30,
    workspace_id: Optional[str] = None,
) -> dict:
    """
    Run Pattern Miner untuk satu service (atau all jika service=None).
    workspace_id (SCALE plan MT-7): None = legacy/global; ada → scope per workspace.
    Return stats dict.
    """
    import time
    start = time.time()
    services = [service] if service else []
    if not service:
        # Ambil semua service yang ada episode
        episodes_all = await load_episodes(service=None, days=days, workspace_id=workspace_id)
        services = sorted(set(ep.get("service_name") for ep in episodes_all if ep.get("service_name")))
        if not services:
            return {"services": [], "total_patterns": 0, "unclassified": 0, "duration_sec": 0}

    total_patterns = 0
    total_unclassified = 0
    results = []

    for svc in services:
        episodes = await load_episodes(service=svc, days=days, workspace_id=workspace_id)
        if len(episodes) < 3:
            logger.info(f"[PatternMiner] skip {svc}: only {len(episodes)} episodes (<3)")
            continue

        # Extract embeddings
        try:
            embeddings = np.array([ep["embedding"] for ep in episodes], dtype=np.float32)
        except Exception as e:
            logger.warning(f"[PatternMiner] no embedding for {svc}: {e}")
            continue

        labels = cluster_episodes(embeddings, min_cluster_size=3)
        patterns, unclassified = aggregate_clusters(episodes, labels)

        # LLM narasi (satu call per service)
        narrative = await generate_narrative_with_llm(svc, patterns, unclassified, len(episodes))

        # 1. Update learned patterns di agent_docs (DB) — bukan file docs/services/
        await _update_learned_patterns_section(svc, narrative)

        # 2. Write patterns/<svc>.json (machine-readable)
        patterns_dir = Path("patterns")
        patterns_dir.mkdir(parents=True, exist_ok=True)
        json_path = patterns_dir / f"{svc}.json"
        json_data = {
            "service": svc,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "patterns": patterns,
            "unclassified_count": unclassified,
            "total_episodes": len(episodes),
        }
        tmp_json = str(json_path) + ".tmp"
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp_json, str(json_path))

        # 3. learned_playbooks/<label>.md per cluster
        pb_dir = Path("learned_playbooks")
        pb_dir.mkdir(parents=True, exist_ok=True)
        for pat in patterns:
            safe_label = re.sub(r"[^a-z0-9]+", "_", pat["label"].lower()).strip("_")
            pb_path = pb_dir / f"{svc}_{safe_label}.md"
            pb_content = f"""# Playbook: {pat['label']} — {svc}

> Auto-generated from Pattern Miner {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

## Trigger
- Service: `{svc}`
- Cluster: {pat['cluster_id']}
- Episodes: {pat['episode_count']}x

## Probable Cause
- {pat['probable_cause']} {int(pat['probable_cause_pct']*100)}% 

## Focus Hints
- {', '.join(pat['focus_hints'])}

## Skip Hints
- {', '.join(pat['skip_hints'])}

## Distinguishing Symptoms
- {', '.join(pat['distinguishing_symptoms'])}

## Feedback Quality
- {pat['feedback_quality']}
"""
            tmp_pb = str(pb_path) + ".tmp"
            with open(tmp_pb, "w", encoding="utf-8") as f:
                f.write(pb_content)
            os.replace(tmp_pb, str(pb_path))

        total_patterns += len(patterns)
        total_unclassified += unclassified
        results.append({"service": svc, "patterns": len(patterns), "episodes": len(episodes), "unclassified": unclassified})

        # Hot-reload docs agar Correlation langsung pakai pattern baru
        try:
            from services.doc_loader import reload_docs
            await reload_docs()
        except Exception as e:
            logger.warning(f"[PatternMiner] reload_docs failed: {e}")

    duration = time.time() - start

    # Catat run metadata ke Mongo
    try:
        db = get_db()
        await db["pattern_miner_runs"].insert_one({
            "services": services,
            "results": results,
            "total_patterns": total_patterns,
            "unclassified": total_unclassified,
            "run_duration_sec": round(duration, 2),
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning(f"[PatternMiner] failed to log run: {e}")

    logger.info(f"[PatternMiner] done services={services} patterns={total_patterns} unclassified={total_unclassified} duration={duration:.2f}s")
    return {"services": services, "total_patterns": total_patterns, "unclassified": total_unclassified, "results": results, "duration_sec": round(duration, 2)}


async def maybe_trigger_pattern_miner(service: str):
    """Event-triggered: jika episode baru sejak last run >= N, queue run."""
    try:
        db = get_db()
        last = await db["pattern_miner_runs"].find_one({"services": service}, sort=[("created_at", -1)])
        last_at = last["created_at"] if last else datetime(2000, 1, 1, tzinfo=timezone.utc)
        cnt = await db["incident_episodes"].count_documents({"service_name": service, "timestamp": {"$gte": last_at}, "feedback": {"$ne": "wrong"}})
        if cnt >= PATTERN_MINER_TRIGGER_N:
            logger.info(f"[PatternMiner] trigger {service}: {cnt} new episodes >= {PATTERN_MINER_TRIGGER_N}")
            asyncio.create_task(run_pattern_miner(service=service))
    except Exception as e:
        logger.warning(f"[PatternMiner] maybe_trigger failed: {e}")
