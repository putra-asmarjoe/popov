"""
Knowledge Retrieval — Gap 1 Fase 4: relevance-based knowledge search.

Replaces flat document dump with ranked retrieval:
  - Jalur A: Deterministic Bypass (agent_docs with service match → score=1.0)
  - Jalur B: Vector Search (cosine similarity on embeddings)
  - Fallback: keyword overlap when embeddings unavailable

Access control: knowledge_library is owner-only — queried only via refs
(workspace_knowledge_refs, service_knowledge_refs), never directly.
"""
import logging
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

LIBRARY_COLLECTION = "knowledge_library"
AGENT_DOCS_COLLECTION = "agent_docs"
SERVICE_LIBRARY_COLLECTION = "service_library"
WORKSPACE_KB_COLLECTION = "workspace_knowledge"
WORKSPACE_REFS_COLLECTION = "workspace_knowledge_refs"
SERVICE_REFS_COLLECTION = "service_knowledge_refs"
AGENT_DOC_REFS_COLLECTION = "agent_doc_refs"


# ── Cosine Similarity ────────────────────────────────────────────────────────

def _vector_cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def _keyword_overlap(query: str, content: str) -> float:
    """Simple keyword overlap score (fallback when no embeddings)."""
    if not query or not content:
        return 0.0
    q_tokens = set(query.lower().split())
    c_tokens = set(content.lower().split())
    if not q_tokens or not c_tokens:
        return 0.0
    intersection = q_tokens & c_tokens
    union = q_tokens | c_tokens
    return len(intersection) / len(union) if union else 0.0


# ── Collection Loaders (with access control) ─────────────────────────────────

async def _load_library_docs_via_refs(workspace_id: str, service_name: str) -> List[Dict[str, Any]]:
    """Load knowledge_library docs linked to this workspace via refs (access-controlled).
    
    Queries both workspace_knowledge_refs AND service_knowledge_refs,
    then deduplicates by libraryId.
    """
    db = get_db()
    lib_id_set = set()

    # Via workspace_knowledge_refs
    ref_cursor = db[WORKSPACE_REFS_COLLECTION].find(
        {"workspaceId": workspace_id}, {"libraryId": 1}
    )
    ref_docs = await ref_cursor.to_list(length=100)
    for ref in ref_docs:
        lid = ref.get("libraryId")
        if lid:
            lib_id_set.add(lid)

    # Via service_knowledge_refs — schema: {serviceLibraryId: str, knowledgeLibraryId: str}
    # (bukan workspaceId/libraryId). Resolve service_library by name dulu (Fix acceptance test 2026-09-01).
    if service_name:
        svc_norm = (service_name or "").strip().lower()
        svc_variants = {
            svc_norm,
            svc_norm.replace("-", "_"),
            svc_norm.replace("_", "-"),
        }
        svc_libs = await db[SERVICE_LIBRARY_COLLECTION].find(
            {"serviceId": {"$in": list(svc_variants)}},
            {"_id": 1},
        ).to_list(length=50)
        svc_lib_ids = [str(s["_id"]) for s in svc_libs]
        if svc_lib_ids:
            svc_ref_cursor = db[SERVICE_REFS_COLLECTION].find(
                {"serviceLibraryId": {"$in": svc_lib_ids}}, {"knowledgeLibraryId": 1}
            )
            async for ref in svc_ref_cursor:
                kid = ref.get("knowledgeLibraryId")
                if kid:
                    lib_id_set.add(kid)

    if not lib_id_set:
        return []

    from bson import ObjectId
    oids = []
    for lid in lib_id_set:
        try:
            oids.append(ObjectId(lid))
        except Exception:
            continue

    if not oids:
        return []

    cursor = db[LIBRARY_COLLECTION].find(
        {"_id": {"$in": oids}},
        {"_id": 1, "name": 1, "folder": 1, "content": 1, "meta": 1, "embedding": 1, "embedding_model": 1},
    )
    docs = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        docs.append(doc)

    return docs


async def _load_workspace_knowledge(workspace_id: str) -> List[Dict[str, Any]]:
    """Load workspace_knowledge items (already workspace-scoped)."""
    db = get_db()
    cursor = db[WORKSPACE_KB_COLLECTION].find(
        {"workspaceId": workspace_id},
        {"_id": 1, "name": 1, "folder": 1, "content": 1, "embedding": 1, "embedding_model": 1},
    )
    docs = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        docs.append(doc)
    return docs


async def _load_agent_docs_via_refs(workspace_id: str) -> List[Dict[str, Any]]:
    """Load agent_docs linked to this workspace via agent_doc_refs."""
    db = get_db()
    refs = await db[AGENT_DOC_REFS_COLLECTION].find(
        {"workspaceId": workspace_id}, {"docCategory": 1, "docKey": 1}
    ).to_list(length=100)

    if not refs:
        return []

    docs = []
    for ref in refs:
        doc = await db[AGENT_DOCS_COLLECTION].find_one(
            {"category": ref["docCategory"], "key": ref["docKey"]},
            {"_id": 0, "category": 1, "key": 1, "body": 1, "meta": 1, "embedding": 1, "embedding_model": 1},
        )
        if doc:
            docs.append(doc)
    return docs


# ── Deterministic Bypass ─────────────────────────────────────────────────────

# Categories that are always relevant when service matches (technical docs)
_BYPASS_CATEGORIES = frozenset({"services", "connections", "schemas"})


async def _deterministic_bypass(
    workspace_id: str, service_name: str
) -> List[Tuple[Dict[str, Any], float]]:
    """
    Jalur A: agent_docs with matching service name → always included (score=1.0).

    BYPASS ACCESS CONTROL — Intentional design:
    agent_docs are system-level (routing, architecture, thresholds, schemas).
    They are globally relevant to any workspace investigating the same service.
    Workspace scoping is NOT applied here — these docs are not user-specific.
    Vector search path (Jalur B) handles workspace-scoped knowledge_library.
    """
    if not service_name:
        return []

    db = get_db()
    # Normalize service name for matching (hyphen ↔ underscore)
    norm_name = service_name.replace("-", "_").replace(" ", "_").lower()
    alt_name = service_name.replace("_", "-").replace(" ", "-").lower()

    # Find agent_docs where key matches service name pattern
    cursor = db[AGENT_DOCS_COLLECTION].find(
        {
            "$or": [
                {"key": {"$regex": norm_name, "$options": "i"}},
                {"key": {"$regex": alt_name, "$options": "i"}},
            ],
            "category": {"$in": list(_BYPASS_CATEGORIES)},
        },
        {"_id": 0, "category": 1, "key": 1, "body": 1, "meta": 1},
    )
    bypass_docs = []
    async for doc in cursor:
        bypass_docs.append((doc, 1.0))

    if bypass_docs:
        logger.info(
            f"[knowledge_retrieval] bypass: {len(bypass_docs)} agent_docs matched "
            f"service='{service_name}' categories={_BYPASS_CATEGORIES}"
        )

    return bypass_docs


# ── Main Search Function ─────────────────────────────────────────────────────

async def search_relevant_knowledge(
    query_text: str,
    workspace_id: str,
    service_name: str = "",
    top_k: Optional[int] = None,
) -> Tuple[List[Tuple[Dict[str, Any], float]], str]:
    """
    Search knowledge documents relevant to the current investigation.

    Returns:
        (results, retrieval_method)
        results: list of (doc, score) tuples, sorted by score descending
        retrieval_method: "vector" | "keyword_fallback" | "no_data"
    """
    top_k = top_k or settings.knowledge_top_k
    threshold = settings.knowledge_threshold
    min_query_len = settings.knowledge_min_query_len

    if not workspace_id:
        return [], "no_data"

    # Jalur A: Deterministic Bypass
    bypass_docs = await _deterministic_bypass(workspace_id, service_name)

    # Jalur B: Vector Search
    all_docs = []

    # Load from all sources (access-controlled)
    library_docs = await _load_library_docs_via_refs(workspace_id, service_name)
    ws_knowledge = await _load_workspace_knowledge(workspace_id)
    agent_docs = await _load_agent_docs_via_refs(workspace_id)

    all_docs.extend(library_docs)
    all_docs.extend(ws_knowledge)
    all_docs.extend(agent_docs)

    if not all_docs and not bypass_docs:
        return [], "no_data"

    # Filter docs that have embeddings
    embedded_docs = [d for d in all_docs if d.get("embedding")]
    non_embedded_docs = [d for d in all_docs if not d.get("embedding")]

    # Decide retrieval method
    has_query = query_text and len(query_text.strip()) >= min_query_len
    has_embeddings = len(embedded_docs) > 0

    if has_embeddings and has_query:
        retrieval_method = "vector"
        # Embed query
        from services.second_brain import _get_embedding
        from services.llm_config_store import get_embedding_cfg
        emb_cfg = await get_embedding_cfg()
        max_chars = (emb_cfg.get("max_chars") if emb_cfg else None) or settings.embedding_max_chars
        query_vec = await _get_embedding(query_text[:max_chars].strip())

        if query_vec:
            # Compute cosine similarity
            scored = []
            for doc in embedded_docs:
                sim = _vector_cosine(query_vec, doc.get("embedding", []))
                # Boost if doc relates to service_name
                doc_key = (doc.get("key") or doc.get("name") or "").lower()
                if service_name and service_name.lower() in doc_key:
                    sim = min(1.0, sim + 0.1)
                scored.append((doc, round(sim, 4)))

            scored.sort(key=lambda x: x[1], reverse=True)
            # Apply threshold with floor rule (always ≥1)
            filtered = [d for d in scored if d[1] >= threshold]
            if not filtered and scored:
                filtered = [scored[0]]
            vector_results = filtered[:top_k]
        else:
            # Embedding failed — fallback to keyword
            retrieval_method = "keyword_fallback"
            vector_results = _keyword_fallback(query_text, embedded_docs, top_k)
    else:
        retrieval_method = "keyword_fallback"
        vector_results = _keyword_fallback(query_text, all_docs, top_k)

    # Combine: bypass first, then vector results
    results = bypass_docs + vector_results

    # Deduplicate by doc identity (key/category or _id)
    seen = set()
    deduped = []
    for doc, score in results:
        doc_id = doc.get("_id") or f"{doc.get('category')}:{doc.get('key')}"
        if doc_id not in seen:
            seen.add(doc_id)
            deduped.append((doc, score))

    return deduped, retrieval_method


def _keyword_fallback(
    query_text: str, docs: List[Dict[str, Any]], top_k: int
) -> List[Tuple[Dict[str, Any], float]]:
    """Keyword overlap fallback when embeddings unavailable."""
    if not query_text:
        # No query — return all docs with neutral score
        return [(d, 0.5) for d in docs[:top_k]]

    scored = []
    for doc in docs:
        content = doc.get("content") or doc.get("body") or ""
        score = _keyword_overlap(query_text, content)
        scored.append((doc, round(score, 4)))

    scored.sort(key=lambda x: x[1], reverse=True)
    # Floor rule: always ≥1
    filtered = [d for d in scored if d[1] > 0]
    if not filtered and scored:
        filtered = [scored[0]]
    return filtered[:top_k]


# ── Format Knowledge Context (Fase 5) ───────────────────────────────────────

def format_knowledge_context(
    results: List[Tuple[Dict[str, Any], float]],
    retrieval_method: str = "",
) -> str:
    """
    Format ranked knowledge results into markdown for Correlation Agent.
    Uses rank-aware truncation: drop whole docs, never cut in the middle.
    """
    if not results:
        return ""

    max_total = settings.knowledge_max_total_chars
    max_item = settings.knowledge_max_item_chars
    parts = []
    chars_used = 0
    docs_dropped = 0

    header = "### Knowledge Context (Ranked by Relevance)\n\n"
    header_len = len(header)

    for doc, score in results:
        content = doc.get("content") or doc.get("body") or ""
        if not content.strip():
            continue

        # Per-doc truncation (rank-aware: drop whole docs, never cut mid-sentence)
        if len(content) > max_item:
            content = content[:max_item].rsplit(" ", 1)[0] + " …[truncated]"

        # Doc identity
        name = doc.get("name") or doc.get("key") or "untitled"
        folder = doc.get("folder") or doc.get("category") or ""
        meta = doc.get("meta") or {}
        prefix = f"[Score: {score:.2f}] **{name}**"
        if folder:
            prefix += f" ({folder})"
        # Show key metadata tags if present
        meta_tags = []
        if meta.get("criticality"):
            meta_tags.append(f"criticality={meta['criticality']}")
        if meta.get("service_id"):
            meta_tags.append(f"service={meta['service_id']}")
        if meta_tags:
            prefix += f" [{', '.join(meta_tags)}]"
        prefix += "\n\n"

        block = prefix + content.strip() + "\n\n"
        block_len = len(block)

        # Check budget (first doc gets extra space for header)
        remaining = max_total - chars_used - (header_len if not parts else 0)
        if block_len > remaining:
            docs_dropped += 1
            continue

        parts.append(block)
        chars_used += block_len

    if not parts:
        return ""

    context = header + "".join(parts)

    # Log stats
    logger.info(
        f"[knowledge_agent] format_context: docs={len(results)}, "
        f"included={len(parts)}, dropped={docs_dropped}, "
        f"chars_used={chars_used}/{max_total}, max_item={max_item}, method={retrieval_method}"
    )

    return context.strip()
