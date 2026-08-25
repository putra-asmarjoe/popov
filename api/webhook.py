"""
Alertmanager Webhook — SCALE_ESCALATION_PLAN Layer 2 (C3/L2-1..L2-8)

Endpoint push alert dari Alertmanager klien (per-tenant):

    POST /api/v1/webhook/alert/{observ_id}
    Header: X-Alertmanager-Token: <token per-tenant>

Payload yang diterima = format webhook Alertmanager standar:
    { "status": "firing"|"resolved", "alerts": [ {labels, annotations, startsAt, ...} ] }

Alur: validasi token per-tenant → parse & normalisasi → dedup composite fingerprint
(MD5 workspace+observ+alertname+service, window 30m) → triage silent → format →
auto-ticket → kirim Telegram. Resolved alerts TIDAK memicu pipeline RCA
(auto-resolve tiket = follow-up; dicatat di log).

Latency target <5 detik dari alert firing di klien.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from services.observability_client import _extract_service  # reuse label priority
from services.observability_store import get_target, record_health_status
from services.observability_watchdog import process_service_alerts, run_triage_silent
from services.mongodb_client import get_db
from services.webhook_validator import validate_alertmanager_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

DEDUP_WINDOW_MINUTES = 30


def _parse_dt(value) -> Optional[str]:
    """Normalisasi timestamp Alertmanager (ISO8601) → string ringkas."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except Exception:
        return str(value)


def normalize_alertmanager_payload(payload: dict) -> Dict[str, Any]:
    """
    Parse payload webhook Alertmanager → {status, alerts:[...]} dengan bentuk internal
    seragam ala observability_client._normalize_alert (source="alertmanager").
    """
    status = payload.get("status") or "firing"
    alerts_out: List[Dict[str, Any]] = []
    for raw in payload.get("alerts") or []:
        labels = raw.get("labels") or {}
        annotations = raw.get("annotations") or {}
        alerts_out.append({
            "source": "alertmanager",
            "name": labels.get("alertname", "UnknownAlert"),
            "severity": labels.get("severity", "warning"),
            "service": _extract_service(labels),
            "state": raw.get("status") or status,
            "active_at": _parse_dt(raw.get("startsAt")),
            "description": annotations.get("description") or annotations.get("summary") or "",
            "labels": labels,
        })
    return {"status": status, "alerts": alerts_out}


def composite_fingerprint(
    workspace_id: Optional[str],
    observ_id: str,
    alerts: List[Dict[str, Any]],
) -> str:
    """MD5(workspace + observ + alertname/severity/service unik grup) — dedup antar sumber."""
    canonical = "|".join(sorted(
        f"{a.get('name')}:{a.get('severity')}:{a.get('service')}" for a in alerts
    ))
    raw = f"{workspace_id or 'global'}|{observ_id}|{canonical}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


async def _recent_duplicate(fingerprint: str, minutes: int = DEDUP_WINDOW_MINUTES) -> bool:
    """True bila fingerprint sama sudah diproses dalam window terakhir."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    doc = await get_db()["watchdog_alerts"].find_one(
        {"fingerprint": fingerprint, "sent_at": {"$gte": since.isoformat()}},
        {"alert_id": 1},
    )
    return doc is not None


@router.post("/alert/{observ_id}")
async def receive_alert(
    observ_id: str,
    request: Request,
    x_alertmanager_token: Optional[str] = Header(default=None),
):
    # 404 vs 401 dibedakan agar admin tahu URL salah vs token salah
    target = await get_target(observ_id)
    if not target or not target.get("enabled", True):
        raise HTTPException(status_code=404, detail="unknown observability target")

    valid_target = await validate_alertmanager_token(observ_id, x_alertmanager_token)
    if valid_target is None:
        raise HTTPException(status_code=401, detail="invalid webhook token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON payload")

    parsed = normalize_alertmanager_payload(payload)

    # send_resolved (L2-7): alert resolved TIDAK memicu pipeline RCA.
    # Auto-resolve tiket = follow-up; di sini cukup catat status stack sehat.
    if parsed["status"] == "resolved":
        await record_health_status(observ_id, "resolved_notification")
        logger.info(f"[Webhook] resolved notification for {observ_id} (no RCA)")
        return {"status": "accepted", "action": "resolved_acknowledged"}

    firing = [a for a in parsed["alerts"] if a.get("state") != "resolved"]
    if not firing:
        return {"status": "accepted", "action": "nothing_to_process"}

    workspace_id = target.get("workspace_id")
    observ = target.get("observ_id")
    fingerprint = composite_fingerprint(workspace_id, observ, firing)
    if await _recent_duplicate(fingerprint):
        logger.info(f"[Webhook] duplicate fingerprint for {observ} within {DEDUP_WINDOW_MINUTES}m — skip")
        return {"status": "accepted", "action": "duplicate_skipped"}

    # group per service lalu proses tiap grup (triage → format → ticket → telegram)
    grouped: Dict[str, List[dict]] = {}
    for a in firing:
        grouped.setdefault(a.get("service") or "unknown", []).append(a)

    sent_total = 0
    for svc, alerts in grouped.items():
        sent_total += await process_service_alerts(
            service=svc,
            alerts=alerts,
            workspace_id=workspace_id,
            observ_id=observ,
            fingerprint=fingerprint,
        )

    await record_health_status(observ, "webhook_ok")
    return {
        "status": "accepted",
        "services": list(grouped.keys()),
        "alerts": len(firing),
        "notified": sent_total,
    }
