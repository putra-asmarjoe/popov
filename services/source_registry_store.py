"""
Source Registry Store — 1C roadmap integrasi (Fix #207).

Collection `source_registry` di popovagent_db — mencatat semua source eksternal
yang pernah kirim signal ke workspace (trust: user bisa lihat "dari mana saja
Popov menerima data").

    {
      workspace_id:    str
      source_type:     str   — kategori (mis. "alert" | "deploy")
      source_label:    str   — label user (mis. "sentry", "github_actions", "api")
      signal_count:    int   — total signal diterima
      last_seen_at:    datetime|None
      last_signal_type:str|None
      enabled:         bool  — disable tanpa hapus (1C)
      created_at:      datetime
      last_meta:       dict|None
    }

Record otomatis dipanggil di jalur ingest (deploy-event + ingest/alert).
Pattern mengikuti observability_store/notification_store (registry DB-driven).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

SOURCE_REGISTRY_COLLECTION = "source_registry"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_source_registry_indexes() -> None:
    db = get_db()
    coll = db[SOURCE_REGISTRY_COLLECTION]
    await coll.create_index(
        [("workspace_id", 1), ("source_type", 1), ("source_label", 1)],
        unique=True,
        name="source_registry_ws_type_label",
    )
    await coll.create_index(
        [("workspace_id", 1), ("last_seen_at", -1)],
        name="source_registry_ws_lastseen",
    )


def public_source(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Response shape utk API — tanpa internal field."""
    return {
        "id": str(doc.get("_id")),
        "source_type": doc.get("source_type"),
        "source_label": doc.get("source_label") or "",
        "signal_count": doc.get("signal_count", 0),
        "last_seen_at": doc.get("last_seen_at"),
        "last_signal_type": doc.get("last_signal_type"),
        "enabled": doc.get("enabled", True),
        "created_at": doc.get("created_at"),
    }


async def record_source_signal(
    workspace_id: Optional[str],
    source_type: str,
    source_label: Optional[str] = None,
    signal_type: str = "alert",
    meta: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Upsert registry entry (per workspace+type+label) lalu inc signal_count.
    Graceful: workspace_id kosong / DB error → return None (tidak memblokir funnel)."""
    if not workspace_id:
        return None
    label = (source_label or "").strip()
    try:
        coll = get_db()[SOURCE_REGISTRY_COLLECTION]
        now = _now_utc()
        doc = await coll.find_one_and_update(
            {
                "workspace_id": workspace_id,
                "source_type": source_type,
                "source_label": label,
            },
            {
                "$set": {
                    "last_seen_at": now,
                    "last_signal_type": signal_type,
                    "enabled": True,
                    "last_meta": meta,
                },
                "$inc": {"signal_count": 1},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return public_source(doc)
    except Exception as e:
        logger.warning(f"[SourceRegistry] record failed (non-fatal): {e}")
        return None


async def list_sources(workspace_id: str) -> list:
    coll = get_db()[SOURCE_REGISTRY_COLLECTION]
    cursor = coll.find({"workspace_id": workspace_id}).sort("last_seen_at", -1)
    return [public_source(doc) async for doc in cursor]


async def set_source_enabled(
    workspace_id: str, source_id: str, enabled: bool
) -> Optional[Dict[str, Any]]:
    coll = get_db()[SOURCE_REGISTRY_COLLECTION]
    doc = await coll.find_one_and_update(
        {"_id": _oid(source_id), "workspace_id": workspace_id},
        {"$set": {"enabled": enabled}},
        return_document=ReturnDocument.AFTER,
    )
    return public_source(doc) if doc else None


async def rename_source(
    workspace_id: str, source_id: str, source_label: str
) -> Optional[Dict[str, Any]]:
    coll = get_db()[SOURCE_REGISTRY_COLLECTION]
    doc = await coll.find_one_and_update(
        {"_id": _oid(source_id), "workspace_id": workspace_id},
        {"$set": {"source_label": (source_label or "").strip()}},
        return_document=ReturnDocument.AFTER,
    )
    return public_source(doc) if doc else None


async def delete_source(workspace_id: str, source_id: str) -> bool:
    coll = get_db()[SOURCE_REGISTRY_COLLECTION]
    res = await coll.delete_one({"_id": _oid(source_id), "workspace_id": workspace_id})
    return res.deleted_count > 0


def _oid(source_id: str):
    from bson import ObjectId
    try:
        return ObjectId(source_id)
    except Exception:
        return source_id