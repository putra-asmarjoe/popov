"""
Ingest Router — Public API endpoints for external integrations.

POST   /ingest/knowledge         — Insert knowledge (knowledge:write)
GET    /ingest/knowledge/{id}    — Read knowledge item (knowledge:read)
PATCH  /ingest/knowledge/{id}    — Update knowledge item (knowledge:write)

Requires API key (pk_pub_*).
Rate limited per key.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.deps import Principal, get_current_principal
from services import knowledge_store
from services.knowledge_embed import fire_and_forget_embed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


# ── i18n Messages ────────────────────────────────────────────────────────────

MESSAGES = {
    "en": {
        "workspace_id_required": "workspace_id is required for API key auth",
        "content_too_long": "Content too long ({actual} chars). Maximum: {max_chars} chars.",
        "create_failed": "Failed to create knowledge item",
        "created": "Knowledge '{name}' has been added successfully",
        "not_found": "Knowledge item not found",
        "access_denied": "Access denied — item belongs to different workspace",
        "read_failed": "Failed to read knowledge item",
        "update_failed": "Failed to update knowledge item",
        "updated": "Knowledge '{name}' has been updated successfully",
        "no_fields": "No fields to update",
        "already_exists": "Knowledge '{name}' already exists in this folder",
        "knowledge_injected": "Knowledge '{name}' has been injected into service {service}",
        "knowledge_updated": "Knowledge '{name}' has been updated in service {service}",
        "service_not_found": "Service '{service}' not found. Create it first in Management or via service_library.",
    },
    "id": {
        "workspace_id_required": "workspace_id wajib diisi untuk API key auth",
        "content_too_long": "Content terlalu panjang ({actual} char). Maksimal: {max_chars} char.",
        "create_failed": "Gagal membuat knowledge item",
        "created": "Knowledge '{name}' berhasil ditambahkan",
        "not_found": "Knowledge item tidak ditemukan",
        "access_denied": "Akses ditolak — item milik workspace lain",
        "read_failed": "Gagal membaca knowledge item",
        "update_failed": "Gagal update knowledge item",
        "updated": "Knowledge '{name}' berhasil diupdate",
        "no_fields": "Tidak ada field yang diupdate",
        "already_exists": "Knowledge '{name}' sudah ada di folder ini",
        "knowledge_injected": "Knowledge '{name}' telah ditanam ke service {service}",
        "knowledge_updated": "Knowledge '{name}' telah diupdate di service {service}",
        "service_not_found": "Service '{service}' tidak ditemukan. Buat terlebih dahulu di Management atau via service_library.",
    },
}


def _msg(locale: str, key: str, **kwargs) -> str:
    """Return localized message based on locale (default: en)."""
    lang = MESSAGES.get(locale, MESSAGES["en"])
    return lang.get(key, MESSAGES["en"].get(key, key)).format(**kwargs)


def _get_locale(request: Request, principal: Principal) -> str:
    """Get locale from request header or default to 'en'."""
    # Check Accept-Language header
    accept_lang = request.headers.get("accept-language", "")
    if accept_lang.startswith("id"):
        return "id"
    return "en"


# ── Request Schema ───────────────────────────────────────────────────────────

class KnowledgeIngestRequest(BaseModel):
    """Schema for knowledge ingest endpoint."""
    name: str                          # "kuponku_core_api"
    folder: str = "general"            # "services" | "general" | custom
    content: str                       # markdown content
    workspace_id: Optional[str] = None  # required for API key auth
    meta: Optional[Dict[str, Any]] = None  # Fix #170: structured metadata


class KnowledgeUpdateRequest(BaseModel):
    """Schema for knowledge update endpoint."""
    name: Optional[str] = None
    folder: Optional[str] = None
    content: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class PublicServiceKnowledgeRequest(BaseModel):
    """Schema for public service knowledge injection endpoint."""
    name: str
    folder: str = "general"
    service: str
    workspace_id: str
    content: str
    meta: Optional[Dict[str, Any]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _check_ownership(item_id: str, principal: Principal) -> dict:
    """Check item exists and belongs to this workspace. Returns item."""
    item = await knowledge_store.get_item(item_id)
    if item is None:
        return None
    # API key: item owner must be system:<same workspace>
    if principal.is_api_key:
        expected_owner = f"system:{principal.workspace_id}"
        if item.get("ownerId") != expected_owner:
            return "denied"
    return item


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/knowledge")
async def ingest_knowledge(
    request: Request,
    body: KnowledgeIngestRequest,
    principal: Principal = Depends(get_current_principal),
):
    """
    Ingest knowledge from external systems.

    Auth:
        - API key (pk_pub_*) → requires workspace_id in body, assigned to system owner
        - JWT → uses current user, workspace_id optional

    Rate limit: 200 req/hour (default for public keys)

    Request body:
        - name: Knowledge document name
        - folder: Category (services, general, etc.)
        - content: Markdown content
        - workspace_id: Required for API key auth
        - meta: Optional structured metadata (Fix #170)

    Response:
        - success: true/false
        - message: Localized message
        - data: Knowledge item data (on success)
    """
    locale = _get_locale(request, principal)

    # Determine owner and workspace
    if principal.is_api_key:
        # API key auth — workspace_id required
        if not body.workspace_id:
            raise HTTPException(
                status_code=400,
                detail={"success": False, "message": _msg(locale, "workspace_id_required")}
            )
        owner_id = f"system:{principal.workspace_id}"
        workspace_id = body.workspace_id
    else:
        # JWT auth
        owner_id = str(principal.user["_id"])
        workspace_id = body.workspace_id

    # Validate content length
    from config.settings import settings
    from services.llm_config_store import get_embedding_cfg
    emb_cfg = await get_embedding_cfg()
    max_chars = (emb_cfg.get("max_chars") if emb_cfg else None) or settings.embedding_max_chars
    if len(body.content) > max_chars:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "message": _msg(locale, "content_too_long", actual=len(body.content), max_chars=max_chars)}
        )

    # Create knowledge item
    try:
        item = await knowledge_store.create_item(
            owner_id=owner_id,
            name=body.name,
            folder=body.folder,
            content=body.content,
            meta=body.meta,
            max_chars=max_chars,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"success": False, "message": str(e)})
    except Exception as e:
        from pymongo.errors import DuplicateKeyError
        if isinstance(e, DuplicateKeyError):
            raise HTTPException(
                status_code=409,
                detail={"success": False, "message": _msg(locale, "already_exists", name=body.name)}
            )
        logger.error(f"[Ingest] Failed to create knowledge item: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "message": _msg(locale, "create_failed")})

    # Fire-and-forget embedding
    embedded = False
    try:
        fire_and_forget_embed(
            content=body.content,
            collection="knowledge_library",
            doc_filter={"_id": item["_id"]}
        )
        embedded = True
    except Exception as e:
        logger.warning(f"[Ingest] Embedding scheduling failed: {e}")

    # Link to workspace if workspace_id provided
    if workspace_id:
        try:
            from services import knowledge_store as ks
            await ks.add_ref(
                ws_id=workspace_id,
                library_id=str(item["_id"]),
                user_id=owner_id,
            )
        except Exception as e:
            logger.warning(f"[Ingest] Workspace linking failed: {e}")

    item_id = str(item["_id"])
    logger.info(
        f"[Ingest] Knowledge created: {body.name} "
        f"(id={item_id}, type={principal.type}, embedded={embedded})"
    )

    return {
        "success": True,
        "message": _msg(locale, "created", name=body.name),
        "data": {
            "id": item_id,
            "name": body.name,
            "folder": body.folder,
            "embedded": embedded,
        }
    }


@router.get("/knowledge/{item_id}")
async def get_knowledge(
    request: Request,
    item_id: str,
    principal: Principal = Depends(get_current_principal),
):
    """
    Read knowledge item by ID.

    Auth:
        - API key (pk_pub_*) → only items from same workspace
        - JWT → owner only

    Rate limit: 200 req/hour (default for public keys)
    """
    locale = _get_locale(request, principal)

    result = await _check_ownership(item_id, principal)
    if result is None:
        raise HTTPException(status_code=404, detail={"success": False, "message": _msg(locale, "not_found")})
    if result == "denied":
        raise HTTPException(status_code=403, detail={"success": False, "message": _msg(locale, "access_denied")})

    item = result
    logger.info(f"[Ingest] Knowledge read: {item.get('name')} (id={item_id}, type={principal.type})")

    return {
        "success": True,
        "data": knowledge_store._public_item(item, include_content=True),
    }


@router.patch("/knowledge/{item_id}")
async def update_knowledge(
    request: Request,
    item_id: str,
    body: KnowledgeUpdateRequest,
    principal: Principal = Depends(get_current_principal),
):
    """
    Update knowledge item by ID.

    Auth:
        - API key (pk_pub_*) → only items from same workspace
        - JWT → owner only

    Rate limit: 200 req/hour (default for public keys)
    """
    locale = _get_locale(request, principal)

    result = await _check_ownership(item_id, principal)
    if result is None:
        raise HTTPException(status_code=404, detail={"success": False, "message": _msg(locale, "not_found")})
    if result == "denied":
        raise HTTPException(status_code=403, detail={"success": False, "message": _msg(locale, "access_denied")})

    # Build updates dict (only non-None fields)
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.folder is not None:
        updates["folder"] = body.folder
    if body.content is not None:
        updates["content"] = body.content
    if body.meta is not None:
        updates["meta"] = body.meta

    if not updates:
        raise HTTPException(status_code=400, detail={"success": False, "message": _msg(locale, "no_fields")})

    # Validate content length if content is being updated
    if "content" in updates:
        from config.settings import settings
        from services.llm_config_store import get_embedding_cfg
        emb_cfg = await get_embedding_cfg()
        max_chars = (emb_cfg.get("max_chars") if emb_cfg else None) or settings.embedding_max_chars
        if len(updates["content"]) > max_chars:
            raise HTTPException(
                status_code=400,
                detail={"success": False, "message": _msg(locale, "content_too_long", actual=len(updates["content"]), max_chars=max_chars)}
            )

    # Update item
    owner_id = result.get("ownerId", "")
    try:
        updated = await knowledge_store.update_item(item_id, owner_id, updates, max_chars=max_chars)
    except Exception as e:
        logger.error(f"[Ingest] Failed to update knowledge item: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "message": _msg(locale, "update_failed")})

    if updated is None:
        raise HTTPException(status_code=404, detail={"success": False, "message": _msg(locale, "not_found")})

    # Re-embed if content changed
    if "content" in updates:
        try:
            fire_and_forget_embed(
                content=updates["content"],
                collection="knowledge_library",
                doc_filter={"_id": updated["_id"]}
            )
        except Exception as e:
            logger.warning(f"[Ingest] Re-embedding failed: {e}")

    logger.info(f"[Ingest] Knowledge updated: {updated.get('name')} (id={item_id}, type={principal.type})")

    return {
        "success": True,
        "message": _msg(locale, "updated", name=updated.get("name", "")),
        "data": knowledge_store._public_item(updated, include_content=True),
    }


@router.post("/knowledge/service", status_code=201)
async def public_inject_service_knowledge(
    request: Request,
    body: PublicServiceKnowledgeRequest,
    principal: Principal = Depends(get_current_principal),
):
    """
    Public API: Inject knowledge directly into service knowledge base.

    Auth:
        - pk_pub_* → requires workspace_id, service name, knowledge:write scope
        - Rate limited: 200 req/hour

    Creates knowledge item and links it to the specified service.
    """
    locale = _get_locale(request, principal)

    # Determine owner and workspace_id
    if principal.is_api_key:
        if not body.workspace_id:
            raise HTTPException(
                status_code=400,
                detail={"success": False, "message": _msg(locale, "workspace_id_required")}
            )
        owner_id = f"system:{principal.workspace_id}"
        workspace_id = body.workspace_id
    else:
        owner_id = str(principal.user["_id"])
        workspace_id = body.workspace_id

    # 1. Find service in service_library (flexible hyphen/underscore lookup)
    from services import service_store, mongodb_client
    db = mongodb_client.get_db()
    service_slug = body.service.strip().lower()
    alt_slugs = list({service_slug, service_slug.replace("-", "_"), service_slug.replace("_", "-")})

    svc = await db[service_store.LIBRARY_COLLECTION].find_one({"serviceId": {"$in": alt_slugs}})

    if svc is None:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "message": _msg(locale, "service_not_found", service=body.service)}
        )

    service_lib_id = str(svc["_id"])

    # Auto-register service in workspace_service_registry if workspace_id is provided (matching UI behavior)
    if workspace_id:
        try:
            from services import workspace_service_registry as wsr
            reg = await wsr.get_by_service(workspace_id, service_slug)
            if not reg and ("-" in service_slug or "_" in service_slug):
                reg = await wsr.get_by_service(workspace_id, service_slug.replace("-", "_")) or \
                      await wsr.get_by_service(workspace_id, service_slug.replace("_", "-"))
            if not reg:
                await wsr.create_item(
                    workspace_id=workspace_id,
                    service_id=service_slug,
                    label=body.service,
                )
                logger.info(f"[Ingest] Service '{service_slug}' auto-registered in workspace_service_registry for ws={workspace_id}")
        except ValueError:
            pass  # Already registered
        except Exception as e:
            logger.warning(f"[Ingest] Auto-registering service in workspace_service_registry skipped: {e}")

    # 2. Validate content length
    from config.settings import settings
    from services.llm_config_store import get_embedding_cfg
    emb_cfg = await get_embedding_cfg()
    max_chars = (emb_cfg.get("max_chars") if emb_cfg else None) or settings.embedding_max_chars
    if len(body.content) > max_chars:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "message": _msg(locale, "content_too_long", actual=len(body.content), max_chars=max_chars)},
        )

    # 3. Upsert: check existing by name+folder+owner, update or create
    from services import knowledge_store as ks
    from services.knowledge_store import LIBRARY_COLLECTION
    slug_name = ks.slugify_name(body.name)
    existing = await db[LIBRARY_COLLECTION].find_one({
        "ownerId": owner_id, "name": slug_name, "folder": body.folder,
    })

    embedded = False
    action = "created"

    if existing:
        # UPDATE flow — update content/meta, skip link
        updates = {}
        if body.content is not None:
            updates["content"] = body.content
        if body.meta is not None:
            updates["meta"] = body.meta
        if body.folder is not None:
            updates["folder"] = body.folder
        if not updates:
            raise HTTPException(status_code=400, detail={"success": False, "message": _msg(locale, "no_fields")})
        try:
            updated = await ks.update_item(
                str(existing["_id"]), owner_id, updates, max_chars=max_chars,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail={"success": False, "message": str(e)})
        except Exception as e:
            logger.error(f"[Ingest] Failed to update service knowledge: {e}")
            raise HTTPException(status_code=500, detail={"success": False, "message": _msg(locale, "update_failed")})
        if updated is None:
            raise HTTPException(status_code=404, detail={"success": False, "message": _msg(locale, "not_found")})
        item = updated
        action = "updated"
        logger.info(f"[Ingest] Service knowledge updated: {body.name} -> {body.service} (id={existing['_id']})")
    else:
        # CREATE flow — create item + link to service
        try:
            item = await knowledge_store.create_item(
                owner_id=owner_id,
                name=body.name,
                folder=body.folder,
                content=body.content,
                meta=body.meta,
                max_chars=max_chars,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail={"success": False, "message": str(e)})
        except Exception as e:
            from pymongo.errors import DuplicateKeyError
            if isinstance(e, DuplicateKeyError):
                raise HTTPException(
                    status_code=409,
                    detail={"success": False, "message": _msg(locale, "already_exists", name=body.name)}
                )
            logger.error(f"[Ingest] Failed to create knowledge item: {e}")
            raise HTTPException(status_code=500, detail={"success": False, "message": _msg(locale, "create_failed")})
        knowledge_item_id = str(item["_id"])
        try:
            await service_store.link_knowledge(service_lib_id, knowledge_item_id, owner_id)
        except Exception as e:
            logger.warning(f"[Ingest] Service-knowledge linking note: {e}")
        logger.info(f"[Ingest] Service knowledge created: {body.name} -> {body.service} (id={knowledge_item_id})")

    knowledge_item_id = str(item["_id"])

    # 4. Fire-and-forget embedding (both create and update)
    try:
        fire_and_forget_embed(
            content=body.content,
            collection="knowledge_library",
            doc_filter={"_id": item["_id"]}
        )
        embedded = True
    except Exception as e:
        logger.warning(f"[Ingest] Embedding scheduling failed: {e}")

    msg_key = "knowledge_updated" if action == "updated" else "knowledge_injected"
    logger.info(
        f"[Ingest] Service knowledge {action}: {body.name} -> {body.service} "
        f"(id={knowledge_item_id}, embedded={embedded})"
    )

    return {
        "success": True,
        "message": _msg(locale, msg_key, name=body.name, service=body.service),
        "data": {
            "id": knowledge_item_id,
            "name": body.name,
            "folder": body.folder,
            "serviceId": service_lib_id,
            "workspace_id": workspace_id,
            "embedded": embedded,
            "linked": True,
            "action": action,
        },
    }
