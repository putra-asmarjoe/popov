"""
Second Brain — Fase 1 Writer + Fase 2 Reader (NEXTDEV2.md)
Writer: setiap insiden → episode terstruktur (fire-and-forget).
Reader: Hybrid Search (metadata exact + semantic cosine lokal) + Dynamic Confidence Scaling.
Non-blocking, additive, tidak pernah mengganggu pipeline utama.
"""
from __future__ import annotations
import logging
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.mongodb_client import get_db
from config.settings import settings

logger = logging.getLogger(__name__)

INCIDENT_EPISODES_COLLECTION = "incident_episodes"


# ── ID Generation (in-memory, no DB I/O → no race) ──────────────────────────

def generate_episode_id(service_name: str = "") -> str:
    """Generate ID unik instan tanpa I/O DB. Format: EP-YYYY-MM-DD-XXXX (hash 4 hex)."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    short_hash = uuid.uuid4().hex[:4].upper()
    return f"EP-{today_str}-{short_hash}"


# ── Regex Extractors ─────────────────────────────────────────────────────────

def _extract_error_rate(metrics_summary: str) -> Optional[float]:  # noqa
    """Extract error rate percentage dari metrics_summary. Contoh: 'Error rate: 43.5%'"""
    if not metrics_summary:
        return None
    # Coba beberapa pola
    patterns = [
        r"error\s*rate[:\s]*([\d]+\.?[\d]*)\s*%",
        r"error_rate[:\s]*([\d]+\.?[\d]*)\s*%",
        r"rate\s*error[:\s]*([\d]+\.?[\d]*)\s*%",
    ]
    for pat in patterns:
        m = re.search(pat, metrics_summary, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def _extract_hpa_status(metrics_summary: str) -> Optional[str]:
    """Detect HPA maxout dari metrics_summary."""
    if not metrics_summary:
        return None
    if re.search(r"MAXOUT|MAXED\s*OUT|HPA.*max", metrics_summary, re.IGNORECASE):
        return "MAXOUT"
    if "HPA" in metrics_summary:
        return "NORMAL"
    return None


def _extract_mongo_count(mongo_summary: str) -> Optional[int]:
    """Extract jumlah error dari mongo_summary."""
    if not mongo_summary:
        return None
    patterns = [
        r"(\d+)\s*error",
        r"total[:\s]*(\d+)",
        r"count[:\s]*(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, mongo_summary, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def _infer_trigger(state: dict) -> str:
    """Tentukan dari mana insiden ini dipicu."""
    intent = str(state.get("intent", "")).lower()
    if "watchdog" in intent:
        return "watchdog_alert"
    sender = state.get("sender") or {}
    # sender bisa dict atau string
    if isinstance(sender, dict) and sender.get("channel") == "telegram":
        return "telegram_mention"
    if isinstance(sender, dict) and sender.get("channel") == "api":
        return "api_trigger"
    if sender:  # ada sender info apapun
        return "telegram_mention"
    return "api_trigger"


# ── Embedding via API (Fase 2+ — OpenRouter liquid / OpenAI) ──────────────

async def _get_embedding(text: str) -> Optional[list[float]]:
    """
    Ambil embedding vector via config BYOK (Fix #54) / fallback settings.
    Return None jika mode local, tak ada key, atau request gagal (fallback TF).
    """
    from services.llm_config_store import get_embedding_cfg
    cfg = await get_embedding_cfg()
    if not cfg:
        return None
    api_key = cfg["api_key"]
    base_url = (cfg["base_url"] or "").rstrip("/")
    provider = cfg["provider"]
    model = cfg["model"]
    dim = cfg["dim"]
    timeout_ms = cfg["timeout_ms"]
    # potong teks agar pas context model (liquid 512 tokens ≈ 1800 char)
    text = (text or "")[:1800].strip()
    if not text or not api_key or not base_url:
        return None
    try:
        import httpx
        url = f"{base_url}/embeddings"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        # OpenRouter butuh extra headers untuk tracking (opsional)
        if cfg.get("is_openrouter"):
            headers["HTTP-Referer"] = "https://popov-agent.local"
            headers["X-Title"] = "Popov Agent Second Brain"
        payload = {"model": model, "input": text}
        timeout = timeout_ms / 1000.0
        async with httpx.AsyncClient(timeout=timeout + 2) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            # OpenAI compat: data["data"][0]["embedding"]
            vec = data.get("data", [{}])[0].get("embedding")
            if vec and isinstance(vec, list):
                # sanity dim check (log warning jika beda)
                if len(vec) != dim:
                    logger.warning(f"[SecondBrain] embedding dim mismatch {len(vec)} vs expected {dim} (model {model})")
                return vec
            logger.warning(f"[SecondBrain] embedding response tanpa vector: {data}")
            return None
    except Exception as e:
        logger.warning(f"[SecondBrain] _get_embedding failed ({provider}/{model}): {e}")
        return None


def _vector_cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    # cosine [-1,1] → clamp 0..1 untuk similarity (embeddings biasanya 0..1, tapi negative mungkin)
    cos = dot / (na * nb)
    return max(0.0, min(1.0, cos))


# ── Core Writer ──────────────────────────────────────────────────────────────

async def write_episode_bg(state: dict, episode_id: str) -> None:
    """
    Tulis episode ke incident_episodes sebagai background task (fire-and-forget).
    Tidak pernah raise exception — semua error ditelan dan di-log sebagai warning.
    """
    try:
        db = get_db()
        collection = db[INCIDENT_EPISODES_COLLECTION]

        metrics_sum = state.get("metrics_summary") or ""
        mongo_sum = state.get("mongo_summary") or ""
        trace_sum = state.get("trace_summary") or ""
        now = datetime.now(timezone.utc)

        # siapkan teks untuk embedding (reuse helper biar konsisten)
        tmp_state = {"metrics_summary": metrics_sum, "mongo_summary": mongo_sum, "trace_summary": trace_sum, "service_name": state.get("service_name") or "", "intent": state.get("intent") or ""}
        embed_text = _build_query_text(tmp_state)

        doc = {
            "episode_id": episode_id,
            "request_id": state.get("request_id"),
            "timestamp": now,
            "service_name": state.get("service_name"),
            "trigger": _infer_trigger(state),
            "symptoms": {
                "error_rate": _extract_error_rate(metrics_sum),
                "hpa_status": _extract_hpa_status(metrics_sum),
                "mongo_error_count": _extract_mongo_count(mongo_sum),
                "trace_available": bool(state.get("trace_available", False)),
                "metrics_available": bool(state.get("metrics_available", False)),
                "mongo_available": bool(state.get("mongo_available", False)),
            },
            "root_cause": state.get("root_cause_assessment"),
            "correlation_result": state.get("correlation_result"),
            "confidence": None,
            "mongo_summary": mongo_sum if mongo_sum else None,
            "metrics_summary": metrics_sum if metrics_sum else None,
            "trace_summary": trace_sum if trace_sum else None,
            "feedback": None,
            "feedback_weight": None,
            "feedback_note": None,
            "feedback_at": None,
            "created_at": now,
            "workspace_id": state.get("workspace_id") or None,   # MT isolation (SCALE plan MT-3)
            "observ_id": state.get("observ_id") or None,
            "schema_version": 2,
            "embedding": None,
            "embedding_model": None,
            "embedding_dim": None,
        }

        # coba generate embedding via API (non-blocking failure → tetap insert tanpa embedding)
        from services.llm_config_store import get_embedding_cfg
        emb_cfg = await get_embedding_cfg()
        if emb_cfg:
            try:
                vec = await _get_embedding(embed_text)
                if vec:
                    doc["embedding"] = vec
                    doc["embedding_model"] = emb_cfg["model"]
                    doc["embedding_dim"] = len(vec)
                else:
                    logger.info(f"[SecondBrain] no embedding for {episode_id} (fallback TF)")
            except Exception as e:
                logger.warning(f"[SecondBrain] embedding gen failed for {episode_id}: {e}")

        await collection.insert_one(doc)
        has_vec = "with vector" if doc.get("embedding") else "TF only"
        logger.info(f"[SecondBrain] Episode {episode_id} written for service={state.get('service_name')} ({has_vec})")

        # Event-triggered Pattern Miner (Fase 5): jika episode baru >= N, queue run
        try:
            from agents.pattern_miner import maybe_trigger_pattern_miner
            # fire-and-forget, jangan block write
            import asyncio as _asyncio
            _asyncio.create_task(maybe_trigger_pattern_miner(doc.get("service_name") or state.get("service_name")))
        except Exception as e:
            logger.debug(f"[SecondBrain] maybe_trigger_pattern_miner skip: {e}")

    except Exception as e:
        logger.warning(f"[SecondBrain] write_episode_bg failed (non-fatal) episode_id={episode_id}: {e}")


def is_anomalous_episode(ep: dict) -> bool:
    """Predicate Fase 2.B: hanya episode dengan anomali (error_rate>0 atau MAXOUT atau mongo>0) yang layak auto_resolved."""
    sym = ep.get("symptoms") or {}
    # error_rate >0
    er = sym.get("error_rate")
    if er is not None:
        try:
            if float(er) > 0:
                return True
        except Exception:
            pass
    if sym.get("hpa_status") == "MAXOUT":
        return True
    mc = sym.get("mongo_error_count")
    if mc is not None:
        try:
            if int(mc) > 0:
                return True
        except Exception:
            pass
    return False


async def update_episode_feedback(episode_id: str, feedback: str, note: str | None = None, weight: float | None = None) -> bool:
    """
    Update feedback episode. Return False jika episode tidak ditemukan atau sudah punya feedback.
    Idempotent — tidak overwrite. Support correct/wrong (weight 1.0) dan auto_resolved (weight 0.5).
    """
    try:
        db = get_db()
        collection = db[INCIDENT_EPISODES_COLLECTION]

        existing = await collection.find_one({"episode_id": episode_id}, {"feedback": 1})
        if not existing:
            logger.warning(f"[SecondBrain] Episode {episode_id} not found for feedback")
            return False
        if existing.get("feedback") is not None:
            logger.info(f"[SecondBrain] Episode {episode_id} already has feedback={existing.get('feedback')}, skip")
            return False

        if feedback not in ("correct", "wrong", "auto_resolved"):
            logger.warning(f"[SecondBrain] Invalid feedback value: {feedback}")
            return False

        # weight default per spec: correct/wrong 1.0, auto_resolved 0.5
        if weight is None:
            weight = 0.5 if feedback == "auto_resolved" else 1.0

        await collection.update_one(
            {"episode_id": episode_id},
            {"$set": {
                "feedback": feedback,
                "feedback_weight": weight,
                "feedback_note": note,
                "feedback_at": datetime.now(timezone.utc),
            }}
        )
        logger.info(f"[SecondBrain] Feedback '{feedback}' (weight {weight}) saved for episode {episode_id}")
        return True

    except Exception as e:
        logger.warning(f"[SecondBrain] update_episode_feedback failed episode_id={episode_id}: {e}")
        return False


# ── Reader — Fase 2: Hybrid Search + Dynamic Confidence Scaling ─────────────

def compute_confidence_boost(n_valid: int) -> float:
    """Dynamic boost per NEXTDEV2.md:167 — capped 0.15 (aman, spec 0.15..0.20)."""
    if n_valid < 5:
        return 0.0
    if n_valid < 15:
        return 0.05 + 0.05 * (n_valid - 5) / 10  # 0.05 .. 0.10
    return 0.15


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", text.lower())


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b[t] for t in a if t in b)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _build_query_text(state: dict) -> str:
    parts = [
        state.get("metrics_summary") or "",
        state.get("mongo_summary") or "",
        state.get("trace_summary") or "",
        state.get("service_name") or "",
        state.get("intent") or "",
    ]
    txt = " ".join(parts)
    return txt[:600]


def _build_doc_text(ep: dict) -> str:
    parts = [
        ep.get("metrics_summary") or "",
        ep.get("mongo_summary") or "",
        ep.get("trace_summary") or "",
        ep.get("root_cause") or "",
        str(ep.get("symptoms") or ""),
    ]
    txt = " ".join(parts)
    return txt[:600]


async def read_similar_episodes(
    state: dict,
    limit: int = 10,
    days: int = 30,
    candidate_limit: int = 50,
) -> dict | None:
    """
    Hybrid Search (lapis 1 metadata exact + lapis 2 cosine lokal).
    Return SecondBrainContext or None (graceful).
    Tidak pernah raise — semua error ditelan.
    """
    try:
        service = state.get("service_name")
        if not service:
            return None

        db = get_db()
        coll = db[INCIDENT_EPISODES_COLLECTION]

        # Lapis 1 — metadata exact
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q: dict = {
            "service_name": service,
            "feedback": {"$ne": "wrong"},
            "timestamp": {"$gte": since},
        }
        # MT isolation (SCALE plan MT-4): workspace_id=None → legacy behavior
        # (episode global/lama); workspace_id ada → hanya episode workspace itu.
        ws_id = state.get("workspace_id")
        if ws_id:
            q["workspace_id"] = ws_id
        cursor = coll.find(q).sort("timestamp", -1).limit(candidate_limit)
        candidates = await cursor.to_list(length=candidate_limit)

        if not candidates:
            # fallback tanpa timestamp filter (cold start / data lama)
            q2 = {"service_name": service, "feedback": {"$ne": "wrong"}}
            if ws_id:
                q2["workspace_id"] = ws_id
            candidates = await coll.find(q2).sort("timestamp", -1).limit(candidate_limit).to_list(length=candidate_limit)
            if not candidates:
                return {
                    "pattern_recognized": False,
                    "similar_episodes": 0,
                    "total_candidates": 0,
                    "probable_cause": None,
                    "probable_cause_ratio": 0.0,
                    "confidence_boost": 0.0,
                    "confidence_tier": "INFO_ONLY",
                    "match_level": "Unknown Pattern",
                    "suggested_focus": ["full fan-out"],
                    "historical_resolution": "belum ada data historis",
                    "top_matches": [],
                    "excluded_wrong": 0,
                }

        # hitung excluded_wrong untuk audit
        total_for_service = await coll.count_documents({"service_name": service})
        excluded_wrong = await coll.count_documents({"service_name": service, "feedback": "wrong"})

        # Lapis 2 — semantic: coba vector embeddings API, fallback TF cosine lokal
        query_text = _build_query_text(state)
        # coba ambil query embedding jika provider bukan local
        query_vec: Optional[list[float]] = None
        use_vector = False
        from services.llm_config_store import get_embedding_cfg
        if await get_embedding_cfg():
            try:
                query_vec = await _get_embedding(query_text)
                use_vector = query_vec is not None
                if use_vector:
                    logger.info(f"[SecondBrain] READ using vector (dim={len(query_vec)})")
            except Exception as e:
                logger.warning(f"[SecondBrain] query embedding failed, fallback TF: {e}")

        scored = []
        if use_vector and query_vec:
            q_counter = Counter(_tokenize(query_text))  # fallback untuk doc tanpa vector
            for ep in candidates:
                vec = ep.get("embedding")
                if vec and isinstance(vec, list) and len(vec) == len(query_vec):
                    sim = _vector_cosine(query_vec, vec)
                else:
                    # fallback TF untuk episode lama tanpa embedding
                    d_counter = Counter(_tokenize(_build_doc_text(ep)))
                    sim = _cosine(q_counter, d_counter)
                # bonus kecil jika root_cause keyword overlap
                rc = (ep.get("root_cause") or "").lower()
                if rc and rc in query_text.lower():
                    sim = min(1.0, sim + 0.03)
                scored.append((sim, ep))
        else:
            # TF lokal murni (default)
            q_counter = Counter(_tokenize(query_text))
            for ep in candidates:
                doc_text = _build_doc_text(ep)
                d_counter = Counter(_tokenize(doc_text))
                sim = _cosine(q_counter, d_counter)
                rc = (ep.get("root_cause") or "").lower()
                if rc and rc in query_text.lower():
                    sim = min(1.0, sim + 0.03)
                scored.append((sim, ep))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        # n_valid = semua candidates yang feedback in (correct, auto_resolved, None) → di sini semua non-wrong = valid
        n_valid = len(candidates)  # karena sudah filter wrong
        boost = compute_confidence_boost(n_valid)
        tier = "INFO_ONLY" if n_valid < 5 else "PARTIAL" if n_valid < 15 else "FULL"

        # probable cause = majority root_cause di top matches (atau di candidates jika top similarity rendah)
        # pakai candidates untuk stabilitas
        from collections import Counter as CC
        rc_counter = CC(ep.get("root_cause") or "unknown" for _, ep in scored)
        probable = rc_counter.most_common(1)[0][0] if rc_counter else None
        ratio = rc_counter[probable] / len(scored) if probable else 0.0

        # match level dari top similarity
        # Spec asli: >=0.82 Known / 0.65-0.82 Partial (untuk Atlas embedding 1536d).
        # Implementasi lokal TF cosine lebih rendah → kalibrasi threshold lokal:
        # Known >=0.55, Partial 0.30-0.55, Unknown <0.30 (tetap bedakan 3 tier, DRY tanpa Atlas)
        top_sim = top[0][0] if top else 0.0
        if top_sim >= 0.55:
            match_level = "Known Pattern"
            recognized = True
        elif top_sim >= 0.30:
            match_level = "Partial Match"
            recognized = n_valid >= 3  # partial tetap recognized jika ada cukup data
        else:
            match_level = "Unknown Pattern"
            recognized = False

        # suggested_focus mapping
        if probable == "downstream":
            suggested = ["cek boundary trace", "skip CPU check"]
        elif probable == "service-fault":
            suggested = ["cek DB connection", "trace internal"]
        elif probable == "unknown":
            suggested = ["full fan-out"]
        else:
            suggested = ["full fan-out"]

        # historical resolution string
        if n_valid >= 15:
            hist = "biasanya resolve dalam 18-23 menit (full pattern)"
        elif n_valid >= 5:
            hist = f"historical {n_valid} episode, probable {probable} {ratio:.0%}"
        else:
            hist = "belum ada pola kuat (N<5, informational only)"

        top_matches = [
            {
                "episode_id": ep.get("episode_id"),
                "root_cause": ep.get("root_cause"),
                "similarity": round(sim, 3),
                "timestamp": ep.get("timestamp").isoformat() if ep.get("timestamp") else None,
                "feedback": ep.get("feedback"),
            }
            for sim, ep in top
        ]

        ctx = {
            "pattern_recognized": recognized,
            "similar_episodes": n_valid,
            "total_candidates": len(candidates),
            "probable_cause": probable,
            "probable_cause_ratio": ratio,
            "confidence_boost": boost,
            "confidence_tier": tier,
            "match_level": match_level,
            "top_similarity": round(top_sim, 3),
            "suggested_focus": suggested,
            "historical_resolution": hist,
            "top_matches": top_matches,
            "top_matches_brief": ", ".join(f"{m['episode_id']}({m['root_cause']}:{m['similarity']})" for m in top_matches[:3]),
            "excluded_wrong": excluded_wrong,
            "total_for_service": total_for_service,
        }
        logger.info(f"[SecondBrain] READ service={service} N_valid={n_valid} boost={boost:.3f} tier={tier} match={match_level} top_sim={top_sim:.3f}")
        return ctx

    except Exception as e:
        logger.warning(f"[SecondBrain] read_similar_episodes failed (non-fatal): {e}")
        return None
