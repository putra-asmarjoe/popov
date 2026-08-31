"""
LLM Config Store — BYOK (Bring Your Own Key), Fix #54.

Collection `llm_settings` (1 doc, _id="llm"):
    provider, model, base_urls{prov:url}, keys{prov:<Fernet-enc>}, embedding{mode,provider,model}.

- Keys dienkripsi at-rest dgn Fernet (master key `DATA_ENCRYPTION_KEY` dari .env).
- API TIDAK pernah mengembalikan plaintext key — hanya status set/unset + mask.
- Default base_url per provider (user bisa edit — mis. opencode /zen/go/v1 utk MiMo).
- Embedding: mode "local" (TF cosine, tanpa API) ATAU "provider" (reuse key/base_url
  provider LLM yang sudah di-set user, tinggal pilih model embedding).
- Cache in-memory hasil dekripsi; invalidate saat PUT /config/llm.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config.settings import settings

logger = logging.getLogger(__name__)

COLLECTION = "llm_settings"
DOC_ID = "llm"

PROVIDERS = ("openai", "openrouter", "google", "opencode")

DEFAULT_BASE_URLS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "opencode": "https://opencode.ai/zen/v1",
}

_cache: Optional[dict] = None
_cache_empty: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Enkripsi ──────────────────────────────────────────────────────────────────

def _fernet():
    from cryptography.fernet import Fernet, InvalidToken
    key = (settings.data_encryption_key or "").strip()
    if not key:
        raise ValueError(
            "DATA_ENCRYPTION_KEY belum di-set di .env — wajib utk enkripsi key LLM. "
            "Generate: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode())
    except Exception as e:
        raise ValueError(f"DATA_ENCRYPTION_KEY tidak valid (butuh Fernet 32-byte urlsafe base64): {e}") from e


def _encrypt(plain: str) -> Optional[str]:
    if not plain:
        return None
    return _fernet().encrypt(plain.encode()).decode()


def _decrypt(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception as e:
        logger.error(f"[LLMConfig] decrypt gagal (master key salah/hilang?): {e}")
        return None


def _mask_key(key: Optional[str]) -> str:
    if not key:
        return ""
    if len(key) <= 12:
        return "***"
    return f"{key[:6]}***{key[-4:]}"


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def _collection():
    from services.mongodb_client import get_db
    return get_db()[COLLECTION]


async def ensure_llm_indexes() -> None:
    # single-doc collection; index _id otomatis unik. No-op jaga konsistensi.
    logger.info("llm_settings ensured (single doc)")


def invalidate_cache() -> None:
    global _cache, _cache_empty
    _cache = None
    _cache_empty = False


async def get_llm_config() -> Optional[dict]:
    """Config lengkap + key TERDEKRIPSI (utk factory/embedding) + cache. None bila kosong.
    Fix #54: negative cache — DB kosong tidak di-query ulang tiap call (hindari DB hit berulang)."""
    global _cache, _cache_empty
    if _cache is not None:
        return _cache
    if _cache_empty:
        return None
    try:
        doc = await (await _collection()).find_one({"_id": DOC_ID})
    except Exception as e:
        logger.warning(f"[LLMConfig] get failed: {e}")
        return None
    if not doc:
        _cache_empty = True
        return None
    keys = {}
    for p in PROVIDERS:
        keys[p] = _decrypt(doc.get("keys", {}).get(p))
    models_raw = doc.get("models") or {}
    models = {p: (models_raw.get(p) or "").strip() for p in PROVIDERS}
    provider = doc.get("provider") or "openai"
    cfg = {
        "provider": provider,
        "model": models.get(provider) or (doc.get("model") or ""),  # efektif utk provider aktif
        "models": models,  # model PER provider (Fix #56)
        "base_urls": {p: (doc.get("base_urls") or {}).get(p) or DEFAULT_BASE_URLS[p] for p in PROVIDERS},
        "keys": keys,
        "embedding": doc.get("embedding") or {"mode": "local"},
        "updated_at": doc.get("updated_at"),
    }
    _cache = cfg
    return cfg


async def set_llm_config(
    provider: str,
    model: Optional[str] = None,
    base_urls: Optional[Dict[str, str]] = None,
    keys: Optional[Dict[str, str]] = None,
    embedding: Optional[Dict[str, Any]] = None,
    models: Optional[Dict[str, str]] = None,
) -> dict:
    """Simpan config; keys dienkripsi. Keys kosong = pertahankan yang lama. Return public.
    Fix #56: model PER provider (`models`) — provider A boleh model beda dari provider B.
    `model` (opsional) = model utk provider AKTIF (backward compat / PUT parsial)."""
    existing = await get_llm_config()

    # ── models per provider: preserve existing → apply models → apply model(aktif) ──
    merged_models: Dict[str, str] = {}
    if existing and existing.get("models"):
        merged_models = dict(existing["models"])
    if models:
        for p in PROVIDERS:
            v = (models.get(p) or "").strip()
            if v:
                merged_models[p] = v
    if model is not None and str(model).strip():
        merged_models[provider] = str(model).strip()
    for p in PROVIDERS:
        merged_models.setdefault(p, "")

    enc_keys: Dict[str, Optional[str]] = {}
    for p in PROVIDERS:
        new_val = ((keys or {}).get(p) or "").strip()
        if new_val:
            enc_keys[p] = _encrypt(new_val)
        elif existing:
            enc_keys[p] = _encrypt(existing["keys"].get(p) or "")
        else:
            enc_keys[p] = None

    merged_base = {p: DEFAULT_BASE_URLS[p] for p in PROVIDERS}
    # preserve base_url existing utk provider yang TIDAK dikirim (jangan reset ke default)
    if existing:
        for p in PROVIDERS:
            if existing["base_urls"].get(p):
                merged_base[p] = existing["base_urls"][p]
    if base_urls:
        for p in PROVIDERS:
            v = (base_urls.get(p) or "").strip().rstrip("/")
            if v:
                merged_base[p] = v

    emb = dict(embedding or {})
    mode = (emb.get("mode") or "local").lower()
    if mode == "provider":
        emb["provider"] = (emb.get("provider") or "").lower() if (emb.get("provider") or "").lower() in PROVIDERS else None
    else:
        emb = {"mode": "local"}

    doc = {
        "_id": DOC_ID,
        "provider": provider,
        "model": merged_models.get(provider, ""),
        "models": merged_models,
        "base_urls": merged_base,
        "keys": enc_keys,
        "embedding": emb,
        "updated_at": _now_iso(),
    }
    await (await _collection()).update_one({"_id": DOC_ID}, {"$set": doc}, upsert=True)
    invalidate_cache()
    return await public_config()


async def public_config() -> dict:
    """Config untuk API (tanpa plaintext key): status + mask + base_urls + embedding."""
    cfg = await get_llm_config()
    if not cfg:
        return {
            "provider": "openai",
            "model": "",
            "models": {p: "" for p in PROVIDERS},
            "baseUrls": dict(DEFAULT_BASE_URLS),
            "keys": {p: "unset" for p in PROVIDERS},
            "keysMasked": {p: "" for p in PROVIDERS},
            "embedding": {"mode": "local", "provider": None, "model": ""},
            "updatedAt": None,
            "restart_required": False,
        }
    keys = cfg.get("keys") or {}
    return {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "models": cfg.get("models") or {p: "" for p in PROVIDERS},
        "baseUrls": cfg["base_urls"],
        "keys": {p: ("set" if keys.get(p) else "unset") for p in PROVIDERS},
        "keysMasked": {p: _mask_key(keys.get(p)) for p in PROVIDERS},
        "embedding": cfg.get("embedding") or {"mode": "local"},
        "updatedAt": cfg.get("updated_at"),
        "restart_required": False,
    }


# ── Embedding resolver ────────────────────────────────────────────────────────

async def get_embedding_cfg() -> Optional[dict]:
    """
    Config embedding efektif utk Second Brain. None = pakai TF cosine lokal.
    - DB terisi & mode=provider → reuse key+base_url provider LLM terpilih + model embedding.
    - DB kosong (BYOK belum diatur) → fallback legacy settings.embedding_*.
    """
    cfg = await get_llm_config()
    if cfg:
        emb = cfg.get("embedding") or {}
        mode = (emb.get("mode") or "local").lower()
        if mode != "provider":
            return None
        prov = (emb.get("provider") or "").lower()
        model = (emb.get("model") or "").strip()
        if prov not in PROVIDERS or not model:
            return None
        keys = cfg.get("keys") or {}
        bases = cfg.get("base_urls") or {}
        api_key = keys.get(prov)
        base_url = (bases.get(prov) or "").strip()
        if not api_key or not base_url:
            return None
        return {
            "provider": prov,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "dim": int(settings.embedding_dim),
            "timeout_ms": int(settings.embedding_timeout_ms),
            "max_chars": int(emb.get("maxChars") or settings.embedding_max_chars),
            "is_openrouter": prov == "openrouter",
        }
    # fallback legacy (BYOK belum diatur) — baca settings.embedding_*
    if settings.embedding_enabled:
        api_key = settings.embedding_api_key
        base_url = settings.embedding_base_url
        if api_key and base_url:
            return {
                "provider": settings.embedding_provider,
                "model": settings.embedding_model,
                "api_key": api_key,
                "base_url": base_url,
                "dim": int(settings.embedding_dim),
                "timeout_ms": int(settings.embedding_timeout_ms),
                "max_chars": int(settings.embedding_max_chars),
                "is_openrouter": settings.embedding_provider.lower() == "openrouter",
            }
    return None


async def _saved_provider_ctx(provider: str) -> dict:
    """Fallback test: key/base_url tersimpan utk provider (bila form kosong)."""
    cfg = await get_llm_config()
    keys = (cfg or {}).get("keys") or {}
    bases = (cfg or {}).get("base_urls") or {}
    return {
        "api_key": keys.get(provider) or "",
        "base_url": (bases.get(provider) or "").rstrip("/") or DEFAULT_BASE_URLS.get(provider, ""),
    }


async def test_llm_connection(provider: str, model: str, base_url: str, api_key: str) -> Dict[str, Any]:
    """Probe LLM completion minimal ('pong'). Return {ok, latency_ms, error}.
    Fix #54: api_key/base_url kosong → pakai key/base_url tersimpan utk provider tsb."""
    import time
    from langchain_core.messages import SystemMessage, HumanMessage
    from langchain_openai import ChatOpenAI
    saved = await _saved_provider_ctx(provider)
    key = (api_key or "").strip() or saved["api_key"]
    base = (base_url or "").strip().rstrip("/") or saved["base_url"]
    if not key:
        return {"ok": False, "latency_ms": None, "error": "API key belum diisi (form / tersimpan)"}
    try:
        llm = ChatOpenAI(
            model=model,
            api_key=key,
            base_url=base,
            temperature=0.0,
            max_tokens=50,
        )
        t0 = time.monotonic()
        resp = await llm.ainvoke([SystemMessage(content="Jawab satu kata: pong"), HumanMessage(content="ping")])
        return {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000), "error": None,
                "reply": str(resp.content or "")[:60]}
    except Exception as e:
        return {"ok": False, "latency_ms": None, "error": f"{type(e).__name__}: {str(e)[:180]}"}


async def test_embedding_connection(provider: str, model: str, base_url: str, api_key: str) -> Dict[str, Any]:
    """Probe embedding endpoint ('tes'). Return {ok, dim, latency_ms, error}.
    Fix #54: api_key/base_url kosong → pakai tersimpan utk provider tsb."""
    import httpx
    import time
    saved = await _saved_provider_ctx(provider)
    key = (api_key or "").strip() or saved["api_key"]
    base = (base_url or "").strip().rstrip("/") or saved["base_url"]
    if not key:
        return {"ok": False, "dim": None, "latency_ms": None, "error": "API key belum diisi (form / tersimpan)"}
    try:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://popov-agent.local"
            headers["X-Title"] = "Popov Agent"
        payload = {"model": model, "input": "tes koneksi embedding"}
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{base}/embeddings", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        vec = data.get("data", [{}])[0].get("embedding")
        if not isinstance(vec, list):
            return {"ok": False, "dim": None, "latency_ms": None, "error": "respons tanpa vector"}
        return {"ok": True, "dim": len(vec), "latency_ms": int((time.monotonic() - t0) * 1000), "error": None}
    except Exception as e:
        return {"ok": False, "dim": None, "latency_ms": None, "error": f"{type(e).__name__}: {str(e)[:180]}"}