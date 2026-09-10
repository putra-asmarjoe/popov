"""
STACK2 Fase 2 — K8s Events Agent (Node #16).

Module function graph node (no-LLM) — collects K8s events/status via k8s_client.
Single namespace per target, graceful degrade on all failures.

Flow: supervisor → k8s_agent → response_agent (k8s_standalone mode).
"""

from typing import Any, Dict, Optional
from state.schema import AgentState
import logging

logger = logging.getLogger(__name__)

# STACK2-LANG (Fix #259): bilingual strings for K8s events/status paths.
_K8S_L = {
    "en": {
        "no_stack": "K8s API stack not configured for this project. Add it in Workspace Settings → Stacks (kind: k8s).",
        "unreachable": "K8s API unreachable. Check `kubectl port-forward` is active or token & URL are correct in Workspace Settings → Stacks.",
        "failed": "Failed to fetch K8s data: {err}",
        "header": "**K8s Events** \u2014 `{svc}` (ns: {ns})",
        "warn_events": "Warning Events ({n})",
        "no_events": "No Warning events found.",
        "non_running": "Non-Running Pods ({n})",
        "all_running": "All {n} pods Running \u2705",
        "terminated": "    terminated: {reason}",
        "restarts": "    restarts: {n}",
        "node_pressure": "Node Pressure ({name})",
        # Fix #268: inventory list (pod / deployment)
        "pods_header": "**K8s Pods** \u2014 ns `{ns}` ({n} pods)",
        "pods_line": "\u2022 {name} \u00b7 {phase} \u00b7 restarts: {restarts}{node}",
        "pods_line_no_node": "\u2022 {name} \u00b7 {phase} \u00b7 restarts: {restarts}",
        "deployments_header": "**K8s Deployments** \u2014 ns `{ns}` ({n} deployments)",
        "deployments_line": "\u2022 {name} \u00b7 ready: {ready}/{desired} \u00b7 available: {available}",
        "no_data": "(no data)",
        "nodes_collapsed": "nodes: {nodes}",
        # Fix (deployment ranking/overview): replica overview — deterministic, no LLM
        "rank_header": "**Deployments by replica count** — top {n}:",
        "rank_line": "• `{name}` ({ns}) — desired {desired} / available {available}",
        "rank_line_same_ns": "• `{name}` — desired {desired} / available {available}",
        "overview_header": "**Deployment health overview** ({n} deployments):",
        "overview_ok": "✅ desired == available (healthy)",
        "overview_warn": "⚠️ desired {desired} / available {available} — replicas not ready",
        "overview_all_ok": "All {n} deployments healthy ✅ (desired == available)",
        "rank_unavailable": "Deployment data unavailable (Prometheus/KSM unreachable).",
        "rank_no_data": "No deployment replica data found in the cluster.",
    },
    "id": {
        "no_stack": "Stack K8s API belum dikonfigurasi untuk project ini. Tambahkan di Workspace Settings → Stacks (kind: k8s).",
        "unreachable": "K8s API tidak terjangkau. Cek `kubectl port-forward` aktif atau token & URL benar di Workspace Settings → Stacks.",
        "failed": "Gagal mengambil data K8s: {err}",
        "header": "**Event K8s** \u2014 `{svc}` (ns: {ns})",
        "warn_events": "Event Peringatan ({n})",
        "no_events": "Tidak ada event peringatan.",
        "non_running": "Pod Tidak Berjalan ({n})",
        "all_running": "Semua {n} pod berjalan \u2705",
        "terminated": "    dihentikan: {reason}",
        "restarts": "    restart: {n}",
        "node_pressure": "Tekanan Node ({name})",
        # Fix #268: inventory list (pod / deployment)
        "pods_header": "**Pod K8s** \u2014 ns `{ns}` ({n} pod)",
        "pods_line": "\u2022 {name} \u00b7 {phase} \u00b7 restart: {restarts}{node}",
        "pods_line_no_node": "\u2022 {name} \u00b7 {phase} \u00b7 restart: {restarts}",
        "deployments_header": "**Deployment K8s** \u2014 ns `{ns}` ({n} deployment)",
        "deployments_line": "\u2022 {name} \u00b7 ready: {ready}/{desired} \u00b7 available: {available}",
        "no_data": "(tanpa data)",
        "nodes_collapsed": "nodes: {nodes}",
        # Fix (deployment ranking/overview): overview replica — deterministik, tanpa LLM
        "rank_header": "**Deployment berdasarkan jumlah replica** — top {n}:",
        "rank_line": "• `{name}` ({ns}) — desired {desired} / available {available}",
        "rank_line_same_ns": "• `{name}` — desired {desired} / available {available}",
        "overview_header": "**Kondisi deployment** ({n} deployment):",
        "overview_ok": "✅ desired == available (sehat)",
        "overview_warn": "⚠️ desired {desired} / available {available} — replica belum siap",
        "overview_all_ok": "Semua {n} deployment sehat ✅ (desired == available)",
        "rank_unavailable": "Data deployment tidak tersedia (Prometheus/KSM tidak terjangkau).",
        "rank_no_data": "Tidak ada data replica deployment di cluster.",
    },
}


async def k8s_agent(state: AgentState) -> dict:
    """
    K8s events collector — no LLM, pure data collection.
    Reads k8s intent from state, calls k8s_client functions, formats summary.
    Fix #259: Bilingual messages via _K8S_L map.
    """
    from services.observability_store import get_observ_config_for_state, resolve_k8s_targets_for_state
    from services.k8s_client import (
        get_pod_events, get_pod_status, get_node_pressure, health_probe,
        list_pods, list_deployments,
    )
    from services.conversation import resolve_state_locale

    agents_visited = (state.get("agents_visited") or []) + ["k8s_agent"]
    obs = await get_observ_config_for_state(state)
    locale = await resolve_state_locale(state)
    t = _K8S_L.get(locale, _K8S_L["en"])
    intent = state.get("k8s_intent") or "events"

    # Fix (deployment ranking/overview): replica overview lane — KSM/Prometheus
    # dulu, fallback k8s_client list_deployments + sort eksplisit -desired.
    # Jalankan SEBELUM cek obs: Prom bisa ada walau stack kind=k8s tidak.
    if intent in ("deployment_ranking", "deployment_overview"):
        return await _handle_deployment_lane(
            state, intent, agents_visited, locale, list_deployments,
            health_probe,
        )

    # Fix #268: inventory lane (pods / deployments) — query SEMUA cluster K8s yang
    # ter-resolve utk konteks (project-linked > ws-wide). Project boleh punya >1
    # stack kind=k8s; jawaban per stack + nama stack, tanpa pick diam-diam.
    # Jalankan SEBELUM cek obs (obs merged bisa None walau ada k8s target per-stack).
    if intent in ("pods", "deployments"):
        targets = await resolve_k8s_targets_for_state(state)
        if not targets:
            return {
                "k8s_summary": t["no_stack"],
                "k8s_available": False,
                "agents_visited": agents_visited,
            }
        sections: list = []
        raw_per_stack: list = []
        any_ok = False
        for tgt in targets:
            common = dict(api_url=tgt["api_url"], token=tgt["token"],
                          verify_ssl=tgt["verify_ssl"])
            ns = state.get("k8s_namespace") or tgt["namespace"] or "default"
            if not await health_probe(**common):
                sections.append(f"**{tgt['name']}** ({tgt['api_url']}) — {t['unreachable']}")
                raw_per_stack.append({"stack": tgt["name"], "reachable": False})
                continue
            try:
                if intent == "pods":
                    items = await list_pods(namespace=ns, **common)
                else:
                    items = await list_deployments(namespace=ns, **common)
            except Exception as e:
                logger.warning(f"k8s inventory '{tgt['name']}' failed: {e}")
                items = []
            any_ok = any_ok or bool(items)
            raw_per_stack.append({"stack": tgt["name"], "reachable": True, "items": items})
            sections.append(
                f"**{tgt['name']}** ({tgt['api_url']})\n"
                + _format_inventory_summary(intent, ns, {
                    "pods": items} if intent == "pods" else {"deployments": items}, locale)
            )
        return {
            "k8s_summary": "\n\n".join(sections),
            "k8s_available": any_ok,
            "k8s_raw": {"per_stack": raw_per_stack},
            "agents_visited": agents_visited,
        }

    # Graceful degrade: no K8s stack configured
    if not obs or not obs.get("k8s_api_url"):
        return {
            "k8s_summary": t["no_stack"],
            "k8s_available": False,
            "agents_visited": agents_visited,
        }

    service = state.get("service_name") or state.get("preset_service_name") or ""
    common = dict(
        api_url=obs["k8s_api_url"],
        token=obs.get("k8s_token") or "",
        verify_ssl=bool(obs.get("k8s_verify_ssl", False)),
    )
    namespace = state.get("k8s_namespace") or obs.get("k8s_namespace") or "default"

    # Probe first
    is_healthy = await health_probe(**common)
    if not is_healthy:
        return {
            "k8s_summary": t["unreachable"],
            "k8s_available": False,
            "agents_visited": agents_visited,
        }

    results: Dict[str, Any] = {}
    try:
        if intent in ("events", "all", None):
            results["events"] = await get_pod_events(
                service, namespace=namespace, **common
            )
        if intent in ("pod_status", "all", None):
            results["pod_status"] = await get_pod_status(
                service, namespace=namespace, **common
            )
        if intent == "node_pressure":
            node = state.get("k8s_node") or ""
            if node:
                results["node_pressure"] = await get_node_pressure(node, **common)
    except Exception as e:
        logger.error(f"k8s_agent collection failed: {e}", exc_info=True)
        return {
            "k8s_summary": t["failed"].format(err=str(e)[:200]),
            "k8s_available": False,
            "agents_visited": agents_visited,
        }

    # Fix #268: inventory lane sudah return di atas — sini hanya events/pod_status/all/node_pressure
    summary = _format_k8s_summary(service, namespace, results, locale)
    return {
        "k8s_summary": summary,
        "k8s_available": True,
        "k8s_raw": results,
        "agents_visited": agents_visited,
    }


def _format_inventory_summary(intent: str, namespace: str, results: dict, locale: str = "en") -> str:
    """
    Fix #268: format inventory list (pods / deployments) — compact bullet lines.
    Pods: name · phase · restarts (node collapsed, max 3 distinct). Cap 30 lines.
    Deployments: name · ready x/y · available z.
    """
    t = _K8S_L.get(locale, _K8S_L["en"])
    lines: list = []

    if intent == "pods":
        pods = results.get("pods") or []
        lines.append(t["pods_header"].format(ns=namespace, n=len(pods)))
        if not pods:
            lines.append(t["no_data"])
            return "\n".join(lines)
        # Node names: ≤3 distinct → inline per-pod; >3 → collapsed satu baris
        nodes = sorted({p.get("node", "") for p in pods if p.get("node")})
        if len(nodes) > 3:
            shown = ", ".join(f"`{n}`" for n in nodes[:3])
            more = len(nodes) - 3
            lines.append(t["nodes_collapsed"].format(
                nodes=shown + (f" +{more}" if more > 0 else "")
            ))
        for p in pods[:30]:
            node_part = f" · `{p.get('node', '')}`" if len(nodes) <= 3 else ""
            lines.append(t["pods_line"].format(
                name=p.get("name", "?"),
                phase=p.get("phase", "?"),
                restarts=p.get("restarts", 0),
                node=node_part,
            ))
        if len(pods) > 30:
            lines.append(f"... +{len(pods) - 30}")
        return "\n".join(lines)

    # deployments
    deployments = results.get("deployments") or []
    lines.append(t["deployments_header"].format(ns=namespace, n=len(deployments)))
    if not deployments:
        lines.append(t["no_data"])
        return "\n".join(lines)
    for d in deployments[:30]:
        lines.append(t["deployments_line"].format(
            name=d.get("name", "?"),
            desired=d.get("desired", 0),
            ready=d.get("ready", 0),
            available=d.get("available", 0),
        ))
    if len(deployments) > 30:
        lines.append(f"... +{len(deployments) - 30}")
    return "\n".join(lines)


def _format_k8s_summary(service: str, namespace: str, results: dict, locale: str = "en") -> str:
    """
    Format K8s data into <500 token human-readable summary (bilingual).
    Emphasizes non-Running pods, OOMKilled, BackOff, Evicted, exit codes.
    """
    t = _K8S_L.get(locale, _K8S_L["en"])
    lines = [t["header"].format(svc=service, ns=namespace)]

    # Events
    events = results.get("events", [])
    if events:
        lines.append(f"\n**{t['warn_events'].format(n=len(events))}**:")
        for ev in events[:8]:  # cap at 8
            pod = ev.get("name", "?")
            reason = ev.get("reason", "?")
            msg = ev.get("message", "")[:120]
            count = ev.get("count", 1)
            ts = ev.get("lastTimestamp", "")
            # Highlight critical reasons
            emoji = "⚠️"
            if "OOMKilling" in reason or "OOMKilled" in reason:
                emoji = "🔴"
            elif "BackOff" in reason or "CrashLoopBackOff" in reason:
                emoji = "🟡"
            elif "Evicted" in reason:
                emoji = "🟠"
            lines.append(f"  {emoji} **{reason}** ×{count} — `{pod}`")
            if msg:
                lines.append(f"    {msg}")
    else:
        lines.append(f"\n{t['no_events']}")

    # Pod status
    pods = results.get("pod_status", [])
    if pods:
        non_running = [p for p in pods if p.get("phase") != "Running"]
        if non_running:
            lines.append(f"\n**{t['non_running'].format(n=len(non_running))}**:")
            for pod in non_running[:5]:
                name = pod.get("name", "?")
                phase = pod.get("phase", "?")
                lines.append(f"  ❌ `{name}` — {phase}")
                for cs in pod.get("containerStatuses", []):
                    reason = cs.get("lastTerminatedReason", "")
                    exit_code = cs.get("exitCode", 0)
                    signal = cs.get("signal", 0)
                    restarts = cs.get("restartCount", 0)
                    if reason:
                        detail = f"    {t['terminated'].format(reason=reason)}"
                        if exit_code:
                            detail += f" (exit={exit_code}"
                            if signal:
                                detail += f", signal={signal}"
                            detail += ")"
                        lines.append(detail)
                    if restarts > 0:
                        lines.append(t["restarts"].format(n=restarts))
        else:
            lines.append(f"\n{t['all_running'].format(n=len(pods))}")

    # Node pressure
    np_data = results.get("node_pressure", {})
    if np_data:
        conds = np_data.get("conditions", [])
        pressure = [c for c in conds if c.get("status") == "True"]
        if pressure:
            lines.append(f"\n**{t['node_pressure'].format(name=np_data.get('name', '?'))}**:")
            for c in pressure:
                lines.append(f"  ⚠️ {c['type']}: {c.get('reason', '?')} — {c.get('message', '')[:100]}")

    return "\n".join(lines)


async def _handle_deployment_lane(
    state: AgentState,
    intent: str,
    agents_visited: list,
    locale: str,
    list_deployments_fn,
    health_probe_fn,
) -> dict:
    """
    Fix (deployment ranking/overview): lane replica overview — DETERMINISTIK,
    tanpa LLM. Q2 "deployment paling banyak replicanya" → ranking top-N;
    Q1 "apakah semua deployment aman?" → overview + verdict per deployment.

    Sumber utama: Prometheus KSM (get_deployments_replica_overview) — butuh
    prometheus_url dari observ stack. Fallback: k8s_client list_deployments()
    via resolve_k8s_targets_for_state (stack kind=k8s), sort eksplisit -desired.

    Graceful: kedua sumber gagal → jawaban jujur "data tidak tersedia" — JANGAN
    fallback ke project_agent, JANGAN data kosong tanpa penjelasan.
    """
    from services.observability_store import get_observ_config_for_state, resolve_k8s_targets_for_state
    from services.prometheus_client import get_deployments_replica_overview

    t = _K8S_L.get(locale, _K8S_L["en"])
    top_n = 5

    # 1) Prometheus/KSM — prometheus_url dari observ config (bisa None walau
    #    stack k8s ada; probe KSM di dalam fungsi menangani KSM tak di-scrape)
    try:
        obs_cfg = await get_observ_config_for_state(state)
        prom_override = (obs_cfg or {}).get("prometheus_url")
        if prom_override:
            overview = await get_deployments_replica_overview(
                top_n=top_n, base_url_override=prom_override,
            )
            if overview and overview.get("available"):
                items = overview.get("items") or []
                if items:
                    summary = _format_deployment_ranking(items, intent, locale, top_n=top_n)
                    return {
                        "k8s_summary": summary,
                        "k8s_available": True,
                        "k8s_raw": {"source": "prometheus_ksm", "items": items},
                        "agents_visited": agents_visited,
                    }
                # available + items kosong = KSM hidup, cluster belum punya deployment
                summary = t["rank_no_data"]
                return {
                    "k8s_summary": summary,
                    "k8s_available": False,
                    "k8s_raw": {"source": "prometheus_ksm", "items": []},
                    "agents_visited": agents_visited,
                }
            reason = (overview or {}).get("reason") or ""
            logger.warning(f"Deployment overview via KSM unavailable: {reason}")
    except Exception as e:
        logger.warning(f"Deployment overview via KSM failed: {e}")

    # 2) Fallback: k8s_client list_deployments per stack kind=k8s
    try:
        targets = await resolve_k8s_targets_for_state(state)
        for tgt in targets:
            common = dict(api_url=tgt["api_url"], token=tgt["token"],
                          verify_ssl=tgt["verify_ssl"])
            if not await health_probe_fn(**common):
                continue
            ns = state.get("k8s_namespace") or tgt["namespace"] or "default"
            deps = await list_deployments_fn(namespace=ns, **common)
            if deps:
                deps = sorted(deps, key=lambda d: -int(d.get("desired", 0) or 0))
                items = [{
                    "name": d.get("name", ""),
                    "namespace": ns,
                    "desired": int(d.get("desired", 0) or 0),
                    "available": int(d.get("available", 0) or 0),
                } for d in deps[:top_n]]
                summary = _format_deployment_ranking(items, intent, locale, top_n=top_n)
                return {
                    "k8s_summary": summary,
                    "k8s_available": True,
                    "k8s_raw": {"source": "k8s_api", "items": items},
                    "agents_visited": agents_visited,
                }
    except Exception as e:
        logger.warning(f"Deployment overview via k8s API failed: {e}")

    # 3) Kedua sumber gagal → jujur. JANGAN fallback project_agent (supervisor
    #    sudah route ke sini), JANGAN jawaban kosong tanpa penjelasan.
    return {
        "k8s_summary": t["rank_unavailable"],
        "k8s_available": False,
        "k8s_raw": None,
        "agents_visited": agents_visited,
    }


def _format_deployment_ranking(items: list, intent: str, locale: str = "en", top_n: int = 5) -> str:
    """
    Fix (deployment ranking/overview): formatter deterministic bilingual <500 token.
    - ranking: "• `kuponku-core-api` — desired 4 / available 4" per baris.
    - overview: verdict per deployment (desired==available → ✅, else ⚠️).
    """
    t = _K8S_L.get(locale, _K8S_L["en"])
    # Satu namespace saja → label namespace bisa dilepas (kompak)
    namespaces = {it.get("namespace", "") for it in items}
    show_ns = len(namespaces) > 1 or any(not ns for ns in namespaces)
    lines: list = [t["overview_header"].format(n=len(items)) if intent == "deployment_overview"
                   else t["rank_header"].format(n=len(items) or top_n)]
    for it in items[:top_n]:
        name = it.get("name", "?")
        ns = it.get("namespace", "")
        desired = it.get("desired", 0)
        available = it.get("available", 0)
        if intent == "deployment_overview":
            if desired == available:
                verdict = t["overview_ok"]
            else:
                verdict = t["overview_warn"].format(desired=desired, available=available)
            base = (t["rank_line"] if show_ns else t["rank_line_same_ns"]).format(
                name=name, ns=ns, desired=desired, available=available)
            lines.append(f"{base} · {verdict}")
        else:
            lines.append((t["rank_line"] if show_ns else t["rank_line_same_ns"]).format(
                name=name, ns=ns, desired=desired, available=available))
    # Overview: bila semua sehat → satu baris ringkas di atas list
    if intent == "deployment_overview" and items and all(
        it.get("desired", 0) == it.get("available", 0) for it in items
    ):
        lines.insert(1, t["overview_all_ok"].format(n=len(items)))
    return "\n".join(lines)
