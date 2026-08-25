"""
Config router — FE-6 Management Panel (ADMIN ONLY).
Kelola service yang dipantau, API key LLM (write-only), dan konfigurasi observability.
Semua penulisan file bersifat atomic; nilai RAHASIA tidak pernah dikembalikan.
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user, require_admin
from config.settings import settings
from services.config_manager import patch_env
from services.doc_loader import reload_docs
from services.workspace_store import find_workspace_by_id, get_membership, is_workspace_admin  # Fix #39

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/config", tags=["config"])

SERVICE_ID_RE = re.compile(r"^[a-z0-9_\-]{2,64}$")


# ── Services (Fix #45: MURNI DB via agent_docs, bukan JSON legacy) ────────────

class ServiceUpsertRequest(BaseModel):
    service_id: Optional[str] = None  # None untuk PATCH (pakai path)
    collection: Optional[str] = None  # → meta.collections.primary
    body: Optional[str] = None        # markdown body grounding
    # DB connection (type/uri/db/error_filter) DIHAPUS dari sini — pindah ke
    # /services/library (service_store dbConfig). Field dibiarkan utk kompat
    # automation, tapi diabaikan (no-op).
    type: Optional[str] = None
    uri: Optional[str] = None
    db: Optional[str] = None
    error_filter: Optional[dict] = None


async def _merged_services() -> list:
    from services.agent_docs_store import list_docs
    docs = await list_docs("services")
    out = []
    for d in docs:
        meta = d.get("meta") or {}
        sid = meta.get("id") or d.get("key")
        if not sid:
            continue
        col = (meta.get("collections") or {}).get("primary") or f"logs_{sid}"
        out.append({
            "service_id": sid,
            "collection": col,
            "has_doc": True,
            "body_len": len(d.get("body") or ""),
            "updatedAt": d.get("updatedAt"),
        })
    return sorted(out, key=lambda x: x["service_id"])


async def _upsert_service_doc(sid: str, collection: str, body: Optional[str]) -> None:
    from services.agent_docs_store import get_doc, upsert_doc
    existing = await get_doc("services", sid)
    meta = dict(existing.get("meta") or {}) if existing else {}
    meta["id"] = sid
    meta["collections"] = {**dict(meta.get("collections") or {}), "primary": collection}
    current_body = (existing or {}).get("body") or ""
    new_body = body if body is not None else current_body
    if not new_body.strip():
        new_body = f"## Deskripsi\n\nService {sid} — kelola grounding doc ini via UI/API."
    await upsert_doc("services", sid, meta, new_body)


@router.get("/services")
async def list_services(admin: dict = Depends(require_admin)):
    return {"services": await _merged_services()}


@router.post("/services", status_code=201)
async def create_service(body: ServiceUpsertRequest, admin: dict = Depends(require_admin)):
    if not body.service_id or not SERVICE_ID_RE.match(body.service_id):
        raise HTTPException(422, "service_id: huruf kecil/angka/underscore, 2-64 karakter")
    collection = body.collection or f"logs_{body.service_id}"
    if not re.match(r"^[A-Za-z0-9_\-]{2,64}$", collection):
        raise HTTPException(422, "Nama collection tidak valid")
    await _upsert_service_doc(body.service_id, collection, body.body)
    await reload_docs()
    return {"services": await _merged_services()}


@router.patch("/services/{service_id}")
async def update_service(service_id: str, body: ServiceUpsertRequest, admin: dict = Depends(require_admin)):
    from services.agent_docs_store import get_doc
    existing = await get_doc("services", service_id)
    if existing is None:
        raise HTTPException(404, "Service tidak terdaftar")
    meta = dict(existing.get("meta") or {})
    collection = (body.collection
                  or (meta.get("collections") or {}).get("primary")
                  or f"logs_{service_id}")
    if body.collection is not None and not re.match(r"^[A-Za-z0-9_\-]{2,64}$", body.collection):
        raise HTTPException(422, "Nama collection tidak valid")
    await _upsert_service_doc(service_id, collection, body.body)
    await reload_docs()
    return {"services": await _merged_services()}


@router.delete("/services/{service_id}")
async def delete_service(service_id: str, admin: dict = Depends(require_admin)):
    from services.agent_docs_store import delete_doc
    removed = await delete_doc("services", service_id)
    if not removed:
        raise HTTPException(404, "Service tidak terdaftar")
    await reload_docs()
    return {"services": await _merged_services()}


# ── LLM (BYOK — Fix #54: config MURNI DB, key terenkripsi) ────────────────────

LLM_PROVIDERS = ("openai", "openrouter", "google", "opencode")


class LlmUpdateRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None        # model utk provider AKTIF (backward compat)
    models: Optional[dict] = None      # Fix #56: model PER provider {provider: model}
    baseUrls: Optional[dict] = None       # {provider: url} — default prefilled, bisa diedit
    apiKey: Optional[dict] = None          # {provider: key} — kosong = pertahankan lama
    embedding: Optional[dict] = None       # {mode: local|provider, provider?, model?}


class LlmTestRequest(BaseModel):
    provider: str
    model: str
    baseUrl: str = ""
    apiKey: str = ""


class LlmTestEmbeddingRequest(BaseModel):
    provider: str
    model: str
    baseUrl: str = ""
    apiKey: str = ""


def _validate_base_url(value: str, label: str) -> str:
    value = (value or "").strip().rstrip("/")
    if value and not re.match(r"^https?://[^\s]+$", value):
        raise HTTPException(422, f"{label} harus URL http(s)")
    return value


@router.get("/llm")
async def llm_config(admin: dict = Depends(require_admin)):
    from services.llm_config_store import public_config
    return await public_config()


@router.put("/llm")
async def update_llm(body: LlmUpdateRequest, admin: dict = Depends(require_admin)):
    from services.llm_config_store import public_config, set_llm_config
    if body.provider is not None and body.provider not in LLM_PROVIDERS:
        raise HTTPException(422, f"Provider harus salah satu dari {LLM_PROVIDERS}")
    if body.model is not None and not re.match(r"^[\w.\-/:]{2,100}$", body.model):
        raise HTTPException(422, "Nama model tidak valid")

    # Fix #56: model per provider — validasi tiap key
    per_provider_models = {}
    if body.models:
        for p, m in (body.models or {}).items():
            if p not in LLM_PROVIDERS:
                raise HTTPException(422, f"Provider model tidak dikenal: {p}")
            mv = (m or "").strip()
            if mv and not re.match(r"^[\w.\-/:]{2,100}$", mv):
                raise HTTPException(422, f"Nama model {p} tidak valid")
            if mv:
                per_provider_models[p] = mv

    base_urls = {}
    if body.baseUrls:
        for p, v in (body.baseUrls or {}).items():
            if p not in LLM_PROVIDERS:
                raise HTTPException(422, f"Provider base_url tidak dikenal: {p}")
            url = _validate_base_url(v or "", f"base URL {p}")
            if url:
                base_urls[p] = url

    keys = {}
    if body.apiKey:
        for p, v in (body.apiKey or {}).items():
            if p not in LLM_PROVIDERS:
                raise HTTPException(422, f"Provider key tidak dikenal: {p}")
            vv = (v or "").strip()
            if vv and len(vv) < 20:
                raise HTTPException(422, f"API key {p} terlalu pendek")
            if vv:
                keys[p] = vv

    emb = body.embedding
    if emb:
        mode = (emb.get("mode") or "").lower()
        if mode not in ("local", "provider"):
            raise HTTPException(422, "embedding.mode harus local atau provider")
        if mode == "provider":
            ep = (emb.get("provider") or "").lower()
            if ep not in LLM_PROVIDERS:
                raise HTTPException(422, f"embedding provider harus salah satu dari {LLM_PROVIDERS}")
            if not (emb.get("model") or "").strip():
                raise HTTPException(422, "model embedding wajib diisi saat mode provider")
        else:
            emb = {"mode": "local"}

    if not (body.provider or body.model or per_provider_models or base_urls or keys or emb):
        raise HTTPException(422, "Tidak ada perubahan")

    existing = await public_config()
    final_provider = body.provider or existing["provider"]
    # Fix #56: model hanya di-set bila user KIRIM eksplisit — jangan clobber model per-provider
    final_model = body.model
    final_embedding = emb or existing.get("embedding") or {"mode": "local"}
    await set_llm_config(
        final_provider, final_model, base_urls, keys, final_embedding,
        models=per_provider_models or None,
    )

    # Refresh cache factory → berlaku LANGSUNG (tanpa restart)
    from services.llm_config_store import get_llm_config
    from services.llm_factory import set_llm_config_cache
    set_llm_config_cache(await get_llm_config())
    return await public_config()


@router.post("/llm/test")
async def test_llm_conn(body: LlmTestRequest, admin: dict = Depends(require_admin)):
    """Test koneksi LLM dgn value form (belum tentu disimpan) — {ok, latency_ms, error}."""
    from services.llm_config_store import test_llm_connection
    if body.provider not in LLM_PROVIDERS:
        raise HTTPException(422, f"Provider harus salah satu dari {LLM_PROVIDERS}")
    if not (body.model or "").strip():
        raise HTTPException(422, "model wajib diisi")
    return await test_llm_connection(body.provider, body.model, body.baseUrl, body.apiKey)


@router.post("/llm/test-embedding")
async def test_llm_embedding(body: LlmTestEmbeddingRequest, admin: dict = Depends(require_admin)):
    """Test koneksi embedding dgn value form — {ok, dim, latency_ms, error}."""
    from services.llm_config_store import test_embedding_connection
    if body.provider not in LLM_PROVIDERS:
        raise HTTPException(422, f"Provider harus salah satu dari {LLM_PROVIDERS}")
    if not (body.model or "").strip():
        raise HTTPException(422, "model embedding wajib diisi")
    return await test_embedding_connection(body.provider, body.model, body.baseUrl, body.apiKey)


# ── Observability ──────────────────────────────────────────────────────────────

class ObservabilityUpdateRequest(BaseModel):
    # Fix #45: URL stack (prometheus/alertmanager/tempo/loki) DIHAPUS dari sini —
    # sumber kebenaran stack = DB observability_targets (via UI), bukan env.
    watchdog_interval_min: Optional[int] = None
    observability_enabled: Optional[bool] = None


@router.get("/observability")
async def observability_config(admin: dict = Depends(require_admin)):
    # Fix #45: stack URLs tidak lagi dari env — tampilkan master switch system saja.
    return {
        "watchdog_interval_min": settings.observability_interval_min,
        "observability_enabled": settings.observability_enabled,
    }


@router.put("/observability")
async def update_observability(body: ObservabilityUpdateRequest, admin: dict = Depends(require_admin)):
    updates = {}
    if body.watchdog_interval_min is not None:
        if not 1 <= body.watchdog_interval_min <= 1440:
            raise HTTPException(422, "Interval watchdog 1-1440 menit")
        updates["OBSERVABILITY_INTERVAL_MIN"] = str(body.watchdog_interval_min)
    if body.observability_enabled is not None:
        updates["OBSERVABILITY_ENABLED"] = "true" if body.observability_enabled else "false"
    if not updates:
        raise HTTPException(422, "Tidak ada perubahan")
    patch_env(updates)
    # Balik nilai BARU dari body (settings.* masih nilai lama sampai restart) — Fix FE-6
    return {
        "watchdog_interval_min": (
            body.watchdog_interval_min
            if body.watchdog_interval_min is not None
            else settings.observability_interval_min
        ),
        "observability_enabled": (
            body.observability_enabled
            if body.observability_enabled is not None
            else settings.observability_enabled
        ),
        "restart_required": True,
    }


# ── Fix #35: Observability Targets (multi-stack + webhook per-tenant) ────────

class ObservabilityTargetUpsert(BaseModel):
    name: str
    kind: Optional[str] = None          # Fix #45: prometheus/tempo/alertmanager/loki
    workspace_id: Optional[str] = None
    project_ids: list[str] = []
    alertmanager_url: str = ""
    prometheus_url: str = ""
    tempo_url: str = ""
    loki_url: Optional[str] = None
    webhook_mode: bool = False
    poll_interval_seconds: int = 300


def _public_url() -> str:
    """Base URL publik untuk snippet webhook."""
    import os
    return os.environ.get("POPOV_PUBLIC_URL", "http://localhost:8000").rstrip("/")


@router.get("/observability-targets")
async def list_observability_targets(admin: dict = Depends(require_admin)):
    from services.observability_store import list_targets
    return {"targets": await list_targets(enabled_only=False)}


@router.post("/observability-targets", status_code=201)
async def create_observability_target(body: ObservabilityTargetUpsert, admin: dict = Depends(require_admin)):
    from services.observability_store import build_alertmanager_snippet, create_target
    result = await create_target(
        name=body.name,
        workspace_id=body.workspace_id,
        project_ids=body.project_ids,
        alertmanager_url=body.alertmanager_url,
        prometheus_url=body.prometheus_url,
        tempo_url=body.tempo_url,
        loki_url=body.loki_url or None,
        webhook_mode=body.webhook_mode,
        poll_interval_seconds=body.poll_interval_seconds,
        kind=body.kind,
    )
    snippet = build_alertmanager_snippet(_public_url(), result["target"]["observ_id"], result["webhook_token"])
    return {**result, "alertmanager_snippet": snippet}


class ObservabilityTargetPatchRequest(BaseModel):
    """Fix #46: PATCH partial-safe — hanya field yang DIKIRIM yang diubah."""
    name: Optional[str] = None
    kind: Optional[str] = None
    workspace_id: Optional[str] = None
    project_ids: Optional[list[str]] = None
    alertmanager_url: Optional[str] = None
    prometheus_url: Optional[str] = None
    tempo_url: Optional[str] = None
    loki_url: Optional[str] = None
    webhook_mode: Optional[bool] = None
    poll_interval_seconds: Optional[int] = None


@router.patch("/observability-targets/{observ_id}")
async def update_observability_target(observ_id: str, body: ObservabilityTargetPatchRequest, admin: dict = Depends(require_admin)):
    """Partial-safe PATCH (Fix #46): hanya field yang dikirim yang berubah."""
    from services.observability_store import update_target
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(422, "Tidak ada perubahan")
    ok = await update_target(observ_id, payload)
    if not ok:
        raise HTTPException(404, "target tidak ditemukan")
    return {"ok": True}


@router.delete("/observability-targets/{observ_id}")
async def delete_observability_target(observ_id: str, admin: dict = Depends(require_admin)):
    from services.observability_store import delete_target
    if not await delete_target(observ_id):
        raise HTTPException(404, "target tidak ditemukan")
    return {"ok": True}


@router.post("/observability-targets/{observ_id}/rotate-token")
async def rotate_target_token(observ_id: str, admin: dict = Depends(require_admin)):
    from services.observability_store import build_alertmanager_snippet, get_target, rotate_webhook_token
    target = await get_target(observ_id)
    if not target:
        raise HTTPException(404, "target tidak ditemukan")
    token = await rotate_webhook_token(observ_id)
    if not token:
        raise HTTPException(404, "target tidak ditemukan")
    return {
        "webhook_token": token,
        "alertmanager_snippet": build_alertmanager_snippet(_public_url(), observ_id, token),
    }


@router.post("/observability-targets/{observ_id}/test-connection")
async def test_target_connection(observ_id: str, admin: dict = Depends(require_admin)):
    from services.observability_store import get_target, test_connection
    target = await get_target(observ_id)
    if not target:
        raise HTTPException(404, "target tidak ditemukan")
    return await test_connection(target)


# ── Fix #37: Notification Targets (multi-channel per workspace/project) ──────

class NotificationCreate(BaseModel):
    name: str
    channel: str = "telegram"          # saat ini hanya "telegram" (wa/slack/discord roadmap)
    workspace_id: Optional[str] = None
    project_ids: list[str] = []
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


class NotificationUpdate(BaseModel):
    name: Optional[str] = None
    workspace_id: Optional[str] = None
    project_ids: Optional[list[str]] = None
    enabled: Optional[bool] = None
    chat_id: Optional[str] = None      # partial; token kosong = biarkan lama


@router.get("/notification-targets")
async def list_notification_targets(workspace_id: Optional[str] = None, admin: dict = Depends(require_admin)):
    from services.notification_store import list_notifications
    return {"notifications": await list_notifications(workspace_id=workspace_id, enabled_only=False)}


@router.post("/notification-targets", status_code=201)
async def create_notification_target(body: NotificationCreate, admin: dict = Depends(require_admin)):
    from services.notification_store import create_notification
    try:
        doc = await create_notification(
            name=body.name,
            channel=body.channel,
            workspace_id=body.workspace_id,
            project_ids=body.project_ids,
            config={"telegram": {"bot_token": body.bot_token or "", "chat_id": body.chat_id or ""}}
            if body.channel == "telegram" else None,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"notification": doc}


@router.patch("/notification-targets/{notif_id}")
async def update_notification_target(notif_id: str, body: NotificationUpdate, admin: dict = Depends(require_admin)):
    from services.notification_store import update_notification, update_notification_config
    patch = {k: v for k, v in {
        "name": body.name,
        "workspace_id": body.workspace_id,
        "project_ids": body.project_ids,
        "enabled": body.enabled,
    }.items() if v is not None}
    ok = True
    if patch:
        ok = await update_notification(notif_id, patch) and ok
    cfg = {k: v for k, v in {"chat_id": body.chat_id}.items() if v is not None}
    if cfg:
        ok = await update_notification_config(notif_id, "telegram", cfg) and ok
    if not ok:
        raise HTTPException(404, "notifikasi tidak ditemukan")
    return {"ok": True}


@router.delete("/notification-targets/{notif_id}")
async def delete_notification_target(notif_id: str, admin: dict = Depends(require_admin)):
    from services.notification_store import delete_notification
    if not await delete_notification(notif_id):
        raise HTTPException(404, "notifikasi tidak ditemukan")
    return {"ok": True}


@router.post("/notification-targets/{notif_id}/test-connection")
async def test_notification_connection(notif_id: str, admin: dict = Depends(require_admin)):
    """Probe Telegram getMe dengan token tersimpan (tanpa mengirim pesan)."""
    import httpx
    from services.notification_store import get_notification, mask_bot_token
    doc = await get_notification(notif_id)
    if not doc:
        raise HTTPException(404, "notifikasi tidak ditemukan")
    token = ((doc.get("config") or {}).get("telegram") or {}).get("bot_token")
    if not token:
        raise HTTPException(422, "bot_token belum diset")
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        data = resp.json() if resp.status_code == 200 else {}
        if data.get("ok"):
            return {"status": "ok", "bot_username": f"@{data['result'].get('username')}", "masked_token": mask_bot_token(token)}
        return {"status": f"http_{resp.status_code}"}
    except Exception as e:
        return {"status": f"error:{type(e).__name__}"}


# ── Fix #41: Workspace Service Registry (migrasi ⚙️ Monitoring Global) ───────

class RegistryUpsert(BaseModel):
    service_id: str
    label: Optional[str] = None
    db_type: Optional[str] = "mongodb"      # mongodb | mysql
    db_uri: Optional[str] = None
    db_name: Optional[str] = None
    db_collection: Optional[str] = None


class RegistryPatch(BaseModel):
    label: Optional[str] = None
    db_type: Optional[str] = None
    db_uri: Optional[str] = None
    db_name: Optional[str] = None
    db_collection: Optional[str] = None
    enabled: Optional[bool] = None


async def _ws_or_404(ws_id: str):
    ws = await find_workspace_by_id(ws_id)
    if not ws:
        raise HTTPException(404, "workspace tidak ditemukan")
    return ws


@router.get("/workspaces/{ws_id}/service-registry")
async def list_ws_registry(ws_id: str, current_user: dict = Depends(get_current_user)):
    """List registry milik workspace — member workspace boleh lihat."""
    from services.workspace_service_registry import list_for_workspace

    ws = await find_workspace_by_id(ws_id)
    if not ws:
        raise HTTPException(404, "workspace tidak ditemukan")
    uid = str(current_user["_id"])
    if current_user.get("role") != "admin" and get_membership(ws, uid) is None:
        raise HTTPException(403, "Bukan member workspace ini")
    return {"items": await list_for_workspace(ws_id)}


@router.post("/workspaces/{ws_id}/service-registry", status_code=201)
async def create_ws_registry(
    ws_id: str,
    body: RegistryUpsert,
    current_user: dict = Depends(get_current_user),
):
    ws = await _ws_or_404(ws_id)
    uid = str(current_user["_id"])
    if current_user.get("role") != "admin" and not is_workspace_admin(ws, uid):
        raise HTTPException(403, "Hanya workspace admin")
    from services.workspace_service_registry import create_item
    try:
        doc = await create_item(
            workspace_id=ws_id,
            service_id=body.service_id,
            label=body.label or "",
            db_config={
                "type": body.db_type or "mongodb",
                "uri": body.db_uri or "",
                "db": body.db_name or "",
                **({"collection": body.db_collection} if body.db_collection else {}),
            } if body.db_uri and body.db_name else None,
            created_by=uid,  # FE-8.7: auto-mirror ke library pribadi pembuat
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"item": doc}


@router.patch("/workspaces/{ws_id}/service-registry/{registry_id}")
async def update_ws_registry(
    ws_id: str,
    registry_id: str,
    body: RegistryPatch,
    current_user: dict = Depends(get_current_user),
):
    ws = await _ws_or_404(ws_id)
    uid = str(current_user["_id"])
    if current_user.get("role") != "admin" and not is_workspace_admin(ws, uid):
        raise HTTPException(403, "Hanya workspace admin")
    from services.workspace_service_registry import update_item
    patch: dict = {}
    if body.label is not None:
        patch["label"] = body.label
    if body.enabled is not None:
        patch["enabled"] = body.enabled
    db_fields = [body.db_type, body.db_uri, body.db_name, body.db_collection]
    if any(f is not None for f in db_fields):
        patch["db_config"] = {
            "type": body.db_type or "mongodb",
            "uri": body.db_uri or "",
            "db": body.db_name or "",
            **({"collection": body.db_collection} if body.db_collection else {}),
        }
    ok = await update_item(registry_id, patch)
    if not ok:
        raise HTTPException(404, "registry tidak ditemukan / tidak ada perubahan")
    return {"ok": True}


@router.delete("/workspaces/{ws_id}/service-registry/{registry_id}")
async def delete_ws_registry(
    ws_id: str,
    registry_id: str,
    current_user: dict = Depends(get_current_user),
):
    ws = await _ws_or_404(ws_id)
    uid = str(current_user["_id"])
    if current_user.get("role") != "admin" and not is_workspace_admin(ws, uid):
        raise HTTPException(403, "Hanya workspace admin")
    from services.workspace_service_registry import delete_item
    if not await delete_item(registry_id):
        raise HTTPException(404, "registry tidak ditemukan")
    return {"ok": True}


@router.post("/workspaces/{ws_id}/service-registry/{registry_id}/test-connection")
async def test_ws_registry_connection(
    ws_id: str,
    registry_id: str,
    current_user: dict = Depends(get_current_user),
):
    ws = await _ws_or_404(ws_id)
    uid = str(current_user["_id"])
    if current_user.get("role") != "admin" and not is_workspace_admin(ws, uid):
        raise HTTPException(403, "Hanya workspace admin")
    from services.workspace_service_registry import get_item, test_connection
    item = await get_item(registry_id)
    if not item or item.get("workspace_id") != ws_id:
        raise HTTPException(404, "registry tidak ditemukan")
    return await test_connection(item)


# ── Fix #45: M2M project↔stack (typed, atomik) ───────────────────────────────

class LinkProjectRequest(BaseModel):
    project_id: str


@router.post("/observability-targets/{observ_id}/link-project")
async def link_stack_project(observ_id: str, body: LinkProjectRequest, admin: dict = Depends(require_admin)):
    """Link project ke stack (auto-replace bila kind sama sudah ter-link di project itu)."""
    from services.observability_store import get_target, link_project
    target = await get_target(observ_id)
    if not target:
        raise HTTPException(404, "stack tidak ditemukan")
    # auth: global admin ATAU ws-admin workspace pemilik stack
    if admin.get("role") != "admin" and target.get("workspace_id"):
        from services.workspace_store import find_workspace_by_id, is_workspace_admin
        ws = await find_workspace_by_id(target["workspace_id"])
        if not ws or not is_workspace_admin(ws, str(admin["_id"])):
            raise HTTPException(403, "Hanya workspace admin")
    try:
        return await link_project(observ_id, body.project_id)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/observability-targets/{observ_id}/unlink-project")
async def unlink_stack_project(observ_id: str, body: LinkProjectRequest, admin: dict = Depends(require_admin)):
    from services.observability_store import get_target, unlink_project
    target = await get_target(observ_id)
    if not target:
        raise HTTPException(404, "stack tidak ditemukan")
    if admin.get("role") != "admin" and target.get("workspace_id"):
        from services.workspace_store import find_workspace_by_id, is_workspace_admin
        ws = await find_workspace_by_id(target["workspace_id"])
        if not ws or not is_workspace_admin(ws, str(admin["_id"])):
            raise HTTPException(403, "Hanya workspace admin")
    ok = await unlink_project(observ_id, body.project_id)
    return {"ok": ok}


# ── Fix #47: M2M project↔notification (atomik, parity stacks) ────────────────

@router.post("/notification-targets/{notif_id}/link-project")
async def link_notification_project(notif_id: str, body: LinkProjectRequest, admin: dict = Depends(require_admin)):
    from services.notification_store import get_notification, link_project_notification
    doc = await get_notification(notif_id)
    if not doc:
        raise HTTPException(404, "notifikasi tidak ditemukan")
    if admin.get("role") != "admin" and doc.get("workspace_id"):
        from services.workspace_store import find_workspace_by_id, is_workspace_admin
        ws = await find_workspace_by_id(doc["workspace_id"])
        if not ws or not is_workspace_admin(ws, str(admin["_id"])):
            raise HTTPException(403, "Hanya workspace admin")
    ok = await link_project_notification(notif_id, body.project_id)
    return {"ok": ok}


@router.post("/notification-targets/{notif_id}/unlink-project")
async def unlink_notification_project(notif_id: str, body: LinkProjectRequest, admin: dict = Depends(require_admin)):
    from services.notification_store import get_notification, unlink_project_notification
    doc = await get_notification(notif_id)
    if not doc:
        raise HTTPException(404, "notifikasi tidak ditemukan")
    if admin.get("role") != "admin" and doc.get("workspace_id"):
        from services.workspace_store import find_workspace_by_id, is_workspace_admin
        ws = await find_workspace_by_id(doc["workspace_id"])
        if not ws or not is_workspace_admin(ws, str(admin["_id"])):
            raise HTTPException(403, "Hanya workspace admin")
    ok = await unlink_project_notification(notif_id, body.project_id)
    return {"ok": ok}
