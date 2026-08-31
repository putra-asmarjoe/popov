import logging
from typing import Optional
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # MongoDB Default
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "popovagent_db"

    # MySQL Default
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_db: str = "popovagent_db"

    # Fix #45: per-service DB config & service→collection map TIDAK lagi dari
    # file JSON/env — MURNI DB (agent_docs untuk grounding+collection,
    # registry/library untuk db_config). Lihat db_loader.resolve_db_config.

    # Telegram — Fix #40: MURNI DB (collection notification_targets).
    # Tidak ada lagi bot global dari .env; kelola channel per-workspace di
    # Workspace Settings → tab Notifikasi (atau scripts/import_env_telegram.py
    # untuk migrasi pasangan .env lama menjadi channel pertama).
    telegram_api_base: str = "https://api.telegram.org"  # override utk mock-test / self-hosted proxy

    # LLM Configuration
    # Fix #54 (BYOK): provider/model/key/base_url MURNI dikelola via UI → DB
    # (collection llm_settings, key terenkripsi Fernet). Nilai di sini hanya
    # FALLBACK bootstrap saat DB kosong — .env tidak lagi berisi key LLM.
    llm_provider: str = "openai"  # openai, openrouter, google, opencode
    llm_model: str = "gpt-4o-mini"

    # Fix #54: master key enkripsi data sensitif di DB (LLM/embedding API keys).
    # Wajib ada di .env (DATA_ENCRYPTION_KEY) — Fernet key. Hilang = tak bisa dekripsi.
    data_encryption_key: str = ""
    
    # API Keys
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    google_api_key: str = ""
    opencode_api_key: str = ""  # OpenCode Zen gateway (https://opencode.ai/zen/v1)
    # Fix #52: base URL opencode configurable — model 'go' (MiMo-V2.5) dilayani dari
    # /zen/go/v1 (serverless), model utama (gemini/gpt/claude) dari /zen/v1.
    opencode_base_url: str = "https://opencode.ai/zen/v1"

    # Embedding — Second Brain (Fase 2+)
    # provider: local (TF cosine, tanpa API) | openrouter | openai
    # local = default fallback, nol biaya, sudah jalan untuk 60 episode
    # openrouter + liquid = gratis (LFM2.5-Embedding-350M, 1024d, 512 ctx, 135M tokens free)
    embedding_provider: str = "local"
    embedding_model: str = "liquid/lfm-2.5-embedding-350m:free"
    embedding_dim: int = 1024
    embedding_timeout_ms: int = 3000
    # Opsional override URL (kosong = pakai default provider)
    embedding_api_url: str = ""
    embedding_max_chars: int = 8000   # max chars to embed (truncation limit)

    # Observability
    prometheus_url: str = ""
    tempo_url: str = ""
    alertmanager_url: str = ""
    observability_timeout_ms: int = 5000
    observability_enabled: bool = True
    observability_interval_min: int = 5
    # Filter alert noise untuk watchdog (pisahkan dengan koma). Kosongkan untuk disable filter.
    # observability_ignore_alertnames: daftar nama alert yang TIDAK dikirim (mis. "Watchdog" sentinel).
    # observability_ignore_severities: daftar severity yang TIDAK dikirim (mis. "none, info").
    observability_ignore_alertnames: str = "Watchdog"
    observability_ignore_severities: str = "none"

    # Loki — Deploy Check Fase 3 (read-only k8s events)
    loki_url: str = "http://localhost:3100"
    loki_timeout_ms: int = 2500
    loki_namespace: str = "default"

    # FE-4: auto-ticket watchdog — routing kini via incident_router
    # (service→project link → observability target → project pertama workspace).
    # WATCHDOG_TICKET_PROJECT_ID legacy DIHAPUS (Fix #40).

    @property
    def loki_enabled(self) -> bool:
        return bool(self.loki_url)

    # Auth JWT — FE-1 (frontend web/)
    # WAJIB ganti JWT_SECRET di production (.env); default hanya untuk dev lokal.
    jwt_secret: str = "popov-dev-secret-change-me"
    jwt_expiry_hours: int = 24

    # App
    app_debug: bool = False

    # Knowledge Agent — Gap 1: relevance-based retrieval tuning
    knowledge_max_total_chars: int = 8000    # total character budget for knowledge_context
    knowledge_max_item_chars: int = 2000     # per-doc truncation limit
    knowledge_top_k: int = 5                 # max docs from vector search
    knowledge_threshold: float = 0.3         # min cosine similarity score (0.0–1.0)
    knowledge_min_query_len: int = 10        # below this → keyword fallback

    # API Key Rate Limits (per hour, in-memory sliding window)
    api_key_rate_limit_web: int = 1000       # default rate limit for web keys
    api_key_rate_limit_public: int = 200     # default rate limit for public keys

    # Time-window query log (observability & detail observability):
    # hanya ambil data maksimal N jam ke belakang, sehingga error lama (berhari-hari
    # lalu) tidak dilaporkan sebagai insiden baru.
    log_time_window_hours: int = 6

    # Dedup auto-ticket watchdog (window jam): alert dengan konten sama dalam window
    # ini di-link ke tiket AKTIF yang sama (collection ticket_alerts), bukan tiket baru.
    # Di luar window / tiket resolved|closed → tiket baru. 0 = tanpa batas waktu
    # (link ke tiket aktif apa pun umurnya).
    ticket_alert_dedup_hours: int = 12

    # Centralized OpenTelemetry log DB (observplan.md) — sumber kebenaran lintas-service.
    # Fix #107: konfigurasi MURNI dari DB (stack kind="otel" di observability_targets,
    # dikelola via UI Workspace Settings → Stacks) — TIDAK ada lagi fallback .env.

    @property
    def prometheus_enabled(self) -> bool:
        return bool(self.prometheus_url) and self.observability_enabled

    @property
    def tempo_enabled(self) -> bool:
        return bool(self.tempo_url) and self.observability_enabled

    @property
    def alertmanager_enabled(self) -> bool:
        return bool(self.alertmanager_url) and self.observability_enabled

    @property
    def observability_ignored_alertnames(self) -> set:
        """Set nama alert yang diabaikan watchdog (lowercase)."""
        return {a.strip().lower() for a in self.observability_ignore_alertnames.split(",") if a.strip()}

    @property
    def observability_ignored_severities(self) -> set:
        """Set severity yang diabaikan watchdog (lowercase)."""
        return {s.strip().lower() for s in self.observability_ignore_severities.split(",") if s.strip()}

    # ── Embedding helpers ──────────────────────────────────────────────────
    @property
    def embedding_enabled(self) -> bool:
        """True bila provider bukan local dan model terisi."""
        return self.embedding_provider.lower() != "local" and bool(self.embedding_model)

    @property
    def embedding_api_key(self) -> str:
        """Ambil API key sesuai provider embedding — treat placeholder sebagai kosong."""
        prov = self.embedding_provider.lower()
        key = ""
        if prov == "openrouter":
            key = self.openrouter_api_key
        elif prov == "openai":
            key = self.openai_api_key
        elif prov == "google":
            key = self.google_api_key
        # placeholder dari .env.example / .env default jangan dianggap valid
        if not key or key.strip() in ("sk-", "sk-or-v1-", "sk-or-v1-test", "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"):
            return ""
        # key terlalu pendek kemungkinan placeholder
        if len(key.strip()) < 20:
            return ""
        return key.strip()

    @property
    def embedding_base_url(self) -> str:
        """Base URL untuk embeddings API."""
        if self.embedding_api_url:
            return self.embedding_api_url.rstrip("/")
        prov = self.embedding_provider.lower()
        if prov == "openrouter":
            return "https://openrouter.ai/api/v1"
        if prov == "openai":
            return "https://api.openai.com/v1"
        # google embeddings via openai compat?
        if prov == "google":
            return "https://generativelanguage.googleapis.com/v1beta/openai"
        return ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Abaikan key .env yang tidak dikenal (mis. telegram_bot_token/chat_id
        # sisa sebelum Fix #40) — jangan sampai app gagal start karena extra input.
        extra = "ignore"


settings = Settings()

