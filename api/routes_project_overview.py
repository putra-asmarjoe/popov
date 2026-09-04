"""
Project Overview router — War Room Part A (plan WARROOM_IMPLEMENTATION2.md §5.2).

Aggregates project health dari 4 collections (tickets, ticket_alerts,
incident_episodes, observability_targets). Semua query paralel via asyncio.gather,
target latency <500ms. Field mapping SUDAH diverifikasi (bukan versi v1 yang salah):

  - tickets:      createdAt / ticketNumber / severity (BUKAN created_at / key)
  - ticket_alerts: alert feed = alert yang TER-TIKET (relasi alert→ticket→project).
                  Dipakai langsung via projectId — TANPA join observ_id & TANPA
                  fallback workspace-wide (fix bocor lintas project saat project
                  tanpa stack). Bukan lagi watchdog_alerts (broadcast log tanpa
                  project_id, hanya observ_id indirek).
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
from services.request_log import REQUEST_LOG_COLLECTION
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


async def _query_alerts(db, project_id: str, workspace_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Alert feed project = alert yang TER-TIKET (ticket_alerts), bukan broadcast log.

    Relasi yang benar: alert → ticket → project. ticket_alerts membawa projectId +
    ticketId eksplisit (ditulis auto_ticket saat alert memicu/menempel tiket). Query
    per-project langsung — TANPA join observ_id dan TANPA fallback workspace-wide
    (fallback itu bocor lintas project saat project tanpa observability target).

    Map ke shape OverviewAlert (FE lama: message/fingerprint/service_name/sent_at)
    supaya perubahan sumber data tidak mengubah kontrak FE.
    """
    try:
        from services.ticket_alert_store import list_alerts_for_project

        docs = await list_alerts_for_project(project_id, limit=limit)
    except Exception as e:
        logger.warning(f"Overview alerts query gagal (non-fatal): {e}")
        return []
    out = []
    for d in docs:
        out.append({
            "_id": d.get("_id"),
            "message": d.get("name") or "",
            "fingerprint": d.get("contentFp") or None,
            "service_name": d.get("serviceName") or None,
            "observ_id": d.get("observId") or None,
            "sent_at": d.get("occurredAt"),
            "status": None,
            "project_id": d.get("projectId") or None,
            "ticket_id": d.get("ticketId") or None,
            "severity": d.get("severity") or "warning",
        })
    return out[:limit]


async def _query_episodes(db, project_id: str, workspace_id: str, observ_ids: List[str], limit: int = 20) -> List[Dict[str, Any]]:
    """Episode timeline project = investigasi yang terikat project.

    Relasi: episode → ticket_id → ticket(projectId). Episode tanpa ticket_id (dari
    channel non-tiket) di-scope via observ_id. Project tanpa keduanya → kosong
    (TANPA fallback workspace-wide — fallback itu bocor lintas project).
    """
    ticket_ids = []
    try:
        cur = db["tickets"].find(
            {"projectId": project_id, "workspaceId": workspace_id}, {"_id": 1}
        )
        ticket_ids = [str(t["_id"]) async for t in cur]
    except Exception as e:
        logger.warning(f"Overview episode tickets lookup gagal (non-fatal): {e}")

    conds: List[Dict[str, Any]] = []
    if ticket_ids:
        conds.append({"ticket_id": {"$in": ticket_ids}})
    if observ_ids:
        conds.append({"observ_id": {"$in": observ_ids}})
    if not conds:
        return []

    q: Dict[str, Any] = {"workspace_id": workspace_id, "$or": conds}
    cursor = db[INCIDENT_EPISODES_COLLECTION].find(
        q, {"_id": 1, "episode_id": 1, "service_name": 1, "root_cause": 1,
            "confidence": 1, "created_at": 1, "ticket_id": 1,
            "actual_ttr_minutes": 1, "enriched_at": 1, "symptoms": 1},
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
        _query_alerts(db, project_id, workspace_id),
        _query_episodes(db, project_id, workspace_id, observ_ids),
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