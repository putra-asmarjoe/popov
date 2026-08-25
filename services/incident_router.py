"""
Incident router (Fix #40) — SATU sumber kebenaran routing insiden → project.

Menutup business hole: tiket masuk ke project, alert ter-link ke service,
tapi service tidak punya koneksi efektif ke project di jalur insiden.

Urutan resolusi (plan Fix #40):
  1. project_service_refs ⋈ service_library WHERE serviceId == service_name
     (∩ project milik workspace target, urut createdAt)
  2. observability target.project_ids — divalidasi masih ada di workspace
  3. fallback legacy: project pertama workspace (createdAt asc)

Dipakai oleh auto-ticket DAN resolusi channel notifikasi broadcast.
"""
import logging
from typing import Any, Dict, List, Optional

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)


def _norm_service(service_name: Optional[str]) -> str:
    """Normalisasi service_id: lowercase, '-'/'spasi' → '_' (konsisten supervisor)."""
    import re
    return re.sub(r"[-\s]+", "_", (service_name or "").lower().strip())


async def _projects_in_ws(ws_id: Optional[str], query: Dict[str, Any]) -> List[Dict[str, Any]]:
    q = dict(query)
    if ws_id:
        q["workspaceId"] = ws_id
    return [doc async for doc in get_db()["projects"].find(q).sort("createdAt", 1)]


async def resolve_projects_for_incident(
    workspace_id: Optional[str] = None,
    service_name: Optional[str] = None,
    observ_target: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Resolve daftar project tujuan untuk satu insiden (bisa >1 — plan Fix #40).
    Selalu return list (kosong bila benar-benar tidak ada kandidat).
    """
    db = get_db()

    # 1. Service → project links (service library + refs per project)
    norm = _norm_service(service_name)
    if norm:
        try:
            lib_ids = [
                str(doc["_id"])
                async for doc in db["service_library"].find(
                    {"serviceId": {"$in": [norm, norm.replace("_", "-")]}}, {"_id": 1}
                )
            ]
        except Exception as e:
            logger.warning(f"incident_router: lookup service_library gagal: {e}")
            lib_ids = []
        if lib_ids:
            ref_project_ids = [
                r["projectId"]
                async for r in db["project_service_refs"].find(
                    {"libraryServiceId": {"$in": lib_ids}}, {"projectId": 1}
                )
            ]
            if ref_project_ids:
                from bson import ObjectId

                oids = [o for o in (ObjectId(p) for p in ref_project_ids if ObjectId.is_valid(p))]
                projects = await _projects_in_ws(
                    workspace_id, {"_id": {"$in": oids}}
                ) if workspace_id else [
                    doc async for doc in db["projects"].find({"_id": {"$in": oids}}).sort("createdAt", 1)
                ]
                if projects:
                    logger.info(
                        f"incident_router: '{service_name}' → {len(projects)} project "
                        f"(via service link): {[p.get('name') for p in projects]}"
                    )
                    return projects
            else:
                logger.info(f"incident_router: '{service_name}' terdaftar tapi belum ter-link ke project mana pun")

    # 2. Observability target project_ids (validasi masih ada — bisa saja project sudah dihapus)
    if observ_target:
        ids = [str(i) for i in (observ_target.get("project_ids") or [])]
        if ids:
            from bson import ObjectId

            oids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
            if oids:
                projects = (
                    await _projects_in_ws(workspace_id, {"_id": {"$in": oids}})
                    if workspace_id
                    else [doc async for doc in db["projects"].find({"_id": {"$in": oids}}).sort("createdAt", 1)]
                )
                if projects:
                    logger.info(
                        f"incident_router: → {len(projects)} project (via observability target "
                        f"'{observ_target.get('observ_id', '?')}')"
                    )
                    return projects

    # 3. Fallback legacy: project pertama workspace (atau global bila tanpa konteks)
    # HANYA satu project — service tak dikenal jangan membuat tiket di semua project.
    projects = await _projects_in_ws(workspace_id, {})
    if projects:
        logger.info(
            f"incident_router: fallback project pertama"
            f"{f' workspace {workspace_id}' if workspace_id else ' (global)'}: '{projects[0].get('name')}'"
        )
        return [projects[0]]
    return []
