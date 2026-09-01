"""
Investigation Planner — Fase 4B + Gap 3 (pure, no LLM, DRY)
Mapping konservatif + adaptive fan-out:
- base nodes dari MAP hypothesis (tetap)
- confidence-based width (narrow/expand)
- service_type-aware adjustment
- skip_hints blacklist (dari triage) — diaplikasikan TERAKHIR
Safety floor: minimal 1 collector selalu jalan.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional

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

# Full set untuk ekspansi confidence rendah
FULL_SET: List[str] = [NODES["mongo"], NODES["metrics"], NODES["trace"]]

# skip_hints dari triage_agent → node graph (string aktual dari triage, BUKAN tebakan)
SKIP_HINT_TO_NODE = {
    "hpa_metrics": NODES["metrics"],
    "cpu_metrics": NODES["metrics"],
    "memory_metrics": NODES["metrics"],
    "prometheus metrics": NODES["metrics"],
    "trace detail": NODES["trace"],
    "health check": NODES["health"],
}

CONFIDENCE_NARROW = 0.80   # confidence tinggi → narrow (kecuali unknown)
CONFIDENCE_EXPAND = 0.45   # confidence rendah → expand ke full set

# Override per service_type — hanya berlaku untuk hypothesis spesifik
SERVICE_TYPE_ADJUSTMENTS = {
    "worker": {
        "remove": [NODES["trace"]],
        "add": [NODES["mongo"]],
    },
    "gateway": {
        "remove": [NODES["mongo"]],
        "add": [NODES["health"], NODES["trace"]],
    },
    "database": {
        "remove": [NODES["trace"]],
        "add": [NODES["health"]],
    },
    "api": {"remove": [], "add": []},
}

ALLOWED_SERVICE_TYPES = {"api", "worker", "database", "gateway"}


def _apply_confidence(nodes: List[str], hypothesis: str, confidence: float) -> List[str]:
    """Adjust node list berdasarkan confidence.
    HIGH (>=0.80) + hypothesis spesifik → narrow ke collector prioritas pertama.
    LOW (<=0.45) → expand ke full set."""
    if confidence >= CONFIDENCE_NARROW:
        if hypothesis != "unknown":
            return nodes[:1]
        return nodes
    if confidence <= CONFIDENCE_EXPAND:
        expanded = list(nodes)
        for node in FULL_SET:
            if node not in expanded:
                expanded.append(node)
        return expanded
    return nodes


def _apply_service_type(nodes: List[str], service_type: Optional[str]) -> List[str]:
    if not service_type or service_type not in SERVICE_TYPE_ADJUSTMENTS:
        return nodes
    adj = SERVICE_TYPE_ADJUSTMENTS[service_type]
    result = [n for n in nodes if n not in adj.get("remove", [])]
    for node in adj.get("add", []):
        if node not in result:
            result.append(node)
    return result


def _apply_skip_hints(nodes: List[str], skip_hints: List[str]) -> List[str]:
    """Blacklist — node yang di-hint triage untuk di-skip dihapus dari fan-out.
    Diaplikasikan TERAKHIR (setelah confidence/service_type) agar ekspansi
    tidak menambahkan collector yang memang tidak dibutuhkan."""
    to_skip = {SKIP_HINT_TO_NODE[h] for h in (skip_hints or []) if h in SKIP_HINT_TO_NODE}
    if not to_skip:
        return nodes
    result = [n for n in nodes if n not in to_skip]
    return result


def plan(state: dict) -> dict:
    """
    Tentukan planned_nodes secara adaptif:
    base MAP → confidence width → service_type → skip_hints blacklist → safety floor.
    Fallback ke unknown jika triage None/invalid.
    Tambah span_agent jika preset_trace_ids ada dan trace dibutuhkan (Fase 4A DRY).
    Return {"nodes": [...], "reason": str, "hypothesis": str}
    """
    triage = state.get("triage_result") or {}
    hyp = triage.get("hypothesis") if isinstance(triage, dict) else None
    if hyp not in MAP:
        if triage:
            logger.info(f"[Planner] unknown hypothesis '{hyp}' → fallback unknown")
        hyp = "unknown"

    confidence = 0.5
    skip_hints: List[str] = []
    if isinstance(triage, dict):
        try:
            confidence = float(triage.get("confidence") or 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        skip_hints = triage.get("skip_hints") or []
    service_type = state.get("service_type")

    base = list(MAP[hyp])
    # Fix #189: offer "investigate lebih dalam" → paksa full fan-out (semua collector),
    # jangan narrow ulang oleh confidence/service_type. Langsung ke full set.
    if state.get("force_full_fanout"):
        nodes = [NODES["mongo"], NODES["metrics"], NODES["trace"]]
        reason = f"FORCE_FULL (investigate offer) hypothesis={hyp} → {nodes}"
    else:
        nodes = _apply_confidence(base, hyp, confidence)
        nodes = _apply_service_type(nodes, service_type)
        nodes = _apply_skip_hints(nodes, skip_hints)

        # Safety floor: jangan pernah kosong
        if not nodes:
            nodes = base[:1] if base else [NODES["mongo"]]

        reason = (
            f"hypothesis={hyp} confidence={confidence:.2f} service_type={service_type or 'none'} "
            f"skip_hints={skip_hints} base={base} → {nodes}"
        )

    # Fase 4A: span fan-in jika watchdog traceId dan hipotesis butuh trace
    needs_trace = hyp in ("regression_post_deploy", "downstream_timeout", "traffic_spike", "unknown")
    if needs_trace and state.get("preset_trace_ids"):
        if NODES["span"] not in nodes:
            nodes.append(NODES["span"])
            reason += " + span (preset_trace_ids)"

    logger.info(f"[Planner] {reason}")
    return {"nodes": nodes, "reason": reason, "hypothesis": hyp}