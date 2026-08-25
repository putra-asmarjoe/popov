"""
Tickets router — FE-3 Ticketing Core.
Semua endpoint butuh auth + membership workspace project terkait.

- GET   /projects/{projectId}/tickets   → list + filter + pagination + sort
- POST  /projects/{projectId}/tickets   → buat tiket (nomor atomic per project)
- GET   /tickets/{id}                   → detail (assigneesDetail join user)
- PATCH /tickets/{id}                   → edit (creator atau assignee)
- POST  /tickets/{id}/assign            → set assignees (harus member workspace)
- DELETE /tickets/{id}/assign/{userId}  → hapus satu assignee
- POST  /tickets/{id}/status            → transisi forward-only (422 bila invalid)
- POST  /tickets/{id}/reopen            → resolved|closed → open + progress entry
- POST  /tickets/{id}/progress          → tambah catatan progress
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import get_current_user
from services.notification_store import create_notification
from services.ticket_alert_store import list_alerts_for_ticket, public_alert
from services.ticket_store import (
    add_progress_note,
    can_reopen,
    change_status,
    create_ticket,
    get_ticket,
    list_tickets,
    mark_opened,
    public_ticket,
    reopen_ticket,
    remove_assignee,
    set_assignees,
    update_ticket,
)
from services.user_store import get_user
from services.workspace_store import (
    find_project_by_id,
    find_workspace_by_id,
    get_membership,
    is_workspace_admin,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tickets"])


# ── Request schema ─────────────────────────────────────────────────────────────

class TicketCreateRequest(BaseModel):
    title: str
    description: str
    kind: str = "business_logic"
    severity: str
    environment: str = "production"
    traceId: Optional[str] = None
    tags: Optional[List[str]] = None


class TicketUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    tags: Optional[List[str]] = None
    kind: Optional[str] = None
    environment: Optional[str] = None
    traceId: Optional[str] = None


class AssignRequest(BaseModel):
    userIds: List[str]


class StatusRequest(BaseModel):
    status: str


class ProgressRequest(BaseModel):
    note: str


# ── Helper ─────────────────────────────────────────────────────────────────────

async def _project_and_ws_or_403(project_id: str, user: Dict[str, Any]):
    project = await find_project_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project tidak ditemukan")
    ws = await find_workspace_by_id(project.get("workspaceId", ""))
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace tidak ditemukan")
    if get_membership(ws, str(user["_id"])) is None:
        raise HTTPException(status_code=403, detail="Kamu bukan member workspace ini")
    return project, ws


async def _ticket_or_404(ticket_id: str) -> Dict[str, Any]:
    ticket = await get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    return ticket


async def _check_ticket_access(ticket_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Load tiket + pastikan user member workspace project tsb."""
    ticket = await _ticket_or_404(ticket_id)
    await _project_and_ws_or_403(str(ticket.get("projectId", "")), user)
    return ticket


async def _attach_assignees_detail(tickets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Join nama/email assignee (batch, dedup userId)."""
    user_ids = sorted({uid for t in tickets for uid in t.get("assignees", [])})
    users: Dict[str, Dict[str, Any]] = {}
    for uid in user_ids:
        u = await get_user(uid)
        if u:
            users[uid] = u
    result = []
    for t in tickets:
        pub = public_ticket(t)
        pub["assigneesDetail"] = [
            {"userId": uid, "name": users.get(uid, {}).get("name", "(?)"), "email": users.get(uid, {}).get("email", "")}
            for uid in t.get("assignees", [])
        ]
        result.append(pub)
    return result


async def _require_editor(ticket: Dict[str, Any], user: Dict[str, Any]) -> None:
    """Edit hanya pembuat, assignee, ATAU admin workspace."""
    uid = str(user["_id"])
    if uid == str(ticket.get("createdBy")) or uid in ticket.get("assignees", []):
        return
    # izinkan admin workspace
    project = await find_project_by_id(str(ticket.get("projectId", "")))
    if project:
        ws = await find_workspace_by_id(str(project.get("workspaceId", "")))
        if ws and is_workspace_admin(ws, uid):
            return
    raise HTTPException(status_code=403, detail="Hanya pembuat, assignee, atau admin workspace yang bisa mengedit")


# ── List & Create ──────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/tickets")
async def list_project_tickets(
    project_id: str,
    status: Optional[str] = Query(None, description="Multi, comma: open,in_progress"),
    severity: Optional[str] = Query(None, description="Multi, comma: critical,high"),
    environment: Optional[str] = None,
    assignee: Optional[str] = None,
    search: Optional[str] = None,
    service: Optional[str] = Query(None, description="Filter serviceName (Fix #40)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort: str = Query("createdAt:desc"),
    current_user: dict = Depends(get_current_user),
):
    await _project_and_ws_or_403(project_id, current_user)

    def _split_multi(value: Optional[str]) -> Optional[List[str]]:
        if not value:
            return None
        items = [v.strip() for v in value.split(",") if v.strip()]
        return items or None

    tickets, meta = await list_tickets(
        project_id,
        status=_split_multi(status),
        severity=_split_multi(severity),
        environment=environment or None,
        assignee=assignee or None,
        search=search or None,
        service=service or None,
        page=page,
        limit=limit,
        sort=sort,
    )
    return {"tickets": await _attach_assignees_detail(tickets), "meta": meta}


@router.post("/projects/{project_id}/tickets", status_code=201)
async def create_project_ticket(
    project_id: str,
    body: TicketCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    project, _ws = await _project_and_ws_or_403(project_id, current_user)
    if len(body.title.strip()) < 5:
        raise HTTPException(status_code=422, detail="Judul minimal 5 karakter")
    if len(body.description.strip()) < 10:
        raise HTTPException(status_code=422, detail="Deskripsi minimal 10 karakter")
    try:
        ticket = await create_ticket(
            project,
            current_user,
            title=body.title,
            description=body.description,
            kind=body.kind,
            severity=body.severity,
            environment=body.environment,
            trace_id=body.traceId,
            tags=body.tags,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result = (await _attach_assignees_detail([ticket]))[0]
    return result


# ── Detail / Edit ──────────────────────────────────────────────────────────────

@router.get("/tickets/{ticket_id}")
async def ticket_detail(
    ticket_id: str,
    current_user: dict = Depends(get_current_user),
):
    ticket = await _check_ticket_access(ticket_id, current_user)
    return (await _attach_assignees_detail([ticket]))[0]


@router.get("/tickets/{ticket_id}/alerts")
async def list_ticket_alerts_endpoint(
    ticket_id: str,
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Daftar alert notifikasi ter-link ke tiket (1 tiket : N alert), terbaru dulu."""
    ticket = await _check_ticket_access(ticket_id, current_user)
    alerts = await list_alerts_for_ticket(str(ticket["_id"]), limit=limit)
    return {"alerts": [public_alert(a) for a in alerts], "total": len(alerts)}


@router.patch("/tickets/{ticket_id}")
async def edit_ticket(
    ticket_id: str,
    body: TicketUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    ticket = await _check_ticket_access(ticket_id, current_user)
    await _require_editor(ticket, current_user)
    try:
        updated = await update_ticket(
            ticket_id,
            title=body.title,
            description=body.description,
            severity=body.severity,
            tags=body.tags,
            kind=body.kind,
            environment=body.environment,
            trace_id=body.traceId,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    return (await _attach_assignees_detail([updated]))[0]


# ── Assign ─────────────────────────────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/assign")
async def assign_users(
    ticket_id: str,
    body: AssignRequest,
    current_user: dict = Depends(get_current_user),
):
    ticket = await _check_ticket_access(ticket_id, current_user)
    project = await find_project_by_id(str(ticket["projectId"]))
    ws = await find_workspace_by_id(project.get("workspaceId", ""))
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace tidak ditemukan")
    member_ids = {m.get("userId") for m in ws.get("members", [])}
    invalid = [uid for uid in body.userIds if uid not in member_ids]
    if invalid:
        raise HTTPException(status_code=422, detail="Ada assignee yang bukan member workspace")
    old_assignees = set(ticket.get("assignees", []))
    actor_id = str(current_user["_id"])
    updated = await set_assignees(ticket_id, list(dict.fromkeys(body.userIds)))
    if updated is None:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")

    # FE-4: notifikasi assignee baru (skip actor sendiri)
    display = f"{project.get('key', '?')}-{updated.get('ticketNumber', '?')}"
    for uid in updated.get("assignees", []):
        if uid not in old_assignees and uid != actor_id:
            try:
                await create_notification(
                    uid,
                    "ticket:assigned",
                    f'Kamu di-assign ke {display} "{updated.get("title", "")}"',
                    {
                        "ticketId": ticket_id,
                        "ticketNumber": updated.get("ticketNumber"),
                        "projectId": str(ticket.get("projectId", "")),
                        "projectKey": project.get("key", ""),
                    },
                )
            except Exception as e:
                logger.warning(f"Notification create failed: {e}")

    return (await _attach_assignees_detail([updated]))[0]


@router.delete("/tickets/{ticket_id}/assign/{user_id}")
async def unassign_user(
    ticket_id: str,
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _check_ticket_access(ticket_id, current_user)
    updated = await remove_assignee(ticket_id, user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    return (await _attach_assignees_detail([updated]))[0]


# ── Status / Reopen / Progress ─────────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/status")
async def change_ticket_status(
    ticket_id: str,
    body: StatusRequest,
    current_user: dict = Depends(get_current_user),
):
    ticket = await _check_ticket_access(ticket_id, current_user)
    updated, error = await change_status(ticket, body.status, current_user)
    if error:
        raise HTTPException(status_code=422, detail=error)
    return (await _attach_assignees_detail([updated]))[0]


@router.post("/tickets/{ticket_id}/reopen")
async def reopen(
    ticket_id: str,
    current_user: dict = Depends(get_current_user),
):
    ticket = await _check_ticket_access(ticket_id, current_user)
    if not can_reopen(ticket.get("status", "open")):
        raise HTTPException(status_code=422, detail="Hanya tiket resolved/closed yang bisa dibuka kembali")
    updated = await reopen_ticket(ticket, current_user)
    return (await _attach_assignees_detail([updated]))[0]


@router.post("/tickets/{ticket_id}/open")
async def mark_ticket_opened(
    ticket_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Tandai tiket 'new' → 'open' (tiket sudah dibuka user). Idempotent & silent —
    selain 'new' → no-op (kembalikan tiket saat ini)."""
    ticket = await _check_ticket_access(ticket_id, current_user)
    updated = await mark_opened(ticket, current_user)
    if updated is None:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    return (await _attach_assignees_detail([updated]))[0]


@router.post("/tickets/{ticket_id}/progress")
async def add_progress(
    ticket_id: str,
    body: ProgressRequest,
    current_user: dict = Depends(get_current_user),
):
    ticket = await _check_ticket_access(ticket_id, current_user)
    if len(body.note.strip()) < 2:
        raise HTTPException(status_code=422, detail="Catatan minimal 2 karakter")
    updated = await add_progress_note(ticket, body.note, current_user)
    if updated is None:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    return (await _attach_assignees_detail([updated]))[0]
