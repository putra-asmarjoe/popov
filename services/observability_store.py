"""
Observability Store — SCALE_ESCALATION_PLAN Layer 2 / fondasi MULTI_OBS (C1)

Collection `observability_targets` di popovagent_db:
    {
      observ_id:            str unik (mis. "obs-a1b2c3")
      name:                 str
      workspace_id:         str|None      — tenant pemilik stack
      project_ids:          [str]         — project yang terhubung (auto-ticket)
      alertmanager_url:     str           — dipakai watchdog polling (pull mode)
      prometheus_url:       str
      tempo_url:            str
      webhook_mode:         bool          — true = alert via push, polling hanya health-check
      webhook_secret_hash:  str|null      — sha256 hex dari token per-tenant (bukan plaintext)
      poll_interval_seconds:int (default 300)
      enabled:              bool
      health_status:        str|None      — hasil health-check scheduler terakhir
      last_health_check_at: datetime|None
    }

Backward compat: collection kosong → scheduler pakai target legacy dari .env.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

# Fix #54: cache resolusi stack per (workspace, project) — agent (metrics/trace/triage)
# TIDAK buka DB per call. TTL 30s + invalidate saat mutasi target/link.
_OBS_CFG_CACHE: Dict[Tuple[Optional[str], Optional[str]], Tuple[float, List[dict]]] = {}
_OBS_CFG_TTL = 30.0


def invalidate_obs_cfg_cache() -> None:
    """Panggil setelah mutasi target (create/update/delete/rotate/link/unlink)."""
    global _OBS_CFG_CACHE
    _OBS_CFG_CACHE.clear()

# Typed stacks (Fix #45): satu stack mewakili SATU jenis sumber.
# "otel" reserved (central log span_logs masih global via APP_LOGS_DB_URI).
TARGET_KINDS = ["prometheus", "tempo", "alertmanager", "loki"]
KIND_URL_FIELD = {
    "prometheus": "prometheus_url",
    "tempo": "tempo_url",
    "alertmanager": "alertmanager_url",
    "loki": "loki_url",
}

OBSERVABILITY_TARGETS_COLLECTION = "observability_targets"

# Path readiness probe per jenis sumber (D7) — dipakai test_connection & probe_single
PROBE_PATHS = {
    "prometheus": "/-/ready",
    "tempo": "/ready",
    "alertmanager": "/-/ready",
    "loki": "/ready",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_observ_id() -> str:
    """ID pendek unik untuk URL webhook: obs-<8hex>."""
    return f"obs-{secrets.token_hex(4)}"


def hash_token(token: str) -> str:
    """Hash token webhook (sha256 hex). Plaintext TIDAK disimpan (L2-2)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _collection():
    db = get_db()
    return db[OBSERVABILITY_TARGETS_COLLECTION]


def new_webhook_token() -> str:
    """Generate token per-tenant untuk header X-Alertmanager-Token."""
    return secrets.token_urlsafe(32)


async def ensure_target_indexes() -> None:
    try:
        coll = _collection()
        await coll.create_index("observ_id", unique=True)
        await coll.create_index([("workspace_id", 1)])
        logger.info(f"Indexes ensured on '{OBSERVABILITY_TARGETS_COLLECTION}'")
    except Exception as e:
        logger.warning(f"Failed to ensure {OBSERVABILITY_TARGETS_COLLECTION} indexes: {e}")


async def get_target(observ_id: str) -> Optional[dict]:
    try:
        doc = await _collection().find_one({"observ_id": observ_id})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        return doc
    except Exception as e:
        logger.error(f"get_target({observ_id}) failed: {e}")
        return None


async def list_targets(workspace_id: Optional[str] = None, enabled_only: bool = True) -> List[dict]:
    q: Dict[str, Any] = {}
    if workspace_id:
        q["workspace_id"] = workspace_id
    if enabled_only:
        q["enabled"] = {"$ne": False}
    docs = await _collection().find(q).to_list(500)
    for d in docs:
        d["_id"] = str(d["_id"])
        # jangan bocorkan hash ke client
        d.pop("webhook_secret_hash", None)
    return docs


async def create_target(
    name: str,
    workspace_id: Optional[str] = None,
    project_ids: Optional[list] = None,
    alertmanager_url: str = "",
    prometheus_url: str = "",
    tempo_url: str = "",
    loki_url: str = "",
    webhook_mode: bool = False,
    poll_interval_seconds: int = 300,
    token: Optional[str] = None,
    kind: Optional[str] = None,
) -> dict:
    """kind (Fix #45): tipe stack — prometheus/tempo/alertmanager/loki.
    Wajib di UI baru; None ditoleransi untuk data legacy (resolusi skip kind kosong)."""
    if kind is not None and kind not in TARGET_KINDS:
        raise ValueError(f"kind '{kind}' tidak valid (opsi: {TARGET_KINDS})")
    """
    Buat target baru. Return {target, webhook_token} — token plaintext HANYA
    sekali ini dikembalikan (untuk ditampilkan/copy di UI), DB simpan hash.
    """
    coll = _collection()
    token = token or new_webhook_token()
    doc = {
        "observ_id": generate_observ_id(),
        "name": name,
        "workspace_id": workspace_id,
        "project_ids": project_ids or [],
        "alertmanager_url": alertmanager_url,
        "prometheus_url": prometheus_url,
        "tempo_url": tempo_url,
        "loki_url": loki_url,
        "kind": kind,
        "webhook_mode": bool(webhook_mode),
        "webhook_secret_hash": hash_token(token),
        "poll_interval_seconds": max(int(poll_interval_seconds), 60),
        "enabled": True,
        "health_status": None,
        "last_health_check_at": None,
        "created_at": _now(),
    }
    await coll.insert_one(doc)
    doc["_id"] = str(doc["_id"])
    logger.info(f"[ObservStore] created target {doc['observ_id']} ws={workspace_id} webhook_mode={webhook_mode}")
    return {"target": _strip_secret(doc), "webhook_token": token}


async def update_target(observ_id: str, patch: Dict[str, Any]) -> bool:
    """Update field aman (partial-safe, Fix #46):
    - hanya key yang diizinkan & BUKAN None yang di-$set (None = tidak dikirim)
    - kind divalidasi terhadap TARGET_KINDS
    webhook_secret hanya via rotate_webhook_token()."""
    allowed = {
        "name", "kind", "workspace_id", "project_ids",
        "alertmanager_url", "prometheus_url", "tempo_url", "loki_url",
        "webhook_mode", "poll_interval_seconds", "enabled",
    }
    clean = {
        k: v for k, v in patch.items()
        if k in allowed and v is not None
    }
    if "kind" in patch:
        if patch["kind"] is None:
            clean.pop("kind", None)  # jangan menimpa kind dengan null
        elif patch["kind"] not in TARGET_KINDS:
            raise ValueError(f"kind '{patch['kind']}' tidak valid")
        else:
            clean["kind"] = patch["kind"]
    if not clean:
        return False
    clean["updated_at"] = _now()
    result = await _collection().update_one({"observ_id": observ_id}, {"$set": clean})
    return result.matched_count > 0


async def delete_target(observ_id: str) -> bool:
    result = await _collection().delete_one({"observ_id": observ_id})
    if result.deleted_count:
        invalidate_obs_cfg_cache()
    return result.deleted_count > 0


async def rotate_webhook_token(observ_id: str) -> Optional[str]:
    """Rotate token per-tenant. Return plaintext token baru (sekali tampil)."""
    token = new_webhook_token()
    result = await _collection().update_one(
        {"observ_id": observ_id},
        {"$set": {"webhook_secret_hash": hash_token(token), "token_rotated_at": _now()}},
    )
    if result.matched_count == 0:
        return None
    invalidate_obs_cfg_cache()
    return token


async def verify_webhook_token(observ_id: str, token: Optional[str]) -> Optional[dict]:
    """
    Validasi token request webhook (C2/L2-3).
    Return target bila valid, None bila target tak ada ATAU token salah.
    Constant-time compare (anti timing attack).
    """
    import hmac
    if not token:
        return None
    target = await get_target(observ_id)
    if not target or not target.get("enabled", True):
        return None
    stored_hash = target.get("webhook_secret_hash")
    if not stored_hash:
        return None
    if not hmac.compare_digest(hash_token(token), stored_hash):
        return None
    return target


async def record_health_status(observ_id: str, status: str) -> None:
    """Simpan hasil health-check scheduler/webhook terakhir (untuk UI status)."""
    try:
        await _collection().update_one(
            {"observ_id": observ_id},
            {"$set": {"health_status": status, "last_health_check_at": _now()}},
        )
    except Exception as e:
        logger.warning(f"record_health_status({observ_id}) failed: {e}")


def _strip_secret(doc: dict) -> dict:
    d = dict(doc)
    d.pop("webhook_secret_hash", None)
    return d


def build_alertmanager_snippet(base_public_url: str, observ_id: str, token: str) -> str:
    """Snippet alertmanager.yml siap-copy untuk klien (C5/L2-6/L2-7)."""
    return f"""# alertmanager.yml — snippet Popov Agent (stack {observ_id})
route:
  group_by: ['alertname', 'service']
  group_wait: 10s
  group_interval: 5m
  repeat_interval: 1h
  receiver: 'popov-webhook'

receivers:
  - name: 'popov-webhook'
    webhook_configs:
      - url: '{base_public_url.rstrip('/')}/api/v1/webhook/alert/{observ_id}'
        send_resolved: true   # Popov bisa auto-tutup tiket saat alert resolved
        http_config:
          headers:
            X-Alertmanager-Token: '{token}'
"""


# ── Fase D: resolusi stack on-demand untuk pipeline agent ────────────────────

def build_observ_config(target: Optional[dict]) -> Optional[Dict[str, str]]:
    """Target → observ_config dict untuk AgentState. Fix #45: None → observability disabled
    (bukan fallback env) — stack MURNI dari DB observability_targets."""
    if not target:
        return None
    cfg = {
        "prometheus_url": (target.get("prometheus_url") or "").rstrip("/") or None,
        "tempo_url": (target.get("tempo_url") or "").rstrip("/") or None,
        "alertmanager_url": (target.get("alertmanager_url") or "").rstrip("/") or None,
        "loki_url": (target.get("loki_url") or "").rstrip("/") or None,
        "observ_id": target.get("observ_id"),
        "workspace_id": target.get("workspace_id"),
    }
    return cfg


async def get_observ_config_for_state(state: dict) -> Optional[Dict[str, str]]:
    """
    Resolusi satu-pintu untuk agent on-demand — Fix #45 M2M:
    baca workspace_id/project_id dari AgentState →
      linked (project_ids ∋ pid) menang; kosong → ws-wide; kosong → None.
    Return observ_config gabungan per-kind, atau None (= observability disabled,
    tanpa fallback env).
    """
    try:
        targets = await resolve_targets_for_project(
            state.get("workspace_id"), state.get("project_id")
        )
        return build_observ_config_merged(targets)
    except Exception as e:
        logger.warning(f"get_observ_config_for_state failed (non-fatal): {e}")
        return None


async def test_connection(target: dict, timeout_s: float = 4.0) -> Dict[str, Any]:
    """
    Probe endpoint tiap sumber yang terdaftar di target (D7/D1).
    Prometheus: GET /-/ready · Tempo: GET /ready · Alertmanager: GET /-/ready · Loki: GET /ready
    Return {source: {status, detail}} — status 'ok' | 'http_<code>' | 'error:<type>'.
    Sumber tanpa URL → {'status': 'not_configured'}.
    """
    import httpx
    probes = {
        "prometheus": ((target.get("prometheus_url") or "").rstrip("/"), PROBE_PATHS["prometheus"]),
        "tempo": ((target.get("tempo_url") or "").rstrip("/"), PROBE_PATHS["tempo"]),
        "alertmanager": ((target.get("alertmanager_url") or "").rstrip("/"), PROBE_PATHS["alertmanager"]),
        "loki": ((target.get("loki_url") or "").rstrip("/"), PROBE_PATHS["loki"]),
    }
    result: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for name, (base, path) in probes.items():
            if not base:
                result[name] = {"status": "not_configured"}
                continue
            try:
                resp = await client.get(f"{base}{path}")
                ok = resp.status_code < 500
                result[name] = {
                    "status": "ok" if ok else f"http_{resp.status_code}",
                    "url": base,
                }
            except Exception as e:
                result[name] = {"status": f"error:{type(e).__name__}", "url": base}

    overall = all(v["status"] == "ok" for v in result.values()) if result else False
    configured_any = any(v.get("status") != "not_configured" for v in result.values())
    return {
        "overall": "ok" if overall else ("degraded" if configured_any else "not_configured"),
        "sources": result,
        "checked_at": _now().isoformat(),
    }


async def probe_single(kind: str, url: str, timeout_s: float = 4.0) -> Dict[str, Any]:
    """
    Probe satu endpoint observability sebelum stack disimpan (dipakai create dialog).
    kind ∈ PROBE_PATHS. Return {status, url} dengan status 'ok' | 'http_<code>' | 'error:<type>'.
    """
    path = PROBE_PATHS.get(kind)
    base = (url or "").rstrip("/")
    if not path or not base:
        return {"status": "not_configured", "url": base}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(f"{base}{path}")
            return {
                "status": "ok" if resp.status_code < 500 else f"http_{resp.status_code}",
                "url": base,
            }
    except Exception as e:
        return {"status": f"error:{type(e).__name__}", "url": base}


# ── Fix #45: M2M project↔stack (typed) ──────────────────────────────────────

async def _target_by_oid(oid_str: str) -> Optional[dict]:
    from bson import ObjectId
    try:
        oid = ObjectId(oid_str)
    except Exception:
        return None
    doc = await _collection().find_one({"_id": oid})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def link_project(observ_id: str, project_id: str) -> Dict[str, Any]:
    """
    Link project ke stack (atomic $addToSet).
    Kind-collision: bila project sudah ter-link stack lain DENGAN kind sama
    di workspace ini → auto-replace ($pull dari stack lama). Return ringkasan.
    """
    target = await get_target(observ_id)
    if not target:
        raise ValueError("stack tidak ditemukan")
    kind = target.get("kind")
    if not kind:
        raise ValueError("stack belum memiliki 'kind' — set tipe stack dulu sebelum link")
    coll = _collection()

    # auto-replace: lepas project dari stack lama se-kind di workspace yang sama
    old_holders = await coll.find({
        "workspace_id": target.get("workspace_id"),
        "kind": kind,
        "observ_id": {"$ne": observ_id},
        "project_ids": project_id,
    }).to_list(50)
    replaced = [o["observ_id"] for o in old_holders]
    for o in old_holders:
        await coll.update_one({"_id": o["_id"]}, {"$pull": {"project_ids": project_id}})

    await coll.update_one({"observ_id": observ_id}, {"$addToSet": {"project_ids": project_id}})
    invalidate_obs_cfg_cache()
    logger.info(f"[ObservStore] link {observ_id} ← project={project_id} (replaced: {replaced or '-'})")
    return {"ok": True, "replaced": replaced}


async def unlink_project(observ_id: str, project_id: str) -> bool:
    result = await _collection().update_one(
        {"observ_id": observ_id}, {"$pull": {"project_ids": project_id}}
    )
    if result.matched_count:
        invalidate_obs_cfg_cache()
    return result.matched_count > 0


def build_observ_config_merged(targets: List[dict]) -> Optional[Dict[str, Any]]:
    """Gabung N target jadi satu observ_config — per kind ambil URL field-nya."""
    cfg: Dict[str, Any] = {
        "prometheus_url": None, "tempo_url": None,
        "alertmanager_url": None, "loki_url": None,
        "sources": [],
    }
    for t in sorted(targets, key=lambda x: x.get("created_at") or _now()):
        k = t.get("kind")
        url_field = KIND_URL_FIELD.get(k)
        if not url_field:
            continue
        val = (t.get(url_field) or "").strip() or None
        if val and not cfg[url_field]:
            cfg[url_field] = val.rstrip("/")
        cfg["sources"].append({"observ_id": t.get("observ_id"), "kind": k, "name": t.get("name")})
    cfg.pop("prometheus_url") if False else None
    # buang key internal utk konsumsi agent
    sources = cfg.pop("sources")
    if not any(cfg.get(u) for u in KIND_URL_FIELD.values()):
        return None
    cfg["sources"] = sources
    return cfg


async def resolve_targets_for_project(
    workspace_id: Optional[str],
    project_id: Optional[str] = None,
) -> List[dict]:
    """
    Resolver M2M (Fix #45):
      1. targets milik ws yang enabled & project_ids ∋ project_id  → spesifik menang
      2. bila kosong → targets ws yang project_ids == []           → default workspace
      3. kosong / tanpa konteks                                    → [] (.env fallback)
    Return daftar target terpilih (bisa >1, dibedakan by kind, dibersihkan secret).
    Fix #54: hasil di-cache TTL 30s per (ws, project) — invalidate_obs_cfg_cache() saat mutasi.
    """
    cache_key = (workspace_id, project_id)
    now = time.monotonic()
    hit = _OBS_CFG_CACHE.get(cache_key)
    if hit and now - hit[0] < _OBS_CFG_TTL:
        return hit[1]

    if not workspace_id:
        _OBS_CFG_CACHE[cache_key] = (now, [])
        return []
    try:
        base_q = {"workspace_id": workspace_id, "enabled": {"$ne": False}}
        if project_id:
            specific = await _collection().find({**base_q, "project_ids": project_id}).to_list(100)
            if specific:
                out = []
                for d in specific:
                    d["_id"] = str(d["_id"])
                    out.append(d)
                _OBS_CFG_CACHE[cache_key] = (now, out)
                return out
        wide = await _collection().find({**base_q, "$or": [
            {"project_ids": {"$exists": False}}, {"project_ids": []},
        ]}).to_list(100)
        out = []
        for d in wide:
            d["_id"] = str(d["_id"])
            out.append(d)
        _OBS_CFG_CACHE[cache_key] = (now, out)
        return out
    except Exception as e:
        logger.warning(f"resolve_targets_for_project failed (non-fatal): {e}")
        return []