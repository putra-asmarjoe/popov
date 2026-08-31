"""
Deploy Event Store — Gap 4: fallback deploy detection untuk non-Kubernetes.

Collection: deploy_events (TTL 2 jam, auto-cleanup).
CI/CD kirim sinyal deploy via POST /api/v1/deploy-event → Triage baca ini
sebagai fallback jika Loki tidak tersedia/terkonfigurasi.

Normalisasi service_name hyphen/underscore (pola Fix #161) — konsisten dengan
query service_library lain.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from config.settings import settings
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

DEPLOY_EVENTS_COLLECTION = "deploy_events"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_deploy_indexes() -> None:
    """TTL index expires_at (auto-cleanup) + (service_name, deployed_at) untuk lookup cepat."""
    db = get_db()
    coll = db[DEPLOY_EVENTS_COLLECTION]
    await coll.create_index(
        [("expires_at", 1)],
        expireAfterSeconds=0,
        name="deploy_events_ttl",
    )
    await coll.create_index(
        [("service_name", 1), ("deployed_at", -1)],
        name="deploy_events_svc_time",
    )


def _service_variants(service: str) -> list:
    """Semua varian nama service untuk query (hyphen ↔ underscore)."""
    s = (service or "").strip().lower()
    return list({
        s,
        s.replace("-", "_"),
        s.replace("_", "-"),
    })


async def record_deploy_event(
    service_name: str,
    version: Optional[str] = None,
    deployed_at: Optional[datetime] = None,
    project_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    source: str = "api",
) -> Optional[str]:
    """Simpan sinyal deploy. Return event_id (None jika service_name kosong)."""
    svc = (service_name or "").strip()
    if not svc:
        logger.warning("[DeployEvent] record skipped — service_name kosong")
        return None
    deployed = deployed_at or _now_utc()
    ttl_hours = getattr(settings, "deploy_event_ttl_hours", 2)
    expires = deployed + timedelta(hours=ttl_hours)
    doc = {
        "service_name": svc.lower(),
        "version": (version or "").strip() or None,
        "deployed_at": deployed,
        "project_id": project_id,
        "workspace_id": workspace_id,
        "source": source,
        "created_at": _now_utc(),
        "expires_at": expires,
    }
    db = get_db()
    result = await db[DEPLOY_EVENTS_COLLECTION].insert_one(doc)
    event_id = str(result.inserted_id)
    logger.info(f"[DeployEvent] recorded svc={svc} version={doc['version']} event={event_id}")
    return event_id


async def check_deploy_recent(
    service: str,
    minutes: int = 60,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Cek ada deploy dalam `minutes` terakhir. Return (detected, info{version, deployed_at, source})."""
    svc = (service or "").strip().lower()
    if not svc:
        return False, None
    db = get_db()
    coll = db[DEPLOY_EVENTS_COLLECTION]
    window_start = _now_utc() - timedelta(minutes=minutes)
    doc = await coll.find_one(
        {
            "service_name": {"$in": _service_variants(svc)},
            "deployed_at": {"$gte": window_start},
        },
        sort=[("deployed_at", -1)],
    )
    if not doc:
        return False, None
    info = {
        "version": doc.get("version"),
        "deployed_at": doc.get("deployed_at"),
        "source": doc.get("source", "api"),
        "event_id": str(doc.get("_id")),
    }
    logger.info(f"[DeployEvent] recent deploy found svc={svc} minutes={minutes} source={info['source']}")
    return True, info


async def purge_old_events() -> int:
    """One-time cleanup (backup kalau TTL index belum dibuat). Hapus expired."""
    db = get_db()
    result = await db[DEPLOY_EVENTS_COLLECTION].delete_many(
        {"expires_at": {"$lte": _now_utc()}}
    )
    return result.deleted_count