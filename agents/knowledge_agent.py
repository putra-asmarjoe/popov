"""
Knowledge Agent — FE-7 (Gap 1 refactor).
Node pipeline TANPA LLM: menyusun `knowledge_context` untuk correlation_agent.

Gap 1: dari flat document dump → relevance-based ranked retrieval.
- Query builder: bersih dari hypothesis + service_name + intent
- Retrieval: vector search (cosine similarity) + deterministic bypass
- Fallback: keyword overlap jika embedding tidak tersedia
- Output: ranked docs dengan relevance score

Fan-in dari fan-out observability → knowledge_agent → correlation_agent.
"""
import logging
from typing import Any, Dict, List

from config.settings import settings

logger = logging.getLogger(__name__)


def _build_query_text(state: dict) -> str:
    """
    Build clean query text from investigation context.
    Prioritas: hypothesis > service_name > intent.
    TIDAK menggunakan raw logs/summaries (merusak embedding quality).
    """
    query_parts = []

    # Hypothesis dari triage (paling spesifik)
    triage = state.get("triage_result") or {}
    hypothesis = triage.get("hypothesis") if isinstance(triage, dict) else None
    if hypothesis and hypothesis != "unknown":
        query_parts.append(hypothesis.replace("_", " "))

    # Service name
    service_name = state.get("service_name") or ""
    if service_name:
        query_parts.append(f"service {service_name}")

    # Error type / alert name dari triage signals (jika ada)
    signals = triage.get("signals") if isinstance(triage, dict) else {}
    if isinstance(signals, dict):
        # focus_hints bisa berisi info tambahan
        focus = triage.get("focus_hints") or []
        if isinstance(focus, list) and focus:
            query_parts.append(" ".join(focus[:2]))

    # Intent sebagai fallback
    intent = state.get("intent") or ""
    query_str = " ".join(filter(None, query_parts)).strip()
    if len(query_str) < settings.knowledge_min_query_len and intent:
        query_parts.append(intent)
        query_str = " ".join(filter(None, query_parts)).strip()

    return query_str


async def knowledge_agent(state: dict) -> dict:
    """
    Susun knowledge_context dengan relevance-based retrieval.
    Fallback ke build_workspace_context jika search tidak tersedia.
    """
    from state.schema import AgentState  # noqa: F401
    workspace_id = state.get("workspace_id")
    service_name = state.get("service_name") or ""
    agents_visited = ["knowledge_agent"]

    if not workspace_id:
        return {
            "knowledge_context": "",
            "agents_visited": agents_visited,
        }

    # Build clean query
    query_text = _build_query_text(state)
    logger.info(f"[knowledge_agent] query_text={query_text[:100]!r}")

    # Relevance-based retrieval
    try:
        from services.knowledge_retrieval import search_relevant_knowledge, format_knowledge_context

        results, retrieval_method = await search_relevant_knowledge(
            query_text=query_text,
            workspace_id=workspace_id,
            service_name=service_name,
        )

        logger.info(
            f"[knowledge_agent] retrieval_method={retrieval_method}, "
            f"results={len(results)}, "
            f"top_score={results[0][1] if results else 0:.3f}"
        )

        context = format_knowledge_context(results, retrieval_method)

        if context:
            return {
                "knowledge_context": context,
                "agents_visited": agents_visited,
            }

    except Exception as e:
        logger.warning(f"[knowledge_agent] search_relevant_knowledge failed, falling back: {e}")

    # Fallback: legacy flat context
    try:
        from services.workspace_knowledge import build_workspace_context
        ws_ctx = await build_workspace_context(workspace_id)
        if ws_ctx:
            logger.info(f"[knowledge_agent] fallback: legacy context injected ws={workspace_id}")
            return {
                "knowledge_context": ws_ctx,
                "agents_visited": agents_visited,
            }
    except Exception as e:
        logger.warning(f"[knowledge_agent] legacy fallback also failed: {e}")

    return {
        "knowledge_context": "",
        "agents_visited": agents_visited,
    }
