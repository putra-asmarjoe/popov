from typing import Union, List
from langgraph.graph import StateGraph, END
from state.schema import AgentState
from agents.supervisor import supervisor_agent
from agents.mongo_agent import mongo_agent
from agents.metrics_agent import metrics_agent
from agents.trace_agent import trace_agent
from agents.correlation_agent import correlation_agent
from agents.health_agent import health_agent
from agents.data_agent import data_agent
from agents.follow_up_agent import follow_up_agent
from agents.response_agent import response_agent
from agents.span_agent import span_agent
from agents.triage_agent import triage_agent
from agents.knowledge_agent import knowledge_agent
from agents.ticket_agent import ticket_agent
from agents.project_agent import project_agent
import logging

logger = logging.getLogger(__name__)


# CHATFLOW V2.1 (Tahap 4): router otonom setelah correlation — PURE FUNCTION.
# Hanya membaca state, TIDAK memodifikasinya (semua mutasi di correlation_agent).
def route_after_correlation(state: AgentState) -> List[str]:
    """
    Router pure — hanya membaca state, tidak memodifikasinya.

    Logika:
    1. Bila AUTONOMOUS_LOOP_ENABLED=False → selalu ke response_agent (feature flag off)
    2. Bila confidence rendah + ada gap_nodes + loop belum melebihi batas
       → trigger agen-agen yang terlewat secara paralel (fan-out)
    3. Selain itu → ke response_agent

    PENTING: gap_nodes berisi nama node graph valid (mis. "metrics_agent"),
    BUKAN deskripsi human-readable dari data_gaps.
    """
    from state.constants import CONFIDENCE_THRESHOLD, AUTO_LOOP_MAX, AUTONOMOUS_LOOP_ENABLED

    if not AUTONOMOUS_LOOP_ENABLED:
        return ["response_agent"]

    confidence = state.get("investigation_confidence", 1.0)
    gap_nodes = state.get("gap_nodes") or []
    loop_count = state.get("internal_loop_count", 0)

    # loop_count sudah di-increment di correlation_agent sebelum router dipanggil.
    if confidence < CONFIDENCE_THRESHOLD and gap_nodes and loop_count <= AUTO_LOOP_MAX:
        return gap_nodes  # fan-out paralel agen yang terlewat

    return ["response_agent"]


# Gap 5 Fase 3: node yang boleh di-trigger langsung via action chip "investigate:<node>"
DIRECT_FANOUT_NODES = {"mongo_agent", "metrics_agent", "trace_agent", "health_agent"}


def _route(state: AgentState) -> Union[str, List[str]]:
    """Conditional edge: baca next_agent dari state. Selective fan-out via Investigation Planner (FASE 4B) + span jika preset."""
    next_a = state.get("next_agent", "end")
    error = state.get("error")

    if error:
        logger.warning(f"Routing to end due to error: {error}")
        return END

    # Gap 5: chip "investigate:<node>" → direct route ke collector, bypass planner/NLU
    if state.get("routing_flag") == "direct_fanout" and next_a in DIRECT_FANOUT_NODES:
        logger.info(f"[Route] direct fan-out → {next_a} (investigate chip)")
        return [next_a]

    if next_a == "mongo_agent":
        # Gap 3 Fase 1: planner_node yang jalankan plan() dan persist planned_nodes ke state
        return ["planner_node"]

    route_map = {
        "triage_agent":    "triage_agent",
        "health_agent":    "health_agent",
        "data_agent":      "data_agent",
        "follow_up_agent": "follow_up_agent",
        "response_agent":  "response_agent",
        "span_agent":      "span_agent",
        "ticket_agent":    "ticket_agent",
        "project_agent":   "project_agent",
        "end":             END,
    }
    return route_map.get(next_a, END)


def planner_node(state: AgentState) -> dict:
    """Gap 3 Fase 1: jalankan plan() (adaptive fan-out) dan PERSIST planned_nodes ke AgentState.
    Conditional edge tidak bisa mutasi state (langgraph 0.6 rebuild per step) —
    maka plan() dipindah ke node nyata yang return planned_nodes/planner_reason."""
    agents_visited = state.get("agents_visited", []) + ["planner_node"]
    try:
        from agents.investigation_planner import plan
        planned = plan(state)
        nodes = planned["nodes"]
        reason = planned["reason"]
    except Exception as e:
        logger.warning(f"[Planner] failed, fallback full fan-out: {e}")
        nodes = ["mongo_agent", "metrics_agent", "trace_agent"]
        reason = f"fallback full fan-out ({e})"
    # Fase 4A: span jika preset_trace_ids + trace dibutuhkan (fallback, plan() sudah handle)
    if state.get("preset_trace_ids") and "span_agent" not in nodes:
        hyp = (state.get("triage_result") or {}).get("hypothesis", "unknown")
        if hyp in ("regression_post_deploy", "downstream_timeout", "traffic_spike", "unknown"):
            if "trace_agent" in nodes:
                nodes.append("span_agent")
                reason += " + span (preset_trace_ids)"
    return {
        "planned_nodes": nodes,
        "planner_reason": reason,
        "next_agent": "mongo_agent",
        "agents_visited": agents_visited,
    }


def _route_fanout(state: AgentState) -> List[str]:
    """Conditional edge dari planner_node → fan-out collector berdasarkan planned_nodes."""
    nodes = state.get("planned_nodes") or []
    if not nodes:
        nodes = ["mongo_agent", "metrics_agent", "trace_agent"]
        logger.warning(f"[Planner] planned_nodes kosong, fallback full fan-out → {nodes}")
    logger.info(f"[Planner] fan-out {state.get('planner_reason','?')} → {nodes}")
    return nodes


def _route_span_agent(state: AgentState) -> str:
    """
    FASE 4A: Span sebagai bagian fan-out incident → knowledge_agent (FE-7, lalu correlation),
    Span mandiri (detail trace) → response_agent.

    Fix bahasa ID (CPRO-19): deteksi incident jangan via `next_agent`/`agents_visited` —
    keduanya rawan race di fan-out paralel (mongo_agent menimpa next_agent last-wins,
    agents_visited belum tentu merge saat span selesai). Penanda incident yang ANDAL:
    `triage_result` (di-set triage sebelum fan-out) atau `planned_nodes` (planner_node).
    Salah route → span diformat sebagai jalur mandiri (prompt tanpa reply_language) →
    jawaban jatuh ke bahasa default model (Indonesia).
    """
    # Incident fan-out: ada triage (pipeline insiden) ATAU planned_nodes dari planner.
    if state.get("triage_result") is not None or state.get("planned_nodes"):
        return "knowledge_agent"
    # Fallback non-deterministik parallel: mongo sudah visited (masih berguna utk
    # kondisi mongo selesai lebih dulu).
    if "mongo_agent" in state.get("agents_visited", []):
        return "knowledge_agent"
    return "response_agent"


def _route_health_agent(state: AgentState) -> str:
    """
    Fix duplicate telegram untuk downstream_timeout fan-out.
    Health sebagai bagian incident (triage_result ada) → knowledge_agent (fan-in single telegram).
    Health mandiri (supervisor langsung health_agent tanpa triage) → response_agent.
    """
    if state.get("triage_result") is not None:
        return "knowledge_agent"
    # Fallback: bila agents_visited sudah mengandung trace/mongo (fan-out paralel lain) → knowledge
    visited = state.get("agents_visited", [])
    if any(a in visited for a in ("mongo_agent", "metrics_agent", "trace_agent")):
        return "knowledge_agent"
    return "response_agent"


def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("supervisor",        supervisor_agent)
    workflow.add_node("triage_agent",      triage_agent)
    workflow.add_node("mongo_agent",       mongo_agent)
    workflow.add_node("metrics_agent",     metrics_agent)
    workflow.add_node("trace_agent",       trace_agent)
    workflow.add_node("correlation_agent", correlation_agent)
    workflow.add_node("health_agent",      health_agent)
    workflow.add_node("data_agent",        data_agent)
    workflow.add_node("follow_up_agent",   follow_up_agent)
    workflow.add_node("response_agent",    response_agent)
    workflow.add_node("span_agent",        span_agent)
    workflow.add_node("knowledge_agent",   knowledge_agent)  # FE-7
    workflow.add_node("ticket_agent",      ticket_agent)     # Ticket Agent (lane pengelolaan tiket)
    workflow.add_node("project_agent",     project_agent)    # Chat by Project (lane Q&A project, fase 1 read-only)

    # Entry point
    workflow.set_entry_point("supervisor")

    # Supervisor → conditional routing (triage untuk incident, fan-out untuk mongo_agent intent)
    workflow.add_conditional_edges("supervisor", _route)
    # Triage → planner_node (Gap 3: plan() + persist planned_nodes) → fan-out selective
    workflow.add_conditional_edges("triage_agent", _route)
    workflow.add_node("planner_node", planner_node)
    workflow.add_conditional_edges("planner_node", _route_fanout)

    # Fan-in: Semua parallel observability agents → knowledge_agent (FE-7) → correlation
    workflow.add_edge("mongo_agent",       "knowledge_agent")
    workflow.add_edge("metrics_agent",     "knowledge_agent")
    workflow.add_edge("trace_agent",       "knowledge_agent")
    # span_agent → conditional (incident fan-in vs mandiri) — FASE 4A
    workflow.add_conditional_edges("span_agent", _route_span_agent, {
        "knowledge_agent": "knowledge_agent",
        "response_agent": "response_agent",
    })

    # Knowledge agent (universal + workspace) → correlation agent — FE-7
    workflow.add_edge("knowledge_agent", "correlation_agent")

    # Ticket Agent → telegram (konfirmasi deterministik, tanpa LLM tambahan)
    workflow.add_edge("ticket_agent", "response_agent")

    # Project Agent → telegram (jawaban Q&A project / pengarah detail tiket)
    workflow.add_edge("project_agent", "response_agent")

    # Correlation agent → conditional (CHATFLOW V2.1 Tahap 4): autonomous loop
    # fan-out ke agen kolektor yang terlewat, atau langsung ke response_agent.
    workflow.add_conditional_edges(
        "correlation_agent",
        route_after_correlation,
        {
            "response_agent": "response_agent",
            "metrics_agent": "metrics_agent",
            "mongo_agent": "mongo_agent",
            "trace_agent": "trace_agent",
            "health_agent": "health_agent",
            "span_agent": "span_agent",
        },
    )

    # Jalur khusus independen (langsung ke response_agent)
    # health_agent conditional: fan-out incident → correlation, standalone → telegram (fix duplicate)
    workflow.add_conditional_edges("health_agent", _route_health_agent, {
        "knowledge_agent": "knowledge_agent",
        "response_agent": "response_agent",
    })
    workflow.add_edge("data_agent",        "response_agent")

    # follow_up_agent → routing kondisional (response_agent atau fallback fan-out)
    workflow.add_conditional_edges("follow_up_agent", _route)

    # response_agent → END
    workflow.add_edge("response_agent", END)

    return workflow.compile()


# Singleton graph instance
app = build_graph()

