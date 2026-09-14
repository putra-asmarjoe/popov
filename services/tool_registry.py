"""CHAT3 Phase 4 — Tool registry (agentic lane).

Single source of truth for LLM-invokable tools. Each entry declares:
  - name: canonical lowercase identifier (lookup is case-insensitive)
  - description: one line for the LLM tools block
  - params: LLM-suppliable param names (credentials are NEVER LLM params —
    adapters inject workspace_id / observ creds / ticket actor server-side)
  - read_only: False → requires confirmation, never auto-executed (M2)
  - needs_namespace: True only for tools whose real signature takes a
    namespace (parser never injects namespace otherwise — C5)

Budget (C2/C3): MAX_TOOLS_PER_TURN hard slice per turn; per-tool timeout
TOOL_TIMEOUT_S; session_tool_count persisted in conversation_state.
"""
from __future__ import annotations

from typing import Any, Dict, List

MAX_TOOLS_PER_TURN = 5
TOOL_TIMEOUT_S = 8.0

# ── Tool definitions ─────────────────────────────────────────────────────────
# 16 read-only (auto-execute) + 3 write (confirmation-gated, M2) = 19 tools.

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    # — Mongo / app logs —
    {"name": "mongo_logs", "description": "Recent error logs for a service from its log database",
     "params": ["service", "limit"], "read_only": True, "needs_namespace": False},
    # — Prometheus —
    {"name": "prom_instant", "description": "Run a PromQL instant query (commas/quotes preserved)",
     "params": ["promql"], "read_only": True, "needs_namespace": False},
    {"name": "prom_range", "description": "Run a PromQL range query over a window (e.g. 1h, 24h)",
     "params": ["promql", "window"], "read_only": True, "needs_namespace": False},
    {"name": "pod_health", "description": "Pod health (restarts, OOMKills, ready) via kube-state-metrics",
     "params": ["service", "window"], "read_only": True, "needs_namespace": False},
    {"name": "active_alerts", "description": "Active alerts for a service (Alertmanager, fallback Prometheus)",
     "params": ["service"], "read_only": True, "needs_namespace": False},
    {"name": "deploy_replicas", "description": "Top-N deployments by replica count (desired vs available)",
     "params": ["top_n"], "read_only": True, "needs_namespace": False},
    # — Kubernetes API (namespace applies ONLY here) —
    {"name": "k8s_events", "description": "Warning events for pods of a service",
     "params": ["service", "namespace"], "read_only": True, "needs_namespace": True},
    {"name": "k8s_pods", "description": "Pod status + container details for a service",
     "params": ["service", "namespace"], "read_only": True, "needs_namespace": True},
    {"name": "k8s_pods_list", "description": "List all pods in the namespace (inventory)",
     "params": ["namespace"], "read_only": True, "needs_namespace": True},
    {"name": "k8s_deployments", "description": "List all deployments in the namespace (inventory)",
     "params": ["namespace"], "read_only": True, "needs_namespace": True},
    {"name": "k8s_node", "description": "Node pressure conditions (Memory/Disk/PID) for a node",
     "params": ["node"], "read_only": True, "needs_namespace": False},
    # — Tempo traces —
    {"name": "trace_detail", "description": "Full trace detail for a trace_id",
     "params": ["trace_id"], "read_only": True, "needs_namespace": False},
    {"name": "trace_search", "description": "Search recent traces for a service",
     "params": ["service", "limit"], "read_only": True, "needs_namespace": False},
    # — Central log spans (OTel) —
    {"name": "span_by_trace", "description": "Spans + HTTP logs for a trace_id from central log",
     "params": ["trace_id", "limit"], "read_only": True, "needs_namespace": False},
    {"name": "span_errors", "description": "Recent error spans, optionally filtered by service",
     "params": ["service", "limit"], "read_only": True, "needs_namespace": False},
    # — Knowledge —
    {"name": "knowledge_search", "description": "Search workspace knowledge relevant to a query",
     "params": ["query", "service", "top_k"], "read_only": True, "needs_namespace": False},
    # — Ticket writes (confirmation-gated, NEVER auto-executed) —
    {"name": "ticket_note", "description": "Add a progress note to the current ticket (needs confirmation)",
     "params": ["note"], "read_only": False, "needs_namespace": False},
    {"name": "ticket_status", "description": "Change the current ticket status (needs confirmation)",
     "params": ["status"], "read_only": False, "needs_namespace": False},
    {"name": "ticket_severity", "description": "Change the current ticket severity (needs confirmation)",
     "params": ["severity"], "read_only": False, "needs_namespace": False},
]

_BY_NAME = {t["name"]: t for t in TOOL_DEFINITIONS}


def get_tool(name: str) -> Dict[str, Any] | None:
    """Case-insensitive lookup (C5: parse/lookup case parity)."""
    if not name:
        return None
    return _BY_NAME.get(name.strip().lower())


def read_only_tools() -> List[Dict[str, Any]]:
    return [t for t in TOOL_DEFINITIONS if t.get("read_only")]


def format_tools_for_llm(include_write: bool = False) -> str:
    """Render the tool catalogue for the LLM (C4).

    Default exposes READ-ONLY tools only (M2: write tools removed from the
    LLM-visible registry — they remain defined for gating, never auto-run).
    One line per tool: `- name(param1, param2): description`.
    """
    lines = []
    for t in TOOL_DEFINITIONS:
        if not t.get("read_only") and not include_write:
            continue
        params = ", ".join(t.get("params") or [])
        lines.append(f"- {t['name']}({params}): {t['description']}")
    return "\n".join(lines)
