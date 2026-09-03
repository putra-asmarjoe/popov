"""
Public Alert Ingest — API publik untuk memicu alert + ticket dari aplikasi eksternal.

POST /api/pub/v1/ingest/alert — aplikasi eksternal yang bermasalah cukup memanggil
endpoint ini; Popov Agent mengeksekusi funnel yang SAMA dengan watchdog/webhook
(triage → simpan alert → auto-ticket → notifikasi Telegram/Email/bell).

Param `dedup`:
  - "auto" (default): Popov menganalisa korelasi — bila ada tiket AKTIF dengan
    konten sama dalam window dedup, alert di-LINK ke tiket itu (1 tiket : N alert);
    bila tidak ada, buat tiket baru.
  - "new": selalu buat tiket BARU (skip link & triage gate).

Auth: API key scope `alerts:write` (pk_pub_*). Rate limit per key.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import Principal, get_current_principal

logger = logging.getLogger(__name__)

router = APIRouter()

_MESSAGES = {
    "en": {
        "workspace_id_required": "workspace_id is required for API key auth",
        "service_required": "service is required",
        "invalid_dedup": "dedup must be 'auto' or 'new'",
        "processed": "Alert ingested — check ticket & notification",
    },
    "id": {
        "workspace_id_required": "workspace_id wajib diisi untuk API key auth",
        "service_required": "service wajib diisi",
        "invalid_dedup": "dedup harus 'auto' atau 'new'",
        "processed": "Alert diterima — cek tiket & notifikasi",
    },
}


def _msg(locale: str, key: str) -> str:
    return _MESSAGES.get(locale, _MESSAGES["en"]).get(key, _MESSAGES["en"][key])


def _get_locale(request: Request) -> str:
    lang = request.headers.get("Accept-Language", "") or request.headers.get("X-Lang", "")
    return "id" if "id" in lang.lower() else "en"


class PublicAlertIngestRequest(BaseModel):
    """Schema for public alert ingest — trigger ticket + notification."""

    service: str = Field(..., min_length=1, max_length=128, description="Service slug yang bermasalah")
    name: str = Field("ExternalAlert", min_length=1, max_length=128, description="Alert name / judul singkat")
    severity: Optional[str] = Field(None, description="critical | warning | info | error (default: warning)")
    description: Optional[str] = Field(None, max_length=8000, description="Detail/deskripsi alert (markdown ok)")
    details: Optional[Dict[str, Any]] = Field(None, description="Metadata tambahan (JSON object)")
    workspace_id: Optional[str] = Field(None, description="Target workspace — wajib utk API key auth")
    dedup: str = Field("auto", description="auto = link ke tiket aktif bila ada korelasi; new = selalu tiket baru")
    source: str = Field("external", min_length=1, max_length=64, description="Label sumber eksternal")
    started_at: Optional[datetime] = Field(None, description="Timestamp mulai (default: sekarang, UTC)")


def _normalize_severity(value: Optional[str]) -> str:
    """Normalisasi severity dari caller eksternal ke skala watchdog (critical/warning/info)."""
    sev = (value or "").lower()
    if sev in ("critical", "critical_alert", "p1", "severe"):
        return "critical"
    if sev in ("info", "informational", "low", "p3"):
        return "info"
    return "warning"  # warning, error, p2, dll → warning


@router.post("/ingest/alert", status_code=201)
async def public_ingest_alert(
    request: Request,
    body: PublicAlertIngestRequest,
    principal: Principal = Depends(get_current_principal),
):
    """
    API publik: pemicu alert + tiket dari aplikasi eksternal.

    Menjalankan funnel yang sama dgn watchdog/webhook (process_service_alerts):
    simpan alert → auto-ticket (dedup auto/new) → notifikasi (Telegram/Email/bell).
    """
    locale = _get_locale(request)

    # Validasi dedup
    dedup = (body.dedup or "auto").strip().lower()
    if dedup not in ("auto", "new"):
        raise HTTPException(status_code=422, detail={"success": False, "message": _msg(locale, "invalid_dedup")})

    # Validasi service
    svc = (body.service or "").strip().lower()
    if not svc:
        raise HTTPException(status_code=422, detail={"success": False, "message": _msg(locale, "service_required")})

    # Workspace binding: API key wajib punya target workspace
    if principal.is_api_key:
        if not body.workspace_id:
            raise HTTPException(status_code=400, detail={"success": False, "message": _msg(locale, "workspace_id_required")})
        workspace_id = body.workspace_id
    else:
        workspace_id = body.workspace_id

    # Bentuk alert dengan struktur normalisasi yang sama dgn observability_client
    alert = {
        "source": (body.source or "external").strip().lower(),
        "name": (body.name or "ExternalAlert").strip(),
        "severity": _normalize_severity(body.severity),
        "service": svc,
        "state": "firing",
        "active_at": (body.started_at or datetime.now(timezone.utc)).isoformat(),
        "description": body.description or "",
    }

    force_new = dedup == "new"

    # Funnel watchdog/webhook — sama persis: alert → tiket → notifikasi
    from services.observability_watchdog import process_service_alerts

    result = await process_service_alerts(
        service=svc,
        alerts=[alert],
        workspace_id=workspace_id,
        observ_id=None,
        force_new=force_new,
        return_details=True,
    )

    # 1C Source Registry (Fix #207): catat source eksternal pengirim signal
    try:
        from services.source_registry_store import record_source_signal
        await record_source_signal(
            workspace_id,
            source_type="alert",
            source_label=alert.get("source") or "external",
            signal_type="alert",
            meta={"service": svc, "name": alert.get("name")},
        )
    except Exception as e:
        logger.warning(f"[SourceRegistry] record alert source failed (non-fatal): {e}")

    return {
        "success": True,
        "message": _msg(locale, "processed"),
        "data": {
            "service": svc,
            "alert_id": result.get("alert_id"),
            "dedup": dedup,
            "skipped": result.get("skipped"),
            "tickets_created": result.get("tickets_created", 0),
            "tickets_new": result.get("ticket_refs", {}).get("new", []),
            "tickets_linked": result.get("ticket_refs", {}).get("linked", []),
            "notifications_sent": result.get("sent", 0),
        },
    }