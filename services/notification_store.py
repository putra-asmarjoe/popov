"""
Notification Store — dua tanggung jawab:

1. User bell notifications (FE-4): collection `notifications`
   {userId, type, title, payload, readAt, createdAt} + push WS `user:{userId}`.
2. Multi-channel notification TARGETS per workspace/project (Fix #37):
   collection `notification_targets`

Pola identik observability_targets: 1 workspace bisa punya banyak notifikasi;
project di-link via project_ids (1 notif → banyak project, atau beda notif per project).

Collection `notification_targets`:
    {
      notif_id:       "ntf-<8hex>" unique
      name:           str
      channel:        "telegram"          # whatsapp/slack/discord = roadmap (schema ready)
      workspace_id:   str
      project_ids:    [str]
      config: {                     # per-channel config — WRITE-ONLY via API
        telegram: { bot_token: str, chat_id: str }
      }
      enabled:        bool
      created_at / updated_at / last_used_at
    }

Resolusi pengiriman (chain sama dengan Fase D):
    project_ids ∋ project_id → default workspace → None (= .env global fallback)
Bot token disimpan di DB (dibutuhkan saat kirim) tapi TIDAK PERNAH dikembalikan API —
hanya bentuk tersamar (`mask_bot_token`) + flag `has_token`.
"""
from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from services.event_bus import emit
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

# Fix #54: cache resolusi channel broadcast per (ws, project, channel) — telegram_agent
# TIDAK buka DB per kirim. TTL 30s + invalidate saat mutasi channel/link.
_CHANNEL_CACHE: Dict[Tuple[Optional[str], Optional[str], str], Tuple[float, List[Dict[str, Any]]]] = {}
_CHANNEL_TTL = 30.0


def invalidate_channel_cache() -> None:
    """Panggil setelah mutasi channel (create/update/delete/toggle/link/unlink)."""
    global _CHANNEL_CACHE
    _CHANNEL_CACHE.clear()


NOTIFICATION_TARGETS_COLLECTION = "notification_targets"
NOTIFICATIONS_COLLECTION = "notifications"  # FE-4 user bell

# Channel yang didukung saat ini; lainnya schema-ready (UI tampilkan disabled)
SUPPORTED_CHANNELS = ["telegram"]
CHANNEL_FIELDS = {
    "telegram": ["bot_token", "chat_id"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_notif_id() -> str:
    return f"ntf-{secrets.token_hex(4)}"


def _collection():
    return get_db()[NOTIFICATION_TARGETS_COLLECTION]


def mask_bot_token(token: Optional[str]) -> Optional[str]:
    """Tampilkan hanya 4 karakter terakhir untuk verifikasi visual."""
    if not token:
        return None
    return f"***{token[-4:]}" if len(token) > 8 else "***"


def _strip_secrets(doc: dict) -> dict:
    """Hapus bot_token dari dokumen sebelum keluar API; sisakan mask + chat_id."""
    d = dict(doc)
    cfg = dict(d.get("config") or {})
    tg = dict(cfg.get("telegram") or {})
    tg["bot_token_masked"] = mask_bot_token(tg.pop("bot_token", None))
    tg.pop("bot_token", None)
    cfg["telegram"] = tg
    d["config"] = cfg
    return d


async def ensure_notification_indexes() -> None:
    try:
        coll = _collection()
        await coll.create_index("notif_id", unique=True)
        await coll.create_index([("workspace_id", 1)])
        # FE-4 user bell
        await get_db()[NOTIFICATIONS_COLLECTION].create_index([("userId", 1), ("readAt", 1)])
        logger.info(f"Indexes ensured on '{NOTIFICATION_TARGETS_COLLECTION}' + '{NOTIFICATIONS_COLLECTION}'")
    except Exception as e:
        logger.warning(f"Failed to ensure notification indexes: {e}")


async def create_target(
    name: str,
    channel: str,
    workspace_id: Optional[str] = None,
    project_ids: Optional[list] = None,
    config: Optional[Dict[str, Any]] = None,
) -> dict:
    if channel not in SUPPORTED_CHANNELS:
        raise ValueError(f"channel '{channel}' belum didukung (opsi: {SUPPORTED_CHANNELS})")
    doc = {
        "notif_id": generate_notif_id(),
        "name": name,
        "channel": channel,
        "workspace_id": workspace_id,
        "project_ids": project_ids or [],
        "config": config or {},
        "enabled": True,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await _collection().insert_one(doc)
    invalidate_channel_cache()
    doc["_id"] = str(doc["_id"])
    logger.info(f"[NotificationStore] created {doc['notif_id']} channel={channel} ws={workspace_id}")
    return _strip_secrets(doc)


async def get_notification(notif_id: str) -> Optional[dict]:
    """Return dokumen LENGKAP termasuk config (khusus internal pengiriman)."""
    doc = await _collection().find_one({"notif_id": notif_id})
    if not doc:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


async def list_notifications(
    workspace_id: Optional[str] = None,
    enabled_only: bool = True,
    channel: Optional[str] = None,
) -> List[dict]:
    q: Dict[str, Any] = {}
    if workspace_id:
        q["workspace_id"] = workspace_id
    if channel:
        q["channel"] = channel
    if enabled_only:
        q["enabled"] = {"$ne": False}
    docs = await _collection().find(q).to_list(500)
    out = []
    for d in docs:
        d["_id"] = str(d["_id"])
        out.append(_strip_secrets(d))
    return out


async def list_channels_internal(
    channel: str = "telegram",
    enabled_only: bool = True,
) -> List[dict]:
    """Dokumen channel LENGKAP (config/token included) — KHUSUS internal pengiriman
    & polling (Fix #40). JANGAN pernah dipakai untuk response API."""
    q: Dict[str, Any] = {"channel": channel}
    if enabled_only:
        q["enabled"] = {"$ne": False}
    docs = await _collection().find(q).sort("created_at", 1).to_list(500)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def update_notification(notif_id: str, patch: Dict[str, Any]) -> bool:
    allowed = {"name", "workspace_id", "project_ids", "enabled"}
    clean = {k: v for k, v in patch.items() if k in allowed}
    if not clean:
        return False
    clean["updated_at"] = _now()
    result = await _collection().update_one({"notif_id": notif_id}, {"$set": clean})
    if result.matched_count:
        invalidate_channel_cache()
    return result.matched_count > 0


async def update_notification_config(notif_id: str, channel: str, config: Dict[str, Any]) -> bool:
    """Update config per-channel (partial merge). Token kosong = biarkan token lama."""
    if channel not in SUPPORTED_CHANNELS:
        return False
    doc = await get_notification(notif_id)
    if not doc:
        return False
    existing_cfg = dict((doc.get("config") or {}).get(channel) or {})
    for k in CHANNEL_FIELDS[channel]:
        v = config.get(k)
        if v:  # hanya set field yang diisi (token tidak ter-blank-kan tak sengaja)
            existing_cfg[k] = v.strip() if isinstance(v, str) else v
    result = await _collection().update_one(
        {"notif_id": notif_id},
        {"$set": {f"config.{channel}": existing_cfg, "updated_at": _now()}},
    )
    return result.matched_count > 0


async def delete_notification(notif_id: str) -> bool:
    result = await _collection().delete_one({"notif_id": notif_id})
    if result.deleted_count:
        invalidate_channel_cache()
    return result.deleted_count > 0


# ── Resolusi pengiriman (broadcast union — plan Fix #40) ─────────────────────

async def resolve_channels(
    workspace_id: Optional[str],
    project_id: Optional[str] = None,
    channel: str = "telegram",
) -> List[Dict[str, Any]]:
    """
    Set channel tujuan BROADCAST (Fix #40): UNION
      - channel project-linked (project_ids ∋ project_id)  ∪
      - channel workspace-wide (project_ids kosong)
    enabled saja, dedup by notif_id, urut created_at (deterministik).
    Tanpa project_id → semua channel enabled milik workspace.
    Return dokumen lengkap (config included) untuk dipakai mengirim.
    Fix #54: hasil di-cache TTL 30s per (ws, project, channel); invalidate saat mutasi.
    """
    cache_key = (workspace_id, project_id, channel)
    now = time.monotonic()
    hit = _CHANNEL_CACHE.get(cache_key)
    if hit and now - hit[0] < _CHANNEL_TTL:
        return hit[1]

    if not workspace_id and not project_id:
        _CHANNEL_CACHE[cache_key] = (now, [])
        return []
    try:
        coll = _collection()
        base_q: Dict[str, Any] = {"channel": channel, "enabled": {"$ne": False}}
        if project_id:
            base_q["workspace_id"] = workspace_id
            base_q["$or"] = [
                {"project_ids": project_id},
                {"project_ids": {"$in": [[], None]}},
                {"project_ids": {"$exists": False}},
            ]
        else:
            base_q["workspace_id"] = workspace_id
        docs = await coll.find(base_q).sort("created_at", 1).to_list(100)
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for d in docs:
            nid = d.get("notif_id")
            if not nid or nid in seen:
                continue
            seen.add(nid)
            d["_id"] = str(d["_id"])
            out.append(d)
        _CHANNEL_CACHE[cache_key] = (now, out)
        return out
    except Exception as e:
        logger.warning(f"resolve_channels failed (non-fatal): {e}")
        return []


def extract_telegram_creds(notification: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """Dari dokumen notifikasi → (bot_token, chat_id). None bila bukan telegram/empty."""
    if not notification or notification.get("channel") != "telegram":
        return None, None
    tg = (notification.get("config") or {}).get("telegram") or {}
    return tg.get("bot_token") or None, tg.get("chat_id") or None


async def verify_bot_token(bot_token: str) -> Dict[str, Any]:
    """getMe probe ke Telegram API. Return {ok, bot_id, username, error}."""
    import httpx
    from config.settings import settings as _settings

    if not bot_token:
        return {"ok": False, "error": "bot_token kosong"}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{_settings.telegram_api_base}/bot{bot_token}/getMe")
            data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            result = data.get("result", {})
            return {"ok": True, "bot_id": result.get("id"), "username": result.get("username", "")}
        desc = (data.get("description") or "")[:160]
        return {"ok": False, "error": f"HTTP {resp.status_code}: {desc}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


async def set_project_link(notif_id: str, project_id: str, link: bool) -> bool:
    """Link/unlink channel ↔ project ($addToSet/$pull project_ids)."""
    update = {"$addToSet": {"project_ids": project_id}} if link else {"$pull": {"project_ids": project_id}}
    update["$set"] = {"updated_at": _now()}
    result = await _collection().update_one({"notif_id": notif_id}, update)
    if result.matched_count:
        invalidate_channel_cache()
    return result.matched_count > 0


async def record_health(notif_id: str, ok: bool, username: Optional[str] = None) -> None:
    """Simpan hasil probe getMe: cache bot_username + status health (Fix #40)."""
    sets: Dict[str, Any] = {
        "config.telegram.last_health_check_at": _now().isoformat(),
        "config.telegram.health_status": "ok" if ok else "error",
        "updated_at": _now(),
    }
    if username:
        sets["config.telegram.bot_username"] = username
    try:
        await _collection().update_one({"notif_id": notif_id}, {"$set": sets})
    except Exception as e:
        logger.warning(f"record_health({notif_id}) failed: {e}")


async def list_project_usage(notif_id: str) -> List[Dict[str, Any]]:
    """Daftar project yang memakai channel ini → [{projectId, name}] (untuk warning delete)."""
    from services.mongodb_client import get_db

    doc = await get_notification(notif_id)
    ids = [i for i in ((doc or {}).get("project_ids") or []) if ObjectId.is_valid(i)]
    if not ids:
        return []
    oids = [ObjectId(i) for i in ids]
    projects = await get_db()["projects"].find({"_id": {"$in": oids}}, {"name": 1}).to_list(len(oids))
    return [{"projectId": str(p["_id"]), "name": p.get("name", "?")} for p in projects]

# ── User bell notifications (FE-4) ────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_bell(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "type": doc.get("type", ""),
        "title": doc.get("title", ""),
        "payload": doc.get("payload", {}),
        "readAt": doc.get("readAt"),
        "createdAt": doc.get("createdAt"),
    }


async def create_notification(
    user_id: str, type_: str, title: str, payload: Optional[Dict] = None
) -> Dict[str, Any]:
    """Bell notification ke satu user (FE-4). Insert + push WS `user:{userId}`."""
    doc = {
        "userId": user_id,
        "type": type_,
        "title": title,
        "payload": payload or {},
        "readAt": None,
        "createdAt": _now_iso(),
    }
    db = get_db()
    result = await db[NOTIFICATIONS_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    emit(f"user:{user_id}", {"type": "notification:new", "payload": _public_bell(doc)})
    return doc


async def list_for_user(
    user_id: str, unread_only: bool = False, limit: int = 20
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"userId": user_id}
    if unread_only:
        query["readAt"] = None
    db = get_db()
    cursor = db[NOTIFICATIONS_COLLECTION].find(query).sort("createdAt", -1).limit(limit)
    return [doc async for doc in cursor]


async def unread_count(user_id: str) -> int:
    db = get_db()
    return await db[NOTIFICATIONS_COLLECTION].count_documents({"userId": user_id, "readAt": None})


async def mark_read(user_id: str, ids: Optional[List[str]] = None) -> int:
    """Tandai terbaca. ids kosong/None = semua milik user."""
    query: Dict[str, Any] = {"userId": user_id, "readAt": None}
    if ids:
        query["_id"] = {"$in": [ObjectId(i) for i in ids if ObjectId.is_valid(i)]}
    db = get_db()
    result = await db[NOTIFICATIONS_COLLECTION].update_many(
        query, {"$set": {"readAt": _now_iso()}}
    )
    return result.modified_count


# ── Fix #47: M2M project↔channel (atomik, parity dengan stacks) ─────────────

async def link_project_notification(notif_id: str, project_id: str) -> bool:
    """$addToSet project ke channel — idempotent."""
    result = await _collection().update_one(
        {"notif_id": notif_id}, {"$addToSet": {"project_ids": project_id}}
    )
    if result.matched_count:
        invalidate_channel_cache()
    return result.matched_count > 0


async def unlink_project_notification(notif_id: str, project_id: str) -> bool:
    """$pull project dari channel."""
    result = await _collection().update_one(
        {"notif_id": notif_id}, {"$pull": {"project_ids": project_id}}
    )
    if result.matched_count:
        invalidate_channel_cache()
    return result.matched_count > 0
