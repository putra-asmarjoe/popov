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
from typing import Annotated, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_current_user
from services.notification_store import (
    SUPPORTED_CHANNELS,
    _strip_secrets,
    create_target,
    delete_notification,
    extract_email_creds,
    extract_telegram_creds,
    get_notification,
    list_notifications,
    list_project_usage,
    record_health,
    set_project_link,
    update_notification,
    update_notification_config,
    verify_bot_token,
    verify_smtp,
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

class ChannelCreateTelegram(BaseModel):
    name: str
    channel: Literal["telegram"] = "telegram"
    bot_token: str
    chat_id: str


class ChannelCreateEmail(BaseModel):
    name: str
    channel: Literal["email"] = "email"
    smtp_host: str
    smtp_port: int = 587
    security: Literal["starttls", "ssl", "none"] = "starttls"
    ignore_tls_error: bool = False
    disable_starttls: bool = False
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    from_addr: str
    to_addrs: list[str] = Field(min_length=1)
    cc_addrs: list[str] = []
    bcc_addrs: list[str] = []


ChannelCreate = Annotated[
    Union[ChannelCreateTelegram, ChannelCreateEmail],
    Field(discriminator="channel"),
]


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    # partial update — telegram
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    # partial update — email (semua opsional; smtp_pass kosong = biarkan lama)
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    security: Optional[str] = None
    ignore_tls_error: Optional[bool] = None
    disable_starttls: Optional[bool] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    from_addr: Optional[str] = None
    to_addrs: Optional[list[str]] = None
    cc_addrs: Optional[list[str]] = None
    bcc_addrs: Optional[list[str]] = None


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

    if body.channel == "telegram":
        if not body.bot_token.strip() or not body.chat_id.strip():
            raise HTTPException(422, "bot_token dan chat_id wajib diisi")
        probe = await verify_bot_token(body.bot_token.strip())
        if not probe.get("ok"):
            raise HTTPException(422, f"bot_token tidak valid: {probe.get('error')}")
        config = {"telegram": {"bot_token": body.bot_token.strip(), "chat_id": body.chat_id.strip()}}
        health_meta = probe.get("username")
    else:  # email
        if not body.smtp_host.strip() or not body.from_addr.strip() or not body.to_addrs:
            raise HTTPException(422, "smtp_host, from_addr, dan to_addrs wajib diisi")
        probe = await verify_smtp(
            body.smtp_host.strip(), body.smtp_port, body.security,
            body.smtp_user, body.smtp_pass,
            body.ignore_tls_error, body.disable_starttls,
        )
        if not probe.get("ok"):
            raise HTTPException(422, f"SMTP tidak valid: {probe.get('error')}")
        config = {"email": {
            "smtp_host": body.smtp_host.strip(),
            "smtp_port": body.smtp_port,
            "security": body.security,
            "ignore_tls_error": body.ignore_tls_error,
            "disable_starttls": body.disable_starttls,
            "smtp_user": (body.smtp_user or "").strip() or None,
            "smtp_pass": body.smtp_pass,
            "from_addr": body.from_addr.strip(),
            "to_addrs": [x.strip() for x in body.to_addrs if x.strip()],
            "cc_addrs": [x.strip() for x in body.cc_addrs if x.strip()],
            "bcc_addrs": [x.strip() for x in body.bcc_addrs if x.strip()],
        }}
        health_meta = probe.get("banner")

    doc = await create_target(
        name=body.name,
        channel=body.channel,
        workspace_id=str(ws["_id"]),
        project_ids=[],
        config=config,
    )
    await record_health(doc["notif_id"], True, health_meta, channel=body.channel)
    fresh = await get_notification(doc["notif_id"])
    out = _strip_secrets(fresh or doc)
    ch = out.setdefault("config", {}).setdefault(body.channel, {})
    if body.channel == "telegram":
        ch["botUsername"] = probe.get("username")
    logger.info(f"[Channels] created {doc['notif_id']} ws={ws_id} channel={body.channel} by {_uid(current_user)}")
    return {"channel": out}


@router.patch("/notification-channels/{notif_id}")
async def patch_channel(notif_id: str, body: ChannelUpdate, current_user: dict = Depends(get_current_user)):
    doc, ws = await _channel_admin_guard(notif_id, current_user)
    ch_type = doc.get("channel", "telegram")

    patch = {k: v for k, v in {
        "name": body.name,
        "enabled": body.enabled,
    }.items() if v is not None}
    ok = True
    if patch:
        ok = await update_notification(notif_id, patch) and ok

    health_meta = None
    if ch_type == "telegram":
        cfg = {k: v.strip() for k, v in {"bot_token": body.bot_token, "chat_id": body.chat_id}.items() if v and v.strip()}
        if cfg.get("bot_token"):
            probe = await verify_bot_token(cfg["bot_token"])
            if not probe.get("ok"):
                raise HTTPException(422, f"bot_token tidak valid: {probe.get('error')}")
            health_meta = probe.get("username")
    else:  # email — partial update, smtp_pass kosong = biarkan lama
        email_fields = {
            "smtp_host": body.smtp_host, "smtp_port": body.smtp_port,
            "security": body.security, "ignore_tls_error": body.ignore_tls_error,
            "disable_starttls": body.disable_starttls, "smtp_user": body.smtp_user,
            "smtp_pass": body.smtp_pass, "from_addr": body.from_addr,
            "to_addrs": body.to_addrs, "cc_addrs": body.cc_addrs, "bcc_addrs": body.bcc_addrs,
        }
        cfg = {k: v for k, v in email_fields.items() if v is not None}
        if cfg.get("to_addrs") is not None:
            cfg["to_addrs"] = [x.strip() for x in cfg["to_addrs"] if x.strip()]
        if cfg.get("cc_addrs") is not None:
            cfg["cc_addrs"] = [x.strip() for x in cfg["cc_addrs"] if x.strip()]
        if cfg.get("bcc_addrs") is not None:
            cfg["bcc_addrs"] = [x.strip() for x in cfg["bcc_addrs"] if x.strip()]
        if any(k in cfg for k in ("smtp_host", "smtp_user", "smtp_pass", "from_addr", "to_addrs")):
            # re-verify bila kredensial berubah (host/user/pass)
            current = extract_email_creds(doc) or {}
            probe_host = cfg.get("smtp_host") or current.get("host")
            probe_port = cfg.get("smtp_port") or current.get("port")
            probe_sec = cfg.get("security") or current.get("security")
            probe_user = cfg.get("smtp_user") if "smtp_user" in cfg else current.get("user")
            probe_pass = cfg.get("smtp_pass") or current.get("password")
            probe = await verify_smtp(
                probe_host or "", int(probe_port or 587), probe_sec or "starttls",
                probe_user, probe_pass,
                bool(cfg.get("ignore_tls_error") if "ignore_tls_error" in cfg else current.get("ignore_tls_error")),
                bool(cfg.get("disable_starttls") if "disable_starttls" in cfg else current.get("disable_starttls")),
            )
            if not probe.get("ok"):
                raise HTTPException(422, f"SMTP tidak valid: {probe.get('error')}")
            health_meta = probe.get("banner")

    if cfg:
        ok = await update_notification_config(notif_id, ch_type, cfg) and ok
    if not ok:
        raise HTTPException(404, "Channel tidak ditemukan")

    if health_meta is not None or cfg:
        await record_health(notif_id, True, health_meta, channel=ch_type)
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


# ── Test (getMe/verify_smtp + kirim tes) ──────────────────────────────────────

@router.post("/notification-channels/{notif_id}/test")
async def test_channel(notif_id: str, current_user: dict = Depends(get_current_user)):
    """Probe koneksi (Telegram getMe / SMTP handshake) + kirim pesan tes tersimpan."""
    doc, _ws = await _channel_admin_guard(notif_id, current_user)
    ch_type = doc.get("channel", "telegram")

    if ch_type == "telegram":
        token, chat = extract_telegram_creds(doc)
        if not token:
            raise HTTPException(422, "bot_token belum diset")
        probe = await verify_bot_token(token)
        await record_health(notif_id, bool(probe.get("ok")), probe.get("username"), channel="telegram")
        test_sent = False
        send_error = None
        if probe.get("ok"):
            uname = f"@{probe['username']}" if probe.get("username") else "bot"
            try:
                test_sent = await send_message(
                    f"✅ Tes channel *{doc.get('name', notif_id)}* dari {uname} — Popov Agent",
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

    # email
    from services.email_client import send_email

    cfg = extract_email_creds(doc)
    if not cfg or not cfg.get("host"):
        raise HTTPException(422, "smtp_host belum diset")
    probe = await verify_smtp(
        cfg["host"], cfg["port"], cfg["security"],
        cfg.get("user"), cfg.get("password"),
        cfg.get("ignore_tls_error"), cfg.get("disable_starttls"),
    )
    await record_health(notif_id, bool(probe.get("ok")), probe.get("banner"), channel="email")
    test_sent = False
    send_error = None
    if probe.get("ok") and cfg.get("to"):
        try:
            result = await send_email(
                cfg,
                "[Popov] Tes notifikasi email",
                f"✅ Tes channel *{doc.get('name', notif_id)}* — koneksi SMTP OK.\n"
                f"Host: {cfg['host']}:{cfg['port']} · From: {cfg.get('from_addr')}\n"
                "Ini pesan tes dari Popov Agent.",
            )
            test_sent = bool(result.get("ok"))
            if not test_sent:
                send_error = result.get("detail", "gagal kirim")
        except Exception as e:
            send_error = str(e)[:200]
    elif probe.get("ok") and not cfg.get("to"):
        send_error = "to_addrs kosong"
    return {"smtp": probe, "test_sent": test_sent, "error": send_error}


# ── Test raw credentials (before save) ────────────────────────────────────────

class _TestCredentials(BaseModel):
    channel: Literal["telegram", "email"]
    # telegram
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    # email
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    security: Literal["starttls", "ssl", "none"] = "starttls"
    ignore_tls_error: bool = False
    disable_starttls: bool = False
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None


@router.post("/notification-channels/test-credentials")
async def test_credentials(body: _TestCredentials, current_user: dict = Depends(get_current_user)):
    """Probe koneksi tanpa menyimpan channel (buat create dialog)."""
    if body.channel == "telegram":
        if not body.bot_token:
            raise HTTPException(422, "bot_token wajib")
        probe = await verify_bot_token(body.bot_token)
        return {"getMe": probe, "error": None if probe.get("ok") else probe.get("error")}

    # email
    if not body.smtp_host:
        raise HTTPException(422, "smtp_host wajib")
    probe = await verify_smtp(
        body.smtp_host, body.smtp_port, body.security,
        body.smtp_user, body.smtp_pass,
        body.ignore_tls_error, body.disable_starttls,
    )
    return {"smtp": probe, "error": None if probe.get("ok") else probe.get("error")}


# ── Delivery logs (debug — admin workspace) ───────────────────────────────────

@router.get("/notification-channels/delivery-logs")
async def delivery_logs(
    workspace_id: str,
    since_hours: float = Query(24.0, ge=1, le=168),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Log pengiriman alert (ringkas — bukan isi pesan). Admin workspace saja."""
    ws = await _ws_member_or_404(workspace_id, current_user)
    if not is_workspace_admin(ws, _uid(current_user)):
        raise HTTPException(403, "Hanya admin workspace yang bisa melihat delivery logs")
    from services.notification_delivery_logs import list_delivery_logs

    logs = await list_delivery_logs(workspace_id, since_hours=since_hours, limit=limit)
    return {"logs": logs}


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
