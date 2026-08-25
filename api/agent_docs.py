"""
Agent Docs API — kelola grounding docs (services/playbooks/schemas/connections/observability)
langsung di DB (collection agent_docs), editable via UI. Admin only.

Menggantikan edit manual file docs/*.md. Perubahan langsung di-refresh cache
doc_loader (reload) sehingga agent memakai data terbaru tanpa restart.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_admin
from services.agent_docs_store import (
    CATEGORIES,
    delete_doc,
    get_doc,
    list_docs,
    update_doc,
    upsert_doc,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/docs/agent-docs", tags=["agent-docs"])


@router.get("")
async def list_agent_docs(category: Optional[str] = None, admin: dict = Depends(require_admin)):
    if category and category not in CATEGORIES:
        raise HTTPException(422, f"category harus salah satu dari {CATEGORIES}")
    docs = await list_docs(category)
    # ringkas: tanpa body besar
    out = []
    for d in docs:
        out.append({
            "category": d.get("category"),
            "key": d.get("key"),
            "body_len": len((d.get("body") or "")),
            "updatedAt": d.get("updatedAt"),
            "meta": d.get("meta"),
        })
    return {"total": len(out), "docs": out}


@router.get("/{category}/{key}")
async def get_agent_doc(category: str, key: str, admin: dict = Depends(require_admin)):
    _check_category(category)
    doc = await get_doc(category, key)
    if doc is None:
        raise HTTPException(404, "Dokumen tidak ditemukan")
    return doc


@router.post("", status_code=201)
async def create_agent_doc(body: dict, admin: dict = Depends(require_admin)):
    category = (body.get("category") or "").strip()
    key = (body.get("key") or "").strip()
    _check_category(category)
    if not key:
        raise HTTPException(422, "key wajib")
    doc = await upsert_doc(
        category, key, body.get("meta") or {}, body.get("body") or ""
    )
    await _reload()
    return doc


@router.patch("/{category}/{key}")
async def patch_agent_doc(category: str, key: str, body: dict, admin: dict = Depends(require_admin)):
    _check_category(category)
    updates = {k: body[k] for k in ("meta", "body") if k in body and body[k] is not None}
    if not updates:
        raise HTTPException(422, "tidak ada field yang diupdate (meta/body)")
    doc = await update_doc(category, key, updates)
    if doc is None:
        raise HTTPException(404, "Dokumen tidak ditemukan")
    await _reload()
    return doc


@router.delete("/{category}/{key}")
async def remove_agent_doc(category: str, key: str, admin: dict = Depends(require_admin)):
    _check_category(category)
    ok = await delete_doc(category, key)
    if not ok:
        raise HTTPException(404, "Dokumen tidak ditemukan")
    await _reload()
    return {"deleted": f"{category}/{key}"}


@router.post("/reload")
async def reload_agent_docs(admin: dict = Depends(require_admin)):
    await _reload()
    from services.doc_loader import docs_source
    return {"status": "reloaded", "source": await docs_source()}


def _check_category(category: str) -> None:
    if category not in CATEGORIES:
        raise HTTPException(422, f"category harus salah satu dari {CATEGORIES}")


async def _reload() -> None:
    from services.doc_loader import reload_docs
    await reload_docs()
