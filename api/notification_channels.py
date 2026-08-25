"""
Notification Channels router — Fix #40 (menggantikan endpoint global /config/notification-targets).

Kepemilikan & guard:
- Channel milik WORKSPACE (workspace_id wajib) — dikelola ws-admin di Workspace Settings.
- GET  : semua member workspace boleh baca (bot_token TIDAK pernah keluar — hanya mask).
- POST/PATCH/DELETE/link/unlink/test : HANYA ws-admin (owner atau members[].role=admin).
- DELETE saat masih ter-link project → 409 + daftar project, kecuali ?confirm=true.
- Create/update token selalu divalidasi getMe ke Telegram (settings.telegram_api_base),
  hasilnya dicatat via record_health (bot_username + health_status).

Model data tetap koleksi `notification_targets` (skema config.telegram{bot_token, chat_id}).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from services.notification_store import (
    SUPPORTED_CHANNELS,
    _strip_secrets,
    create_target,
    delete_notification,
    extract_telegram_creds,
    get_notification,
    list_notifications,
    list_project_usage,
    record_health,
    set_project_link,
    update_notification,
    update_notification_config,
    verify_bot_token,
)
from services.telegram_client import send_message
from services.workspace_store import (
    find_project_by_id,
    find_workspace_by_id,
    get_membership,
    is_workspace_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notification-channels"])


# ── Request schemas ───────────────────────────────────────────────────────────

class ChannelCreate(BaseModel):
    name: str
    channel: str = "telegram"          # saat ini hanya "telegram" (wa/slack/discord roadmap)
    bot_token: str
    chat_id: str


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    # partial update — token/chat kosong = biarkan nilai lama
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


# ── Guards ────────────────────────────────────────────────────────────────────

def _uid(user: dict) -> str:
    return str(user["_id"])


async def _ws_member_or_404(ws_id: str, user: dict) -> dict:
    ws = await find_workspace_by_id(ws_id)
    if ws is None:
        raise HTTPException(404, "Workspace tidak ditemukan")
    uid = _uid(user)
    if get_membership(ws, uid) is None and str(ws.get("ownerId", "")) != uid:
        raise HTTPException(403, "Bukan member workspace ini")
    return ws


async def _channel_admin_guard(notif_id: str, user: dict):
    """Channel harus ada; user ws-admin di workspace pemilik channel."""
    doc = await get_notification(notif_id)
    if doc is None:
        raise HTTPException(404, "Channel tidak ditemukan")
    ws = await find_workspace_by_id(str(doc.get("workspace_id") or ""))
    if ws is None:
        raise HTTPException(404, "Workspace pemilik channel tidak ditemukan")
    if not is_workspace_admin(ws, _uid(user)):
        raise HTTPException(403, "Hanya admin workspace yang bisa mengelola notification channel")
    return doc, ws


# ── Workspace-scoped CRUD ─────────────────────────────────────────────────────

@router.get("/workspaces/{ws_id}/notification-channels")
async def list_channels(ws_id: str, current_user: dict = Depends(get_current_user)):
    """Daftar channel workspace (member read). Token hanya bentuk tersamar."""
    await _ws_member_or_404(ws_id, current_user)
    docs = await list_notifications(workspace_id=ws_id, enabled_only=False)
    return {"channels": docs}


@router.post("/workspaces/{ws_id}/notification-channels", status_code=201)
async def create_channel(ws_id: str, body: ChannelCreate, current_user: dict = Depends(get_current_user)):
    ws = await _ws_member_or_404(ws_id, current_user)
    if not is_workspace_admin(ws, _uid(current_user)):
        raise HTTPException(403, "Hanya admin workspace yang bisa menambah notification channel")
    if body.channel not in SUPPORTED_CHANNELS:
        raise HTTPException(422, f"channel '{body.channel}' belum didukung (opsi: {SUPPORTED_CHANNELS})")
    if not body.bot_token.strip() or not body.chat_id.strip():
        raise HTTPException(422, "bot_token dan chat_id wajib diisi")

    probe = await verify_bot_token(body.bot_token.strip())
    if not probe.get("ok"):
        raise HTTPException(422, f"bot_token tidak valid: {probe.get('error')}")

    doc = await create_target(
        name=body.name,
        channel=body.channel,
        workspace_id=str(ws["_id"]),
        project_ids=[],
        config={"telegram": {"bot_token": body.bot_token.strip(), "chat_id": body.chat_id.strip()}},
    )
    await record_health(doc["notif_id"], True, probe.get("username"))
    fresh = await get_notification(doc["notif_id"])
    out = _strip_secrets(fresh or doc)
    tg = out.setdefault("config", {}).setdefault("telegram", {})
    tg["botUsername"] = probe.get("username")
    logger.info(f"[Channels] created {doc['notif_id']} ws={ws_id} by {_uid(current_user)}")
    return {"channel": out}


@router.patch("/notification-channels/{notif_id}")
async def patch_channel(notif_id: str, body: ChannelUpdate, current_user: dict = Depends(get_current_user)):
    doc, ws = await _channel_admin_guard(notif_id, current_user)

    patch = {k: v for k, v in {
        "name": body.name,
        "enabled": body.enabled,
    }.items() if v is not None}
    ok = True
    if patch:
        ok = await update_notification(notif_id, patch) and ok

    cfg = {k: v.strip() for k, v in {"bot_token": body.bot_token, "chat_id": body.chat_id}.items() if v and v.strip()}
    probe_username = None
    if cfg.get("bot_token"):
        probe = await verify_bot_token(cfg["bot_token"])
        if not probe.get("ok"):
            raise HTTPException(422, f"bot_token tidak valid: {probe.get('error')}")
        probe_username = probe.get("username")
    if cfg:
        ok = await update_notification_config(notif_id, doc.get("channel", "telegram"), cfg) and ok
    if not ok:
        raise HTTPException(404, "Channel tidak ditemukan")

    if cfg.get("bot_token"):
        await record_health(notif_id, True, probe_username)
    fresh = await get_notification(notif_id)
    return {"channel": _strip_secrets(fresh or {})}


@router.delete("/notification-channels/{notif_id}")
async def remove_channel(
    notif_id: str,
    confirm: bool = False,
    current_user: dict = Depends(get_current_user),
):
    doc, _ws = await _channel_admin_guard(notif_id, current_user)
    linked = await list_project_usage(notif_id)
    still_linked = bool((doc.get("project_ids") or []))
    if still_linked and not confirm:
        raise HTTPException(
            409,
            detail={
                "message": "Channel masih ter-link ke project. Kirim confirm=true untuk hapus paksa (link ikut terputus).",
                "projects": linked,
            },
        )
    if not await delete_notification(notif_id):
        raise HTTPException(404, "Channel tidak ditemukan")
    logger.info(f"[Channels] deleted {notif_id} by {_uid(current_user)}")
    return {"ok": True}


# ── Test (getMe + kirim pesan tes) ────────────────────────────────────────────

@router.post("/notification-channels/{notif_id}/test")
async def test_channel(notif_id: str, current_user: dict = Depends(get_current_user)):
    """Probe getMe + kirim pesan tes ke chat_id tersimpan."""
    doc, _ws = await _channel_admin_guard(notif_id, current_user)
    token, chat = extract_telegram_creds(doc)
    if not token:
        raise HTTPException(422, "bot_token belum diset")
    probe = await verify_bot_token(token)
    await record_health(notif_id, bool(probe.get("ok")), probe.get("username"))

    test_sent = False
    send_error = None
    if probe.get("ok"):
        uname = f"@{probe['username']}" if probe.get("username") else "bot"
        try:
            test_sent = await send_message(
                f"✅ Tes channel *{doc.get('name', notif_id)}* dari {uname} — Popov Agent Fix #40",
                chat_id=chat or "",
                bot_token=token,
            )
            if not test_sent:
                send_error = "Telegram menolak pesan tes (cek chat_id / bot harus join chat)"
        except ValueError as e:
            send_error = str(e)
        except Exception as e:
            send_error = str(e)[:200]
    return {"getMe": probe, "test_sent": test_sent, "error": send_error}


# ── Link/unlink channel ↔ project ─────────────────────────────────────────────

async def _project_ws_admin(project_id: str, user: dict):
    project = await find_project_by_id(project_id)
    if project is None:
        raise HTTPException(404, "Project tidak ditemukan")
    ws = await find_workspace_by_id(str(project["workspaceId"]))
    if ws is None:
        raise HTTPException(404, "Workspace project tidak ditemukan")
    if not is_workspace_admin(ws, _uid(user)):
        raise HTTPException(403, "Hanya admin workspace yang bisa mengatur link channel project")
    return project, ws


@router.get("/projects/{project_id}/notification-channels")
async def list_project_channels(project_id: str, current_user: dict = Depends(get_current_user)):
    """Semua channel workspace + flag `linked` utk project ini (member read — selector FE)."""
    project = await find_project_by_id(project_id)
    if project is None:
        raise HTTPException(404, "Project tidak ditemukan")
    ws = await find_workspace_by_id(str(project["workspaceId"]))
    if ws is None:
        raise HTTPException(404, "Workspace project tidak ditemukan")
    uid = _uid(current_user)
    if get_membership(ws, uid) is None and str(ws.get("ownerId", "")) != uid:
        raise HTTPException(403, "Bukan member workspace ini")

    ws_id = str(ws["_id"])
    docs = await list_notifications(workspace_id=ws_id, enabled_only=False)
    out = []
    for d in docs:
        out.append({**d, "linked": project_id in (d.get("project_ids") or [])})
    return {"channels": out}


@router.post("/projects/{project_id}/notification-channels/{notif_id}", status_code=201)
async def link_channel(project_id: str, notif_id: str, current_user: dict = Depends(get_current_user)):
    project, ws = await _project_ws_admin(project_id, current_user)
    doc = await get_notification(notif_id)
    if doc is None:
        raise HTTPException(404, "Channel tidak ditemukan")
    if str(doc.get("workspace_id") or "") != str(ws["_id"]):
        raise HTTPException(409, "Channel milik workspace lain")
    await set_project_link(notif_id, project_id, True)
    return {"ok": True, "linked": True}


@router.delete("/projects/{project_id}/notification-channels/{notif_id}")
async def unlink_channel(project_id: str, notif_id: str, current_user: dict = Depends(get_current_user)):
    project, ws = await _project_ws_admin(project_id, current_user)
    doc = await get_notification(notif_id)
    if doc is None:
        raise HTTPException(404, "Channel tidak ditemukan")
    if str(doc.get("workspace_id") or "") != str(ws["_id"]):
        raise HTTPException(409, "Channel milik workspace lain")
    await set_project_link(notif_id, project_id, False)
    return {"ok": True, "linked": False}
