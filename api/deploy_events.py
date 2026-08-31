"""
Deploy Event Ingest — Gap 4: fallback deploy detection untuk non-Kubernetes.

CI/CD (GitHub Actions, GitLab CI, manual script) kirim sinyal deploy via
POST /api/pub/v1/deploy-event (API key scope deploy:write). Triage baca
deploy_events sebagai fallback jika Loki tidak tersedia.

Path /api/pub/v1/* = API Key only (konsisten dengan Fix #171 path-based auth).
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import Principal, get_current_principal

logger = logging.getLogger(__name__)

router = APIRouter()


class DeployEventRequest(BaseModel):
    service_name: str = Field(..., min_length=1, max_length=64, description="Service yang di-deploy")
    version: Optional[str] = Field(None, max_length=128, description="Versi/commit/tag")
    deployed_at: Optional[datetime] = Field(None, description="Timestamp deploy (default: sekarang, UTC)")
    project_id: Optional[str] = Field(None, description="Project id (optional)")


_MSG = {
    "en": {"recorded": "Deploy event recorded", "invalid_service": "service_name is required"},
    "id": {"recorded": "Event deploy tercatat", "invalid_service": "service_name wajib diisi"},
}


def _get_locale(request: Request) -> str:
    lang = request.headers.get("Accept-Language", "") or request.headers.get("X-Lang", "")
    return "id" if "id" in lang.lower() else "en"


@router.post("/deploy-event", status_code=201)
async def ingest_deploy_event(
    request: Request,
    body: DeployEventRequest,
    principal: Principal = Depends(get_current_principal),
):
    """Terima sinyal deploy dari CI/CD. Auth: API key scope `deploy:write` (pk_pub_*)."""
    locale = _get_locale(request)
    svc = (body.service_name or "").strip()
    if not svc:
        raise HTTPException(status_code=422, detail={"ok": False, "message": _MSG[locale]["invalid_service"]})

    from services.deploy_event_store import ensure_deploy_indexes, record_deploy_event

    try:
        await ensure_deploy_indexes()
    except Exception as e:
        logger.warning(f"[DeployEvent] ensure indexes failed (non-fatal): {e}")

    # API key principal boleh bawa workspace binding (jika ada) — optional
    workspace_id = getattr(principal, "workspace_id", None)
    source = "api"
    event_id = await record_deploy_event(
        service_name=svc,
        version=body.version,
        deployed_at=body.deployed_at,
        project_id=body.project_id,
        workspace_id=workspace_id,
        source=source,
    )
    if not event_id:
        raise HTTPException(status_code=422, detail={"ok": False, "message": _MSG[locale]["invalid_service"]})

    logger.info(f"[DeployEvent] ingest ok svc={svc} via={source}")
    return {
        "ok": True,
        "event_id": event_id,
        "message": _MSG[locale]["recorded"],
        "service_name": svc.lower(),
        "version": body.version,
    }