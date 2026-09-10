"""
STACK2 Fase 2 — K8s API Client.

Module functions (no class) using httpx — consistent with observability_store pattern.
All functions swallow exceptions → return empty data / False (caller formats degrade message).

Spec: single namespace per target, no multi-cluster.
"""

from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


async def _k8s_get(
    path: str,
    *,
    api_url: str,
    token: str,
    verify_ssl: bool,
    timeout_s: float = 4.0,
) -> dict:
    """
    Generic K8s API GET request.
    Returns parsed JSON or raises on error.
    """
    import httpx

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(verify=verify_ssl, timeout=timeout_s) as client:
        r = await client.get(f"{api_url}{path}", headers=headers)
        r.raise_for_status()
        return r.json()


async def health_probe(
    *,
    api_url: str,
    token: str = "",
    verify_ssl: bool = False,
) -> bool:
    """
    Probe K8s API health: GET /api/v1/namespaces → 200 = ok.
    Returns True/False, never raises.
    """
    try:
        await _k8s_get("/api/v1/namespaces", api_url=api_url, token=token, verify_ssl=verify_ssl)
        return True
    except Exception as e:
        logger.debug(f"K8s health probe failed: {e}")
        return False


async def get_pod_events(
    service: str,
    *,
    api_url: str,
    token: str,
    namespace: str = "default",
    verify_ssl: bool = False,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    GET /api/v1/namespaces/{ns}/events — Warning events for pods matching service prefix.
    Returns [{name, reason, message, count, lastTimestamp, type}].
    Swallow exceptions → empty list.
    """
    try:
        # fieldSelector for Warning events involving Pods
        selector = "involvedObject.kind=Pod,type=Warning"
        path = f"/api/v1/namespaces/{namespace}/events?fieldSelector={selector}&limit={limit}"
        data = await _k8s_get(path, api_url=api_url, token=token, verify_ssl=verify_ssl)

        events = []
        for item in (data.get("items") or []):
            involved = item.get("involvedObject", {})
            pod_name = involved.get("name", "")
            # Filter by pod name prefix matching service
            # Build regex: match service name with [-_] separator, then pod suffix
            import re
            svc_parts = re.split(r'[-_]+', service)
            svc_pattern = '[-_]+'.join(re.escape(p) for p in svc_parts if p)
            if not re.match(rf"^{svc_pattern}[-_]", pod_name):
                continue
            events.append({
                "name": pod_name,
                "reason": item.get("reason", ""),
                "message": item.get("message", ""),
                "count": item.get("count", 1),
                "lastTimestamp": item.get("lastTimestamp", ""),
                "type": item.get("type", ""),
            })
        return events
    except Exception as e:
        logger.warning(f"get_pod_events failed: {e}")
        return []


async def get_pod_status(
    service: str,
    *,
    api_url: str,
    token: str,
    namespace: str = "default",
    verify_ssl: bool = False,
) -> List[Dict[str, Any]]:
    """
    GET /api/v1/namespaces/{ns}/pods — pod status with container details.
    Returns [{name, phase, containerStatuses: [{name, ready, restartCount, lastState}]}].
    Swallow exceptions → empty list.
    """
    try:
        path = f"/api/v1/namespaces/{namespace}/pods?labelSelector=app={service}"
        data = await _k8s_get(path, api_url=api_url, token=token, verify_ssl=verify_ssl)

        pods = []
        for item in (data.get("items") or []):
            pod_name = item.get("metadata", {}).get("name", "")
            phase = item.get("status", {}).get("phase", "Unknown")
            container_statuses = []
            for cs in (item.get("status", {}).get("containerStatuses") or []):
                last_state = cs.get("lastState", {})
                terminated = last_state.get("terminated", {}) if last_state else {}
                container_statuses.append({
                    "name": cs.get("name", ""),
                    "ready": cs.get("ready", False),
                    "restartCount": cs.get("restartCount", 0),
                    "lastTerminatedReason": terminated.get("reason", ""),
                    "exitCode": terminated.get("exitCode", 0),
                    "signal": terminated.get("signal", 0),
                })
            pods.append({
                "name": pod_name,
                "phase": phase,
                "containerStatuses": container_statuses,
            })
        return pods
    except Exception as e:
        logger.warning(f"get_pod_status failed: {e}")
        return []


async def list_pods(
    *,
    api_url: str,
    token: str,
    namespace: str = "default",
    verify_ssl: bool = False,
) -> List[Dict[str, Any]]:
    """
    Fix #268: inventory — list ALL pods in namespace (no labelSelector).
    Returns [{name, phase, restarts (total), node}].
    Swallow exceptions → empty list.
    """
    try:
        path = f"/api/v1/namespaces/{namespace}/pods"
        data = await _k8s_get(path, api_url=api_url, token=token, verify_ssl=verify_ssl)

        pods = []
        for item in (data.get("items") or []):
            pod_name = item.get("metadata", {}).get("name", "")
            phase = item.get("status", {}).get("phase", "Unknown")
            node_name = item.get("spec", {}).get("nodeName", "")
            restarts = 0
            for cs in (item.get("status", {}).get("containerStatuses") or []):
                restarts += cs.get("restartCount", 0)
            pods.append({
                "name": pod_name,
                "phase": phase,
                "restarts": restarts,
                "node": node_name,
            })
        return pods
    except Exception as e:
        logger.warning(f"list_pods failed: {e}")
        return []


async def list_deployments(
    *,
    api_url: str,
    token: str,
    namespace: str = "default",
    verify_ssl: bool = False,
) -> List[Dict[str, Any]]:
    """
    Fix #268: inventory — list ALL deployments in namespace.
    GET /apis/apps/v1/namespaces/{ns}/deployments.
    Returns [{name, desired, ready, available}].
    Swallow exceptions → empty list.
    """
    try:
        path = f"/apis/apps/v1/namespaces/{namespace}/deployments"
        data = await _k8s_get(path, api_url=api_url, token=token, verify_ssl=verify_ssl)

        deployments = []
        for item in (data.get("items") or []):
            status = item.get("status", {})
            deployments.append({
                "name": item.get("metadata", {}).get("name", ""),
                "desired": status.get("replicas", 0),
                "ready": status.get("readyReplicas", 0),
                "available": status.get("availableReplicas", 0),
            })
        return deployments
    except Exception as e:
        logger.warning(f"list_deployments failed: {e}")
        return []


async def get_node_pressure(
    node_name: str,
    *,
    api_url: str,
    token: str,
    verify_ssl: bool = False,
) -> Dict[str, Any]:
    """
    GET /api/v1/nodes/{node} — conditions (MemoryPressure, DiskPressure, PIDPressure).
    Returns {name, conditions: [{type, status, reason}], allocatable, capacity}.
    Swallow exceptions → empty dict.
    """
    try:
        path = f"/api/v1/nodes/{node_name}"
        data = await _k8s_get(path, api_url=api_url, token=token, verify_ssl=verify_ssl)

        conditions = []
        for c in (data.get("status", {}).get("conditions") or []):
            conditions.append({
                "type": c.get("type", ""),
                "status": c.get("status", ""),
                "reason": c.get("reason", ""),
                "message": c.get("message", ""),
            })

        return {
            "name": node_name,
            "conditions": conditions,
            "allocatable": data.get("status", {}).get("allocatable", {}),
            "capacity": data.get("status", {}).get("capacity", {}),
        }
    except Exception as e:
        logger.warning(f"get_node_pressure failed: {e}")
        return {}
