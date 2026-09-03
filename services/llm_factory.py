"""
LLM Factory — satu tempat untuk membangun ChatOpenAI sesuai konfigurasi BYOK (Fix #54).

Sumber konfigurasi (prioritas):
  1. DB `llm_settings` (via llm_config_store) — provider/model/base_url/key dikelola UI,
     key terenkripsi. Cache in-memory; refresh saat PUT /config/llm atau startup.
  2. Fallback bootstrap: settings (.env/code default) bila DB kosong.

Provider didukung: openai, openrouter, google, opencode (OpenCode Zen gateway), claude (Anthropic OpenAI-compatible layer).
Dipakai oleh response_agent, correlation_agent, supervisor (Strategy 5),
dan pattern_miner_service — satu-satunya tempat branching provider.

Fix #51: max_tokens dibatasi (3000) — cegah 402 kredit OpenRouter.
Fix #54: ganti provider/model/key/base_url dari UI berlaku LANGSUNG (tanpa restart).
"""
from __future__ import annotations

from typing import Optional

from langchain_openai import ChatOpenAI

from config.settings import settings
from services.llm_usage import TrackingLLM

MAX_TOKENS = 3000

_llm_config_cache: Optional[dict] = None


async def load_llm_config_from_db() -> Optional[dict]:
    """Load config BYOK dari DB ke cache (dipanggil startup lifespan)."""
    global _llm_config_cache
    from services.llm_config_store import get_llm_config
    cfg = await get_llm_config()
    if cfg:
        _llm_config_cache = cfg
    return _llm_config_cache


def set_llm_config_cache(cfg: Optional[dict]) -> None:
    """Update cache setelah PUT /config/llm — berlaku tanpa restart."""
    global _llm_config_cache
    _llm_config_cache = cfg


def get_chat_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Bangun instance ChatOpenAI dari config BYOK (DB) atau fallback settings."""
    cfg = _llm_config_cache
    if cfg:
        provider = cfg.get("provider") or "openai"
        models = cfg.get("models") or {}
        model = (models.get(provider) or cfg.get("model") or "").strip()  # Fix #56: model per provider
        keys = cfg.get("keys") or {}
        bases = cfg.get("base_urls") or {}
        api_key = keys.get(provider)
        base_url = (bases.get(provider) or "").strip().rstrip("/")
        if model and base_url:
            # key boleh kosong (belum di-set di UI) → call gagal auth dgn pesan jelas,
            # bukan fallback diam-diam ke provider lain.
            llm = ChatOpenAI(
                model=model,
                api_key=api_key or "",
                base_url=base_url,
                temperature=temperature,
                max_tokens=MAX_TOKENS,
            )
            return TrackingLLM(llm, provider, model)

    # Fallback bootstrap: settings (.env/code default)
    if settings.llm_provider == "openrouter":
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=temperature,
            max_tokens=MAX_TOKENS,
        )
        return TrackingLLM(llm, "openrouter", settings.llm_model)
    if settings.llm_provider == "google":
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.google_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            temperature=temperature,
            max_tokens=MAX_TOKENS,
        )
        return TrackingLLM(llm, "google", settings.llm_model)
    if settings.llm_provider == "opencode":
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.opencode_api_key,
            base_url=settings.opencode_base_url.rstrip("/"),
            temperature=temperature,
            max_tokens=MAX_TOKENS,
        )
        return TrackingLLM(llm, "opencode", settings.llm_model)
    if settings.llm_provider == "claude":
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.claude_api_key,
            base_url=settings.claude_base_url.rstrip("/"),
            temperature=temperature,
            max_tokens=MAX_TOKENS,
        )
        return TrackingLLM(llm, "claude", settings.llm_model)
    # default: openai
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=temperature,
        max_tokens=MAX_TOKENS,
    )
    return TrackingLLM(llm, "openai", settings.llm_model)