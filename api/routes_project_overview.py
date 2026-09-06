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

from fastapi import APIRouter, Depends, HTTPException, Query

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


async def _query_alerts(db, project_id: str, workspace_id: str, limit: int = 10, days: int = 30) -> List[Dict[str, Any]]:
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

        docs = await list_alerts_for_project(project_id, limit=limit, days=days)
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


async def _query_dashboard_stats(db, project_id: str, days: int, open_only: bool = False) -> dict:
    """Aggregation stats untuk dashboard analytics.

    Semua query paralel via asyncio.gather internal.
    Scope: project_id + rentang waktu `days` hari terakhir.
    open_only=True → filter severity/kind/trend/top_services hanya tiket open (warroom context).
    MTTR: Python-side (datetime.fromisoformat stdlib) — field ISO string, bukan BSON Date.
    """
    from datetime import timedelta

    TICKETS = "tickets"
    TICKET_ALERTS = "ticket_alerts"
    ACTIVE_STATUSES = ["new", "open", "in_progress", "needs_review"]

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    since_iso = since.isoformat()

    # Match filter untuk open tickets saja (warroom context)
    open_match = {"status": {"$in": ACTIVE_STATUSES}} if open_only else {}

    # ── 1. Count by status (filter by days + open_only) ──────────────────
    async def _by_status():
        pipeline = [
            {"$match": {"projectId": project_id, "createdAt": {"$gte": since_iso}, **open_match}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        result = await db[TICKETS].aggregate(pipeline).to_list(None)
        return {r["_id"]: r["count"] for r in result}

    # ── 2. Count by severity (filter by days + open_only) ────────────────
    async def _by_severity():
        pipeline = [
            {"$match": {"projectId": project_id, "createdAt": {"$gte": since_iso}, **open_match}},
            {"$group": {"_id": "$severity", "count": {"$sum": 1}}},
        ]
        result = await db[TICKETS].aggregate(pipeline).to_list(None)
        return {r["_id"]: r["count"] for r in result}

    # ── 3. Count by kind (filter by days + open_only) ────────────────────
    async def _by_kind():
        pipeline = [
            {"$match": {"projectId": project_id, "createdAt": {"$gte": since_iso}, **open_match}},
            {"$group": {"_id": "$kind", "count": {"$sum": 1}}},
        ]
        result = await db[TICKETS].aggregate(pipeline).to_list(None)
        return {r["_id"]: r["count"] for r in result}

    # ── 4. Ticket created trend (N hari, group by date) ───────────────────
    async def _created_trend():
        pipeline = [
            {"$match": {
                "projectId": project_id,
                "createdAt": {"$gte": since_iso},
                **open_match,
            }},
            {"$group": {
                "_id": {"$substr": ["$createdAt", 0, 10]},
                "count": {"$sum": 1},
            }},
            {"$sort": {"_id": 1}},
        ]
        result = await db[TICKETS].aggregate(pipeline).to_list(None)
        return [{"date": r["_id"], "count": r["count"]} for r in result]

    # ── 5. Ticket resolved trend (N hari, group by date) ──────────────────
    async def _resolved_trend():
        pipeline = [
            {"$match": {
                "projectId": project_id,
                "resolvedAt": {"$gte": since_iso, "$ne": None},
            }},
            {"$group": {
                "_id": {"$substr": ["$resolvedAt", 0, 10]},
                "count": {"$sum": 1},
            }},
            {"$sort": {"_id": 1}},
        ]
        result = await db[TICKETS].aggregate(pipeline).to_list(None)
        return [{"date": r["_id"], "count": r["count"]} for r in result]

    # ── 6. Top services by ticket count (N hari) ─────────────────────────
    # Fix #223: tiket multi-service — serviceName (utama) + serviceIds (0..N).
    async def _top_services():
        SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        pipeline = [
            {"$match": {
                "projectId": project_id,
                "createdAt": {"$gte": since_iso},
                **open_match,
                "$or": [
                    {"serviceIds": {"$exists": True, "$ne": []}},
                    {"serviceName": {"$ne": None, "$ne": ""}},
                ],
            }},
            {"$project": {
                "severity": 1,
                "serviceNames": {"$cond": [
                    {"$and": [{"$isArray": "$serviceIds"}, {"$gt": [{"$size": "$serviceIds"}, 0]}]},
                    "$serviceIds",
                    {"$cond": [{"$ne": ["$serviceName", None]}, ["$serviceName"], []]},
                ]},
            }},
            {"$unwind": "$serviceNames"},
            {"$group": {
                "_id": "$serviceNames",
                "count": {"$sum": 1},
                "severities": {"$push": "$severity"},
            }},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        result = await db[TICKETS].aggregate(pipeline).to_list(None)
        out = []
        for r in result:
            worst = min(r["severities"], key=lambda s: SEVERITY_RANK.get(s, 99))
            out.append({
                "service": r["_id"],
                "count": r["count"],
                "worst_severity": worst,
            })
        return out

    # ── 7. Top 5 alert types by frequency (N hari, dari ticket_alerts) ────
    async def _top_alert_types():
        pipeline = [
            {"$match": {
                "projectId": project_id,
                "occurredAt": {"$gte": since_iso},
            }},
            {"$group": {"_id": "$name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        result = await db[TICKET_ALERTS].aggregate(pipeline).to_list(None)
        return [{"name": r["_id"], "count": r["count"]} for r in result]

    # ── 8. MTTR rata-rata (N hari, tiket yang resolved) ───────────────────
    async def _mttr():
        cursor = db[TICKETS].find(
            {
                "projectId": project_id,
                "resolvedAt": {"$gte": since_iso, "$ne": None},
            },
            {"createdAt": 1, "resolvedAt": 1},
        )
        docs = await cursor.to_list(500)
        if not docs:
            return None
        deltas = []
        for d in docs:
            try:
                created = datetime.fromisoformat(d["createdAt"].replace("Z", "+00:00"))
                resolved = datetime.fromisoformat(d["resolvedAt"].replace("Z", "+00:00"))
                diff = (resolved - created).total_seconds()
                if diff > 0:
                    deltas.append(diff)
            except Exception:
                pass
        return round(sum(deltas) / len(deltas)) if deltas else None

    # ── 9. Unassigned open count ──────────────────────────────────────────
    async def _unassigned():
        return await db[TICKETS].count_documents({
            "projectId": project_id,
            "createdAt": {"$gte": since_iso},
            "status": {"$in": ACTIVE_STATUSES},
            "assignees": [],
        })

    # ── 10. AI investigated count ─────────────────────────────────────────
    async def _ai_investigated():
        return await db[TICKETS].count_documents({
            "projectId": project_id,
            "createdAt": {"$gte": since_iso},
            "episode_id": {"$ne": None, "$exists": True},
        })

    # ── 11. Recurring alerts count (alertsCount > 1) ─────────────────────
    async def _recurring():
        return await db[TICKETS].count_documents({
            "projectId": project_id,
            "createdAt": {"$gte": since_iso},
            "alertsCount": {"$gt": 1},
        })

    # ── Jalankan semua paralel ────────────────────────────────────────────
    (
        by_status,
        by_severity,
        by_kind,
        created_trend,
        resolved_trend,
        top_services,
        top_alert_types,
        mttr,
        unassigned,
        ai_investigated,
        recurring,
    ) = await asyncio.gather(
        _by_status(),
        _by_severity(),
        _by_kind(),
        _created_trend(),
        _resolved_trend(),
        _top_services(),
        _top_alert_types(),
        _mttr(),
        _unassigned(),
        _ai_investigated(),
        _recurring(),
    )

    return {
        "days": days,
        "ticket_counts_by_status": by_status,
        "ticket_counts_by_severity": by_severity,
        "ticket_counts_by_kind": by_kind,
        "tickets_created_trend": created_trend,
        "tickets_resolved_trend": resolved_trend,
        "top_services": top_services,
        "top_alert_types": top_alert_types,
        "mttr_seconds": mttr,
        "unassigned_open_count": unassigned,
        "ai_investigated_count": ai_investigated,
        "recurring_alerts_count": recurring,
    }


@router.get("/projects/{project_id}/overview")
async def get_project_overview(
    project_id: str,
    days: int = Query(default=7, ge=1, le=30),
    open_only: bool = Query(default=False),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    project, ws = await _project_and_ws_or_403(project_id, current_user)
    workspace_id = str(project.get("workspaceId", ""))

    db = get_db()
    observ_ids = await _project_observ_ids(db, project_id, workspace_id)

    tickets_t, alerts_t, episodes_t, stacks_t, stats_t = await asyncio.gather(
        _query_open_tickets(db, project_id, workspace_id),
        _query_alerts(db, project_id, workspace_id, days=days),
        _query_episodes(db, project_id, workspace_id, observ_ids),
        _get_stack_health(db, project_id, workspace_id),
        _query_dashboard_stats(db, project_id, days, open_only),
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
        "dashboard_stats": stats_t,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }