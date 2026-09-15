"""CHAT3 Phase 4 — Tool adapters (C1/M3).

Thin layer mapping LLM params → REAL function signatures. Credentials are
injected server-side from state/DB — NEVER from the LLM:

  - workspace_id  → from AgentState (mongo logs, knowledge search)
  - observ creds  → resolved via observability_store per observ_id
                    (k8s api_url+token, prometheus/tempo URLs)
  - ticket dict + actor → from ticket_context / sender state (ticket writes)

Each adapter returns (ok: bool, text: str) — text is the compact
LLM-facing result (< ~1200 chars). Adapters never raise: failure is
(ok=False, reason) so execution degrades gracefully (non-fatal contract).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Tuple

logger = logging.getLogger(__name__)

AdapterCtx = Dict[str, Any]  # {state, observ_cfg, k8s_targets, log_cfg}


def _svc(state: dict, params: dict) -> str:
    raw = (params.get("service") or "").strip()
    if raw:
        return raw
    tc = state.get("topic_service") or ""
    if tc:
        return tc
    svc = state.get("service_name") or ""
    return (svc or "").strip()


def _int(params: dict, key: str, default: int) -> int:
    try:
        v = int(str(params.get(key, default)).strip())
        return v if v > 0 else default
    except (TypeError, ValueError, AttributeError):
        return default


async def _mongo_logs(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.db_loader import fetch_logs_for_service

    state = ctx["state"]
    service = _svc(state, params)
    if not service:
        return False, "mongo_logs: no service known (specify a service)"
    limit = _int(params, "limit", 5)
    try:
        docs = await fetch_logs_for_service(
            service_name=service, limit=min(limit, 20),
            workspace_id=state.get("workspace_id"),
        )
    except ValueError as e:
        return False, f"mongo_logs unavailable: {e}"
    except Exception as e:
        return False, f"mongo_logs query failed: {e}"
    if not docs:
        return True, f"mongo_logs({service}): no error logs found"
    lines = [f"mongo_logs({service}): {len(docs)} docs"]
    for d in docs[:limit]:
        if not isinstance(d, dict):
            continue
        msg = (d.get("message") or d.get("error") or d.get("msg") or "")[:160]
        ts = d.get("timestamp") or d.get("createdAt") or ""
        lines.append(f"- [{ts}] {msg}".strip())
    return True, "\n".join(lines)[:1200]


async def _prom_instant(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.prometheus_client import query_prometheus

    promql = (params.get("promql") or "").strip()
    if not promql:
        return False, "prom_instant: missing promql"
    url = (ctx.get("observ_cfg") or {}).get("prometheus_url")
    if not url:
        return False, "prom_instant: no Prometheus stack configured"
    try:
        res = await query_prometheus(promql, base_url_override=url)
    except Exception as e:
        return False, f"prom_instant failed: {e}"
    if not res or not res.get("result"):
        return True, f"prom_instant: no data for `{promql[:120]}`"
    out = []
    for series in (res.get("result") or [])[:5]:
        metric = series.get("metric", {}) or {}
        val = (series.get("value") or [None, "?"])[1]
        out.append(f"- {metric} = {val}")
    return True, f"prom_instant `{promql[:120]}`:\n" + "\n".join(out)[:1200]


async def _prom_range(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.prometheus_client import query_range

    promql = (params.get("promql") or "").strip()
    if not promql:
        return False, "prom_range: missing promql"
    url = (ctx.get("observ_cfg") or {}).get("prometheus_url")
    if not url:
        return False, "prom_range: no Prometheus stack configured"
    window = (params.get("window") or "1h").strip() or "1h"
    try:
        res = await query_range(promql, window=window, base_url_override=url)
    except Exception as e:
        return False, f"prom_range failed: {e}"
    if not res or not res.get("result"):
        return True, f"prom_range: no data for `{promql[:120]}` [{window}]"
    n = len(res.get("result") or [])
    return True, (f"prom_range `{promql[:120]}` [{window}]: "
                  f"{res.get('resultType', '?')} with {n} series, "
                  f"step={res.get('step', '?')}")


async def _pod_health(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.prometheus_client import get_pod_health

    state = ctx["state"]
    service = _svc(state, params)
    if not service:
        return False, "pod_health: no service known"
    url = (ctx.get("observ_cfg") or {}).get("prometheus_url")
    if not url:
        return False, "pod_health: no Prometheus stack configured"
    window = (params.get("window") or "24h").strip() or "24h"
    try:
        res = await get_pod_health(service, base_url_override=url, window=window)
    except Exception as e:
        return False, f"pod_health failed: {e}"
    if not res:
        return True, f"pod_health({service}): unavailable"
    if not res.get("available"):
        return True, (f"pod_health({service}): unavailable — "
                      f"{res.get('reason', 'unknown')}")
    return True, (f"pod_health({service}) [{res.get('window', window)}]: "
                  f"running={res.get('running', '?')}, "
                  f"restarts={res.get('restarts', '?')}, "
                  f"oom={res.get('oom_kills', '?')}, "
                  f"ready={res.get('ready', '?')}/{res.get('ready', 0) + res.get('not_ready', 0)}")


async def _active_alerts(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.prometheus_client import get_active_alerts

    state = ctx["state"]
    service = _svc(state, params)
    if not service:
        return False, "active_alerts: no service known"
    cfg = ctx.get("observ_cfg") or {}
    try:
        alerts = await get_active_alerts(
            service,
            alertmanager_url_override=cfg.get("alertmanager_url"),
            prometheus_url_override=cfg.get("prometheus_url"),
        )
    except Exception as e:
        return False, f"active_alerts failed: {e}"
    if not alerts:
        return True, f"active_alerts({service}): none firing"
    lines = [f"active_alerts({service}): {len(alerts)} firing"]
    for a in alerts[:5]:
        lines.append(f"- {a.get('name', '?')} [{a.get('severity', '?')}] {a.get('state', '')}")
    return True, "\n".join(lines)[:1200]


async def _deploy_replicas(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.prometheus_client import get_deployments_replica_overview

    url = (ctx.get("observ_cfg") or {}).get("prometheus_url")
    if not url:
        return False, "deploy_replicas: no Prometheus stack configured"
    top_n = _int(params, "top_n", 5)
    try:
        res = await get_deployments_replica_overview(
            top_n=min(top_n, 20), base_url_override=url)
    except Exception as e:
        return False, f"deploy_replicas failed: {e}"
    if not res or not res.get("available"):
        return True, f"deploy_replicas: unavailable — {(res or {}).get('reason', 'unknown')}"
    items = res.get("items") or []
    if not items:
        return True, "deploy_replicas: no deployments found"
    lines = [f"deploy_replicas top-{len(items)}:"]
    for it in items[:top_n]:
        lines.append(f"- {it.get('name', '?')}: desired {it.get('desired', '?')} / available {it.get('available', '?')}")
    return True, "\n".join(lines)[:1200]


def _k8s_common(ctx: AdapterCtx, params: dict | None = None) -> Dict[str, Any] | None:
    targets = ctx.get("k8s_targets") or []
    if not targets:
        return None
    t = targets[0]
    state = ctx.get("state") or {}
    ns = ((params or {}).get("namespace") or "").strip() or None
    if not ns:
        ns = (state.get("k8s_namespace") or "").strip() or None
    return dict(api_url=t["api_url"], token=t.get("token") or "",
                verify_ssl=bool(t.get("verify_ssl", False)),
                namespace=ns or t.get("namespace") or "default")


async def _k8s_events(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.k8s_client import get_pod_events

    common = _k8s_common(ctx, params)
    if not common:
        return False, "k8s_events: no K8s stack configured"
    service = _svc(ctx["state"], params)
    if not service:
        return False, "k8s_events: no service known"
    ns = common.pop("namespace")
    try:
        events = await get_pod_events(service, namespace=ns, **common)
    except Exception as e:
        return False, f"k8s_events failed: {e}"
    if not events:
        return True, f"k8s_events({service}, ns={ns}): no Warning events"
    lines = [f"k8s_events({service}, ns={ns}): {len(events)}"]
    for ev in events[:5]:
        lines.append(f"- {ev.get('reason', '?')} x{ev.get('count', 1)}: {(ev.get('message') or '')[:140]}")
    return True, "\n".join(lines)[:1200]


async def _k8s_pods(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.k8s_client import get_pod_status

    common = _k8s_common(ctx, params)
    if not common:
        return False, "k8s_pods: no K8s stack configured"
    service = _svc(ctx["state"], params)
    if not service:
        return False, "k8s_pods: no service known"
    ns = common.pop("namespace")
    try:
        pods = await get_pod_status(service, namespace=ns, **common)
    except Exception as e:
        return False, f"k8s_pods failed: {e}"
    if not pods:
        return True, f"k8s_pods({service}, ns={ns}): none found"
    non_running = [p for p in pods if p.get("phase") != "Running"]
    lines = [f"k8s_pods({service}, ns={ns}): {len(pods)} pods, {len(non_running)} non-running"]
    for p in (non_running or pods)[:5]:
        lines.append(f"- {p.get('name', '?')}: {p.get('phase', '?')}")
    return True, "\n".join(lines)[:1200]


async def _k8s_pods_list(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.k8s_client import list_pods

    common = _k8s_common(ctx, params)
    if not common:
        return False, "k8s_pods_list: no K8s stack configured"
    ns = common.pop("namespace")
    try:
        pods = await list_pods(namespace=ns, **common)
    except Exception as e:
        return False, f"k8s_pods_list failed: {e}"
    lines = [f"k8s_pods_list(ns={ns}): {len(pods)} pods"]
    for p in pods[:10]:
        lines.append(f"- {p.get('name', '?')}: {p.get('phase', '?')} restarts={p.get('restarts', 0)}")
    return True, "\n".join(lines)[:1200]


async def _k8s_deployments(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.k8s_client import list_deployments

    common = _k8s_common(ctx, params)
    if not common:
        return False, "k8s_deployments: no K8s stack configured"
    ns = common.pop("namespace")
    try:
        deps = await list_deployments(namespace=ns, **common)
    except Exception as e:
        return False, f"k8s_deployments failed: {e}"
    lines = [f"k8s_deployments(ns={ns}): {len(deps)}"]
    for d in deps[:10]:
        lines.append(f"- {d.get('name', '?')}: ready {d.get('ready', '?')}/{d.get('desired', '?')}")
    return True, "\n".join(lines)[:1200]


async def _k8s_node(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.k8s_client import get_node_pressure

    common = _k8s_common(ctx)
    if not common:
        return False, "k8s_node: no K8s stack configured"
    common.pop("namespace", None)
    node = (params.get("node") or ctx["state"].get("k8s_node") or "").strip()
    if not node:
        return False, "k8s_node: missing node"
    try:
        res = await get_node_pressure(node, **common)
    except Exception as e:
        return False, f"k8s_node failed: {e}"
    if not res:
        return True, f"k8s_node({node}): no data"
    pressure = [c for c in (res.get("conditions") or []) if c.get("status") == "True"]
    if not pressure:
        return True, f"k8s_node({node}): no pressure conditions"
    lines = [f"k8s_node({node}): pressure:"]
    for c in pressure:
        lines.append(f"- {c.get('type', '?')}: {c.get('reason', '?')}")
    return True, "\n".join(lines)[:1200]


async def _trace_detail(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.tempo_client import get_trace

    tid = (params.get("trace_id") or "").strip()
    if not tid:
        return False, "trace_detail: missing trace_id"
    url = (ctx.get("observ_cfg") or {}).get("tempo_url")
    if not url:
        return False, "trace_detail: no Tempo stack configured"
    try:
        data = await get_trace(tid, tempo_url_override=url)
    except Exception as e:
        return False, f"trace_detail failed: {e}"
    if not data:
        return True, f"trace_detail({tid}): not found"
    n_batches = len(data.get("batches", []) or [])
    return True, f"trace_detail({tid}): found, {n_batches} batches"


async def _trace_search(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.tempo_client import search_traces

    state = ctx["state"]
    service = _svc(state, params)
    if not service:
        return False, "trace_search: no service known"
    url = (ctx.get("observ_cfg") or {}).get("tempo_url")
    if not url:
        return False, "trace_search: no Tempo stack configured"
    limit = _int(params, "limit", 3)
    try:
        traces = await search_traces(service, limit=min(limit, 10), tempo_url_override=url)
    except Exception as e:
        return False, f"trace_search failed: {e}"
    if not traces:
        return True, f"trace_search({service}): none found"
    lines = [f"trace_search({service}): {len(traces)}"]
    for t in traces[:limit]:
        lines.append(f"- {t.get('traceID', '?')} ({t.get('durationMs', '?')}ms)")
    return True, "\n".join(lines)[:1200]


async def _span_by_trace(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.span_log_loader import (
        fetch_http_logs_by_trace_id, fetch_spans_by_trace_id)

    log_cfg = ctx.get("log_cfg")
    if not log_cfg:
        return False, "span_by_trace: central log not configured"
    tid = (params.get("trace_id") or "").strip()
    if not tid:
        return False, "span_by_trace: missing trace_id"
    limit = _int(params, "limit", 50)
    try:
        spans = await fetch_spans_by_trace_id(tid, limit=min(limit, 50), log_cfg=log_cfg)
        http_logs = await fetch_http_logs_by_trace_id(tid, limit=10, log_cfg=log_cfg)
    except Exception as e:
        return False, f"span_by_trace failed: {e}"
    if not spans:
        return True, f"span_by_trace({tid}): no spans"
    errs = [s for s in spans if isinstance(s, dict) and s.get("isError")]
    return True, (f"span_by_trace({tid}): {len(spans)} spans, "
                  f"{len(errs)} errors, {len(http_logs)} http logs")


async def _span_errors(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.span_log_loader import fetch_recent_error_spans

    log_cfg = ctx.get("log_cfg")
    if not log_cfg:
        return False, "span_errors: central log not configured"
    service = _svc(ctx["state"], params) or None
    limit = _int(params, "limit", 20)
    try:
        spans = await fetch_recent_error_spans(
            limit=min(limit, 20), service=service, log_cfg=log_cfg)
    except Exception as e:
        return False, f"span_errors failed: {e}"
    if not spans:
        return True, f"span_errors({service or 'all'}): none found"
    lines = [f"span_errors({service or 'all'}): {len(spans)}"]
    for s in spans[:5]:
        if not isinstance(s, dict):
            continue
        lines.append(f"- {s.get('traceId', '?')} {s.get('service', '?')} {(s.get('errorMessage') or '')[:120]}")
    return True, "\n".join(lines)[:1200]


async def _knowledge_search(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.knowledge_retrieval import (
        format_knowledge_context, search_relevant_knowledge)

    state = ctx["state"]
    ws_id = state.get("workspace_id")
    if not ws_id:
        return False, "knowledge_search: no workspace context"
    query = (params.get("query") or "").strip()
    if not query:
        return False, "knowledge_search: missing query"
    service = _svc(state, params)
    top_k = _int(params, "top_k", 5)
    try:
        results, method = await search_relevant_knowledge(
            query, str(ws_id), service_name=service, top_k=min(top_k, 10))
    except Exception as e:
        return False, f"knowledge_search failed: {e}"
    if not results:
        return True, f"knowledge_search: no relevant docs ({method})"
    text = format_knowledge_context(results, method)[:1200]
    return True, f"knowledge_search ({method}):\n{text}"


async def _ticket_note(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    """Write tool — adapter layer validates, execution via ticket_agent path."""
    from services.ticket_store import add_progress_note, get_ticket

    state = ctx["state"]
    tc = state.get("ticket_context") or {}
    tid = tc.get("ticketId") or tc.get("ticket_id") or state.get("ticket_id")
    if not tid:
        return False, "ticket_note: no ticket in context"
    note = (params.get("note") or "").strip()
    if not note:
        return False, "ticket_note: missing note"
    actor = state.get("user") or state.get("sender") or {}
    try:
        ticket = await get_ticket(str(tid))
        if ticket is None:
            return False, "ticket_note: ticket not found"
        user = {"_id": str(actor.get("id") or actor.get("userId") or "chat"),
                "name": str(actor.get("name") or actor.get("username") or "chat")}
        doc = await add_progress_note(ticket, note, user)
    except Exception as e:
        return False, f"ticket_note failed: {e}"
    return True, f"ticket_note: added to #{(doc or {}).get('ticketNumber', '?')}"


async def _ticket_status(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.ticket_store import change_status, get_ticket

    state = ctx["state"]
    tc = state.get("ticket_context") or {}
    tid = tc.get("ticketId") or tc.get("ticket_id") or state.get("ticket_id")
    if not tid:
        return False, "ticket_status: no ticket in context"
    target = (params.get("status") or "").strip()
    if not target:
        return False, "ticket_status: missing status"
    actor = state.get("user") or state.get("sender") or {}
    try:
        ticket = await get_ticket(str(tid))
        if ticket is None:
            return False, "ticket_status: ticket not found"
        user = {"_id": str(actor.get("id") or actor.get("userId") or "chat"),
                "name": str(actor.get("name") or actor.get("username") or "chat")}
        doc, err = await change_status(ticket, target, user, via="agent")
    except Exception as e:
        return False, f"ticket_status failed: {e}"
    if err:
        return False, f"ticket_status rejected: {err}"
    return True, f"ticket_status: now {(doc or {}).get('status', '?')}"


async def _ticket_severity(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.ticket_store import get_ticket, update_ticket

    state = ctx["state"]
    tc = state.get("ticket_context") or {}
    tid = tc.get("ticketId") or tc.get("ticket_id") or state.get("ticket_id")
    if not tid:
        return False, "ticket_severity: no ticket in context"
    sev = (params.get("severity") or "").strip().lower()
    if sev not in ("critical", "high", "medium", "low"):
        return False, f"ticket_severity: invalid severity '{sev}'"
    actor = state.get("user") or state.get("sender") or {}
    try:
        user = {"_id": str(actor.get("id") or actor.get("userId") or "chat"),
                "name": str(actor.get("name") or actor.get("username") or "chat")}
        doc = await update_ticket(str(tid), severity=sev, actor=user, via="agent")
    except Exception as e:
        return False, f"ticket_severity failed: {e}"
    if doc is None:
        return False, "ticket_severity: ticket not found"
    return True, f"ticket_severity: now {doc.get('severity', '?')}"


ADAPTERS: Dict[str, Callable[[dict, AdapterCtx], Any]] = {
    "mongo_logs": _mongo_logs,
    "prom_instant": _prom_instant,
    "prom_range": _prom_range,
    "pod_health": _pod_health,
    "active_alerts": _active_alerts,
    "deploy_replicas": _deploy_replicas,
    "k8s_events": _k8s_events,
    "k8s_pods": _k8s_pods,
    "k8s_pods_list": _k8s_pods_list,
    "k8s_deployments": _k8s_deployments,
    "k8s_node": _k8s_node,
    "trace_detail": _trace_detail,
    "trace_search": _trace_search,
    "span_by_trace": _span_by_trace,
    "span_errors": _span_errors,
    "knowledge_search": _knowledge_search,
    "ticket_note": _ticket_note,
    "ticket_status": _ticket_status,
    "ticket_severity": _ticket_severity,
}


async def _ticket_alert_counts(params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    from services.ticket_alert_store import count_alerts_by_name_for_project

    # Tenant-bleed guard (CTO decision): project_id is derived from ctx["state"]
    # ONLY — the LLM must not pass an arbitrary tenant id via params, like every
    # other project-scoped adapter. params["project_id"] is intentionally ignored.
    state = ctx["state"]
    pid = (state.get("project_id") or "").strip()
    if not pid:
        return False, "ticket_alert_counts: no project_id (use in a project session)"
    days = _int(params, "days", 1)
    try:
        counts = await count_alerts_by_name_for_project(pid, days=days)
    except Exception as e:
        return False, f"ticket_alert_counts failed: {e}"
    if not counts:
        return True, f"ticket_alert_counts({pid}): no alerts in last {days} day(s)"
    lines = [f"ticket_alert_counts({pid}, {days}d): {len(counts)} alert types"]
    for c in counts[:15]:
        lines.append(
            f"- {(c.get('alert_name') or '?')}: {c.get('ticket_count', 0)} ticket(s), "
            f"{c.get('alert_count', 0)} alert(s)"
        )
    return True, "\n".join(lines)[:1200]

ADAPTERS["ticket_alert_counts"] = _ticket_alert_counts

async def run_adapter(name: str, params: dict, ctx: AdapterCtx) -> Tuple[bool, str]:
    """Dispatch to the named adapter. Never raises — unknown name or
    adapter exception becomes (False, reason). Sync adapters tolerated."""
    fn = ADAPTERS.get((name or "").strip().lower())
    if fn is None:
        return False, f"unknown tool '{name}'"
    try:
        res = fn(params or {}, ctx)
        if asyncio.iscoroutine(res):
            res = await res
        ok, text = res
        return bool(ok), str(text or "")
    except Exception as e:
        logger.warning(f"[ToolAdapter] {name} raised: {e}")
        return False, f"{name} failed: {e}"
