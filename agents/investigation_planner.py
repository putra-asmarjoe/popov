"""
Investigation Planner — Fase 4B (pure, no LLM, DRY)
Mapping konservatif: regression_post_deploy tetap mongo+trace (tanpa health)
"""
from __future__ import annotations
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# Valid node names di graph/workflow.py
NODES = {
    "mongo": "mongo_agent",
    "metrics": "metrics_agent",
    "trace": "trace_agent",
    "health": "health_agent",
    "span": "span_agent",
}

MAP: Dict[str, List[str]] = {
    "regression_post_deploy": [NODES["mongo"], NODES["trace"]],
    "downstream_timeout": [NODES["trace"], NODES["health"]],
    "hpa_maxout": [NODES["metrics"], NODES["mongo"]],
    "db_connection": [NODES["health"], NODES["mongo"]],
    "traffic_spike": [NODES["metrics"], NODES["trace"]],
    "unknown": [NODES["mongo"], NODES["metrics"], NODES["trace"]],
}


def plan(state: dict) -> dict:
    """
    Tentukan planned_nodes berdasarkan triage_result.hypothesis.
    Fallback ke unknown jika triage None/invalid.
    Tambah span_agent jika preset_trace_ids ada dan trace dibutuhkan (Fase 4A DRY).
    Return {"nodes": [...], "reason": str}
    """
    triage = state.get("triage_result") or {}
    hyp = triage.get("hypothesis") if isinstance(triage, dict) else None
    if hyp not in MAP:
        # triage None atau unknown → fallback
        if triage:
            logger.info(f"[Planner] unknown hypothesis '{hyp}' → fallback unknown")
        hyp = "unknown"

    nodes = list(MAP[hyp])
    reason = f"hypothesis={hyp} → {nodes}"

    # Fase 4A: span fan-in jika watchdog traceId dan hipotesis butuh trace
    # regression_post_deploy & downstream & traffic butuh trace → sertakan span jika preset ada
    needs_trace = hyp in ("regression_post_deploy", "downstream_timeout", "traffic_spike", "unknown")
    if needs_trace and state.get("preset_trace_ids"):
        if NODES["span"] not in nodes:
            nodes.append(NODES["span"])
            reason += " + span (preset_trace_ids)"

    logger.info(f"[Planner] {reason}")
    return {"nodes": nodes, "reason": reason, "hypothesis": hyp}
