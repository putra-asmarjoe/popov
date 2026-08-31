"""
Project Overview router — War Room Part A (plan WARROOM_IMPLEMENTATION2.md §5.2).

Aggregates project health dari 4 collections (tickets, watchdog_alerts,
incident_episodes, observability_targets). Semua query paralel via asyncio.gather,
target latency <500ms. Field mapping SUDAH diverifikasi (bukan versi v1 yang salah):

  - tickets:      createdAt / ticketNumber / severity (BUKAN created_at / key)
  - watchdog_alerts: TIDAK punya project_id → scope via observ_id join
                    (observability_targets.project_ids) ATAU workspace-wide fallback
  - incident_episodes: TIDAK punya severity; pakai root_cause + confidence
  - observability_targets: health_status (bukan last_status) + last_health_check_at

Auth: JWT + membership workspace (pola api.tickets).
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from api.tickets import _project_and_ws_or_403
from services.mongodb_client import get_db
from services.request_log import REQUEST_LOG_COLLECTION, WATCHDOG_ALERT_COLLECTION
from services.second_brain import INCIDENT_EPISODES_COLLECTION

logger = logging.getLogger(__name__)
router = APIRouter(tags=["project-overview"])

_OPEN_STATUSES = {"new", "open", "in_progress", "needs_review"}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _mask_url(url: str) -> str:
    """Sembunyikan credentials di URL (scheme://host[:port] saja)."""
    if not url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    host_port = rest.split("/", 1)[0]
    if "@" in host_port:
        host_port = host_port.split("@")[-1]
    return f"{scheme}://{host_port}"


def _publicize(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ObjectId tak bisa JSON-serialize → ganti _id dengan id:str (pola public_*)."""
    out = []
    for it in items or []:
        d = dict(it)
        if "_id" in d:
            d["id"] = str(d.pop("_id"))
        out.append(d)
    return out


async def _project_observ_ids(db, project_id: str, workspace_id: str) -> List[str]:
    """observ_id yang terikat project — dipakai scope alerts & episodes."""
    return await db["observability_targets"].distinct(
        "observ_id",
        {"workspace_id": workspace_id, "project_ids": project_id, "enabled": True},
    )


async def _query_open_tickets(db, project_id: str, workspace_id: str) -> List[Dict[str, Any]]:
    cursor = db["tickets"].find(
        {"projectId": project_id, "workspaceId": workspace_id,
         "status": {"$nin": ["resolved", "closed"]}},
        {"ticketNumber": 1, "title": 1, "severity": 1, "severityRank": 1,
         "status": 1, "serviceName": 1, "createdAt": 1},
    ).sort("createdAt", -1).limit(20)
    return await cursor.to_list(20)


async def _query_alerts(db, project_id: str, workspace_id: str, observ_ids: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"workspace_id": workspace_id}
    if observ_ids:
        q["observ_id"] = {"$in": observ_ids}
    cursor = db[WATCHDOG_ALERT_COLLECTION].find(
        q, {"_id": 1, "message": 1, "fingerprint": 1, "service_name": 1,
            "observ_id": 1, "sent_at": 1, "status": 1},
    ).sort("sent_at", -1).limit(limit)
    return await cursor.to_list(limit)


async def _query_episodes(db, workspace_id: str, observ_ids: List[str], limit: int = 20) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"workspace_id": workspace_id}
    if observ_ids:
        q["observ_id"] = {"$in": observ_ids}
    cursor = db[INCIDENT_EPISODES_COLLECTION].find(
        q, {"_id": 1, "episode_id": 1, "service_name": 1, "root_cause": 1,
            "confidence": 1, "created_at": 1, "ticket_id": 1,
            "actual_ttr_minutes": 1, "enriched_at": 1},
    ).sort("created_at", -1).limit(limit)
    return await cursor.to_list(limit)


async def _get_stack_health(db, project_id: str, workspace_id: str) -> List[Dict[str, Any]]:
    cursor = db["observability_targets"].find(
        {"workspace_id": workspace_id, "project_ids": project_id},
        {"_id": 1, "kind": 1, "health_status": 1, "last_health_check_at": 1,
         "prometheus_url": 1, "tempo_url": 1, "loki_url": 1, "alertmanager_url": 1},
    )
    targets = await cursor.to_list(None)
    return [
        {
            "kind": t.get("kind"),
            "url": _mask_url(
                t.get("prometheus_url") or t.get("tempo_url")
                or t.get("loki_url") or t.get("alertmanager_url") or ""
            ),
            "health_status": t.get("health_status", "unknown"),
            "last_health_check_at": t.get("last_health_check_at"),
        }
        for t in targets
    ]


@router.get("/projects/{project_id}/overview")
async def get_project_overview(
    project_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    project, ws = await _project_and_ws_or_403(project_id, current_user)
    workspace_id = str(project.get("workspaceId", ""))

    db = get_db()
    observ_ids = await _project_observ_ids(db, project_id, workspace_id)

    tickets_t, alerts_t, episodes_t, stacks_t = await asyncio.gather(
        _query_open_tickets(db, project_id, workspace_id),
        _query_alerts(db, project_id, workspace_id, observ_ids),
        _query_episodes(db, workspace_id, observ_ids),
        _get_stack_health(db, project_id, workspace_id),
    )

    open_tickets = [t for t in tickets_t if t.get("status") in _OPEN_STATUSES]
    by_severity = {
        sev: sum(1 for t in open_tickets if t.get("severity") == sev)
        for sev in ("critical", "high", "medium", "low")
    }

    return {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "project_key": project.get("key", ""),
        "project_name": project.get("name", ""),
        "ticket_summary": {
            "open_count": len(open_tickets),
            "by_severity": by_severity,
            "recent": _publicize(open_tickets[:5]),
        },
        "alert_feed": _publicize(alerts_t),
        "episode_timeline": _publicize(episodes_t),
        "stack_health": _publicize(stacks_t),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }