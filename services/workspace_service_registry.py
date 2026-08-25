"""
Workspace Service Registry — migrasi "⚙️ Monitoring Global" ke level workspace (Fix #41).

Collection `workspace_service_registry` (popovagent_db):
    {
      registry_id:   "wsr-<8hex>" unique
      workspace_id:  str           — pemilik; unique bersama service_id
      service_id:    str lowercase — bebas dibuat (analogi deployment K8s)
      label:         str
      db_config:     {type mongodb|mysql, uri, db, collection} | None
                     = koneksi log transaksi (RAG) milik service ini
      enabled:       bool
      created_at / updated_at
    }

Resolusi chain backend (urutan):
    1. global JSON eksplisit  (`service_db_configs.json`)      ← legacy fallback
    2. registry(workspace_id)                                 ← BARU (lapis ini)
    3. library dbConfig (service_store, Fix #38)
    4. default (.env + logs_<svc>)

Wewenang edit: ws-admin workspace terkait ATAU global admin (B3).
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

WS_SERVICE_REGISTRY_COLLECTION = "workspace_service_registry"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_registry_id() -> str:
    return f"wsr-{secrets.token_hex(4)}"


def _collection():
    return get_db()[WS_SERVICE_REGISTRY_COLLECTION]


def validate_service_id(service_id: str) -> str:
    sid = (service_id or "").strip().lower()
    if not sid or len(sid) > 64 or not all(c.isalnum() or c in "_-" for c in sid):
        raise ValueError("service_id tidak valid (huruf kecil/angka/-/_, maks 64)")
    return sid


def _validate_db_config(db_config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Sama pola dengan service_store._validate_db_config (Fix #38)."""
    if not db_config:
        return None
    allowed = {k: v for k, v in (db_config or {}).items() if k in ("type", "uri", "db", "collection") and v}
    if not allowed:
        return None
    t = (allowed.get("type") or "mongodb").lower()
    if t not in ("mongodb", "mysql"):
        raise ValueError("db_config.type harus mongodb atau mysql")
    allowed["type"] = t
    if len(allowed) < 3:
        raise ValueError("db_config butuh minimal type, uri, dan db/collection")
    return allowed


def mask_uri(uri: Optional[str]) -> Optional[str]:
    """Sembunyikan kredensial di URI sebelum keluar API."""
    if not uri:
        return None
    try:
        from services.config_manager import mask_uri as _mask
        return _mask(uri)
    except Exception:
        import re
        return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", uri)


async def ensure_registry_indexes() -> None:
    try:
        coll = _collection()
        await coll.create_index(
            [("workspace_id", 1), ("service_id", 1)], unique=True
        )
        await coll.create_index("registry_id", unique=True)
        logger.info(f"Indexes ensured on '{WS_SERVICE_REGISTRY_COLLECTION}'")
    except Exception as e:
        logger.warning(f"Failed to ensure {WS_SERVICE_REGISTRY_COLLECTION} indexes: {e}")


def _public(doc: dict) -> dict:
    d = dict(doc)
    d["_id"] = str(d["_id"])
    raw = d.pop("db_config", None) or None
    if raw:
        d["db_config"] = {**raw, "uri": mask_uri(raw.get("uri"))}
    return d


async def get_item(registry_id: str) -> Optional[dict]:
    doc = await _collection().find_one({"registry_id": registry_id})
    if not doc:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


async def list_for_workspace(workspace_id: str, enabled_only: bool = False) -> List[dict]:
    q: Dict[str, Any] = {"workspace_id": workspace_id}
    if enabled_only:
        q["enabled"] = {"$ne": False}
    docs = await _collection().find(q).sort("created_at", 1).to_list(500)
    out = []
    for d in docs:
        d["_id"] = str(d["_id"])
        out.append(_public(d))
    return out


async def create_item(
    workspace_id: str,
    service_id: str,
    label: str = "",
    db_config: Optional[Dict[str, Any]] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    sid = validate_service_id(service_id)
    validated_db = _validate_db_config(db_config)
    doc = {
        "registry_id": generate_registry_id(),
        "workspace_id": workspace_id,
        "service_id": sid,
        "label": (label or "").strip(),
        "db_config": validated_db,
        "enabled": True,
        "created_at": _now(),
        "updated_at": _now(),
    }
    try:
        await _collection().insert_one(doc)
    except Exception as e:
        if "E11000" in str(e) or "duplicate" in str(e).lower():
            raise ValueError(f"Service '{sid}' sudah terdaftar di workspace ini")
        raise
    doc["_id"] = str(doc["_id"])
    logger.info(f"[WsRegistry] created {doc['registry_id']} ws={workspace_id} svc={sid}")

    # FE-8.7: auto-mirror ke library pribadi pembuat — supaya service langsung muncul
    # di Management Library Saya & picker Projects tanpa langkah manual.
    # Gagal mirror = non-fatal (registry tetap jalan untuk routing/RAG).
    if created_by:
        try:
            from services.service_store import create_item as _mirror_to_library
            await _mirror_to_library(created_by, sid, (label or "").strip())
            logger.info(f"[WsRegistry] mirrored to library '{sid}' owner={created_by}")
        except ValueError as e:
            logger.info(f"[WsRegistry] library mirror skipped: {e}")
        except Exception as e:
            logger.warning(f"[WsRegistry] library mirror failed (non-fatal): {e}")

    return _public(doc)


async def update_item(registry_id: str, patch: Dict[str, Any]) -> bool:
    set_fields: Dict[str, Any] = {"updated_at": _now()}
    if patch.get("label") is not None:
        set_fields["label"] = str(patch["label"]).strip()
    if patch.get("enabled") is not None:
        set_fields["enabled"] = bool(patch["enabled"])
    if "db_config" in patch:
        validated = _validate_db_config(patch.get("db_config"))
        set_fields["db_config"] = validated  # None = hapus koneksi
    if len(set_fields) <= 1:
        return False
    result = await _collection().update_one({"registry_id": registry_id}, {"$set": set_fields})
    return result.matched_count > 0


async def delete_item(registry_id: str) -> bool:
    result = await _collection().delete_one({"registry_id": registry_id})
    return result.deleted_count > 0


async def get_by_service(workspace_id: str, service_id: str) -> Optional[dict]:
    """Lookup untuk resolusi chain (B2): ws + service_id, enabled."""
    try:
        sid = (service_id or "").strip().lower()
        if not workspace_id or not sid:
            return None
        doc = await _collection().find_one({
            "workspace_id": workspace_id,
            "service_id": sid,
            "enabled": {"$ne": False},
        })
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        return doc
    except Exception as e:
        logger.warning(f"get_by_service failed (non-fatal): {e}")
        return None


async def resolve_registry_for_state(
    workspace_id: Optional[str],
    project_id: Optional[str] = None,
) -> List[dict]:
    """
    Daftar service registry milik workspace state (Fase D pattern).
    project_id saat ini tidak mempersempit (registry berlaku ws-level);
    parameter disiapkan untuk future per-project override.
    Return list kosong bila tanpa konteks / gagal.
    """
    if not workspace_id:
        return []
    try:
        return await list_for_workspace(workspace_id, enabled_only=True)
    except Exception as e:
        logger.warning(f"resolve_registry_for_state failed (non-fatal): {e}")
        return []


async def test_connection(item: dict, timeout_s: float = 4.0) -> Dict[str, Any]:
    """Probe DB koneksi milik item registry (mongodb/mysql)."""
    import httpx

    cfg = item.get("db_config") or {}
    uri = cfg.get("uri")
    db_type = (cfg.get("type") or "mongodb").lower()
    if not uri:
        return {"overall": "not_configured", "sources": {}}
    try:
        if db_type == "mongodb":
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=int(timeout_s * 1000))
            try:
                await client.admin.command("ping")
                status = "ok"
            except Exception as e:
                status = f"error:{type(e).__name__}"
            finally:
                client.close()
        else:
            # MySQL: probe TCP host/port dari URI mysql://host:port
            from urllib.parse import urlparse
            parsed = urlparse(uri if "//" in uri else f"//{uri}")
            host, port = parsed.hostname or "localhost", parsed.port or 3306
            import socket
            with socket.create_connection((host, port), timeout=timeout_s):
                pass
            status = "ok"
        return {"overall": status, "db_type": db_type}
    except Exception as e:
        return {"overall": f"error:{type(e).__name__}", "db_type": db_type}