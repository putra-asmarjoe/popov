"""
Pattern Miner Service — Fase 5 (HDBSCAN + aggregate, testable, no LLM)
Baca embedding yang sudah ada (1024d liquid), jangan re-embed.
"""
from __future__ import annotations
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)


async def load_episodes(
    service: Optional[str] = None,
    days: int = 30,
    workspace_id: Optional[str] = None,
) -> List[dict]:
    """Load episodes dengan embedding, exclude feedback wrong. Filter 30 hari terakhir.
    MT isolation (SCALE plan MT-7): workspace_id=None → semua (legacy/global);
    workspace_id ada → hanya episode workspace itu."""
    db = get_db()
    coll = db["incident_episodes"]
    q: Dict[str, Any] = {"feedback": {"$ne": "wrong"}, "embedding": {"$exists": True, "$ne": None}}
    if service:
        q["service_name"] = service
    if workspace_id:
        q["workspace_id"] = workspace_id
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q["timestamp"] = {"$gte": since}
    cursor = coll.find(q, {"_id": 0})
    episodes = await cursor.to_list(length=500)
    # fallback tanpa timestamp jika kosong (data lama)
    if not episodes and days:
        q2 = {"feedback": {"$ne": "wrong"}, "embedding": {"$exists": True, "$ne": None}}
        if service:
            q2["service_name"] = service
        if workspace_id:
            q2["workspace_id"] = workspace_id
        episodes = await coll.find(q2, {"_id": 0}).to_list(length=500)
    logger.info(f"[PatternMiner] load service={service or 'all'} ws={workspace_id or 'all'} days={days} → {len(episodes)} episodes")
    return episodes


def cluster_episodes(embeddings: np.ndarray, min_cluster_size: int = 3) -> List[int]:
    """
    HDBSCAN primary (cosine, min_cluster_size=3), fallback KMeans jika HDBSCAN gagal atau semua noise.
    Return labels list ( -1 = noise)
    """
    if len(embeddings) < min_cluster_size:
        logger.info(f"[PatternMiner] not enough data {len(embeddings)} < {min_cluster_size} → all noise")
        return [-1] * len(embeddings)

    # Normalize for cosine
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    norm_emb = embeddings / norms

    try:
        import hdbscan
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=2,
            metric="euclidean",  # after normalize, euclidean ~ cosine
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(norm_emb)
        labels = labels.tolist()
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_noise = labels.count(-1)
        logger.info(f"[PatternMiner] HDBSCAN clusters={n_clusters} noise={n_noise} total={len(labels)}")
        # Jika semua noise, fallback KMeans
        if n_clusters == 0:
            raise ValueError("all noise, fallback KMeans")
        return labels
    except Exception as e:
        logger.warning(f"[PatternMiner] HDBSCAN failed ({e}), fallback KMeans")
        # Fallback KMeans: K = max(2, n//5) capped 5
        try:
            from sklearn.cluster import KMeans
            n = len(embeddings)
            k = max(2, min(5, n // 5))
            kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
            labels = kmeans.fit_predict(norm_emb).tolist()
            logger.info(f"[PatternMiner] KMeans k={k} labels={Counter(labels)}")
            return labels
        except Exception as e2:
            logger.error(f"[PatternMiner] KMeans also failed: {e2}")
            return [-1] * len(embeddings)


def aggregate_clusters(episodes: List[dict], labels: List[int]) -> Tuple[List[dict], int]:
    """
    Per cluster hitung: probable_cause, pct, avg_resolution, distinguishing_symptoms, feedback_quality, episode_count, date_range
    Return (patterns, unclassified_count)
    """
    cluster_map: Dict[int, List[dict]] = defaultdict(list)
    for ep, lbl in zip(episodes, labels):
        cluster_map[lbl].append(ep)

    unclassified = len(cluster_map.get(-1, []))
    patterns: List[dict] = []

    for lbl, eps in sorted(cluster_map.items()):
        if lbl == -1:
            continue  # noise
        # episode_count
        n = len(eps)
        # date_range
        timestamps = [ep.get("timestamp") for ep in eps if ep.get("timestamp")]
        if timestamps:
            dmin = min(timestamps).strftime("%Y-%m-%d") if hasattr(min(timestamps), "strftime") else str(min(timestamps))
            dmax = max(timestamps).strftime("%Y-%m-%d") if hasattr(max(timestamps), "strftime") else str(max(timestamps))
            date_range = [dmin, dmax]
        else:
            date_range = []
        # probable cause
        rc_counter = Counter(ep.get("root_cause") or "unknown" for ep in eps)
        probable, cnt = rc_counter.most_common(1)[0]
        pct = cnt / n if n else 0
        # avg_resolution: tidak ada field resolution, gunakan perbedaan timestamp? fallback None
        # Coba hitung durasi jika ada created_at vs timestamp? Saat ini tidak ada, jadi None
        avg_res = None
        # distinguishing_symptoms: frequency of hpa_status, error_rate buckets
        hpa_counter = Counter((ep.get("symptoms") or {}).get("hpa_status") or "None" for ep in eps)
        # most common hpa
        top_hpa = hpa_counter.most_common(1)[0][0] if hpa_counter else "None"
        # TF-IDF style: ambil kata terbanyak di mongo_summary
        # Sederhana: word frequency dari mongo_summary
        words = Counter()
        for ep in eps:
            txt = (ep.get("mongo_summary") or "") + " " + (ep.get("trace_summary") or "")
            for w in txt.lower().split():
                w = w.strip(".,:()")
                if len(w) > 3 and w not in {"error", "found", "logs"}:
                    words[w] += 1
        top_words = [w for w, _ in words.most_common(5)]
        distinguishing = top_words or [top_hpa]
        # misleading: jika ada CPU/memory di trace tapi bukan cause? Sederhana: cek kata cpu/memory
        misleading = []
        for ep in eps:
            txt = (ep.get("metrics_summary") or "").lower()
            if "cpu" in txt and probable != "service-fault":
                misleading.append("CPU tinggi")
                break
        # feedback_quality
        fb_counter = Counter(ep.get("feedback") or "pending" for ep in eps)
        feedback_quality = {
            "correct": fb_counter.get("correct", 0),
            "auto_resolved": fb_counter.get("auto_resolved", 0),
            "pending": fb_counter.get("pending", 0) + fb_counter.get(None, 0),
        }
        # label human
        label = f"{top_hpa} + {probable}" if top_hpa != "None" else probable
        # focus/skip hints simple mapping
        if probable == "downstream":
            focus = ["boundary_traces", "dependency_health"]
            skip = ["cpu_metrics", "memory_metrics"]
        elif probable == "service-fault":
            focus = ["db_connection", "trace internal"]
            skip = ["dependency_health"]
        else:
            focus = ["full fan-out"]
            skip = []

        patterns.append({
            "cluster_id": int(lbl),
            "label": label,
            "episode_count": n,
            "date_range": date_range,
            "probable_cause": probable,
            "probable_cause_pct": round(pct, 2),
            "avg_resolution_min": avg_res,
            "focus_hints": focus,
            "skip_hints": skip,
            "misleading_signals": misleading,
            "distinguishing_symptoms": distinguishing,
            "top_hpa": top_hpa,
            "feedback_quality": feedback_quality,
            "episode_ids": [ep.get("episode_id") for ep in eps],
        })

    # Sort by episode_count desc
    patterns.sort(key=lambda x: x["episode_count"], reverse=True)
    logger.info(f"[PatternMiner] aggregated {len(patterns)} patterns, unclassified {unclassified}")
    return patterns, unclassified


async def generate_narrative_with_llm(service: str, patterns: List[dict], unclassified: int, total: int) -> str:
    """
    Satu call LLM ringan untuk narasi Markdown. Fallback ke manual jika LLM gagal.
    """
    if not patterns:
        return f"## Learned Patterns (auto-generated, last updated {datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n<!-- DO NOT EDIT MANUALLY -->\n\n_Belum ada pattern yang cukup kuat (min_cluster_size=3)._ Unclassified: {unclassified}/{total} episode."

    # Build cluster_json untuk prompt
    import json
    cluster_json = json.dumps(patterns, indent=2, ensure_ascii=False, default=str)

    from services.prompt_loader import render as render_prompt
    prompt = render_prompt(
        "pattern_miner_narrative",
        service=service,
        total=total,
        cluster_json=cluster_json,
        unclassified=unclassified,
    )

    try:
        from config.settings import settings
        from langchain_core.messages import SystemMessage, HumanMessage
        from services.llm_factory import get_chat_llm

        # Model ringan via factory (openai/openrouter/google/opencode)
        llm = get_chat_llm(temperature=0.3)

        messages = [SystemMessage(content="You are a technical writer. Write the Learned Patterns in Markdown."), HumanMessage(content=prompt)]
        # Timeout 10 detik
        import asyncio
        resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=15)
        text = resp.content if hasattr(resp, "content") else str(resp)
        if "## Learned Patterns" not in text:
            text = f"## Learned Patterns (auto-generated, last updated {datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n<!-- DO NOT EDIT MANUALLY -->\n\n" + text
        return text
    except Exception as e:
        logger.warning(f"[PatternMiner] LLM narasi gagal, fallback manual: {e}")
        # Fallback manual
        lines = [f"## Learned Patterns (auto-generated, last updated {datetime.now(timezone.utc).strftime('%Y-%m-%d')})", "<!-- DO NOT EDIT MANUALLY — dikelola oleh Pattern Miner Agent -->", ""]
        for p in patterns:
            lines.append(f"### Pattern: {p['label']}")
            lines.append(f"- Frekuensi: {p['episode_count']}x dalam 30 hari terakhir")
            lines.append(f"- Root cause aktual: {p['probable_cause']} {int(p['probable_cause_pct']*100)}% kasus ({p['episode_count']}/{total} episode)")
            lines.append(f"- Gejala pembeda: {', '.join(p['distinguishing_symptoms'])}")
            if p['misleading_signals']:
                lines.append(f"- BUKAN penyebab: {', '.join(p['misleading_signals'])}")
            lines.append(f"- Rata-rata resolusi: {p['avg_resolution_min'] or 'belum ada data'}")
            lines.append(f"- Feedback quality: {p['feedback_quality']['correct']} correct, {p['feedback_quality']['auto_resolved']} auto_resolved, {p['feedback_quality']['pending']} pending")
            lines.append("")
        if unclassified:
            lines.append(f"_Unclassified (noise): {unclassified} episode_")
        return "\n".join(lines)
