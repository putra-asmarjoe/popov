import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from pathlib import Path
from api.routes import router
from api.auth import router as auth_router
from api.workspaces import router as workspaces_router
from api.tickets import router as tickets_router
from api.notifications import router as notifications_router
from api.ws import router as ws_router
from api.chat import router as chat_router
from api.config_api import router as config_router
from api.notification_channels import router as notification_channels_router  # Fix #39
from api.knowledge import router as knowledge_router  # FE-7 (menggantikan ingest)
from api.services_lib import router as services_lib_router  # FE-8
from api.agent_docs import router as agent_docs_router  # grounding docs DB (admin CRUD)
from services.mongodb_client import close as close_mongo
from services.telegram_listener import start_polling
from services.request_log import ensure_indexes
from config.settings import settings
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

_log_dir = Path("logs")
_log_dir.mkdir(exist_ok=True)
_file_handler = logging.FileHandler(_log_dir / "app.log")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(_file_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await ensure_indexes()
    # Layer 2: index collection observability_targets (webhook per-tenant)
    try:
        from services.observability_store import ensure_target_indexes
        await ensure_target_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"observability_targets indexes not ensured: {e}")
    # Fix #37: index collection notification_targets
    try:
        from services.notification_store import ensure_notification_indexes
        await ensure_notification_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"notification_targets indexes not ensured: {e}")
    # FE-1: index users.email unique (auth)
    try:
        from services.user_store import ensure_user_indexes
        await ensure_user_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"User indexes not ensured: {e}")
    # FE-2: index workspaces.slug + projects workspaceId+slug/key unique
    try:
        from services.workspace_store import ensure_workspace_indexes
        await ensure_workspace_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Workspace indexes not ensured: {e}")
    # FE-3: index tickets projectId+ticketNumber unique + filter indexes
    try:
        from services.ticket_store import ensure_ticket_indexes
        await ensure_ticket_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Ticket indexes not ensured: {e}")
    # Alert↔Tiket: index collection ticket_alerts (1 tiket : N alert, dedup window)
    try:
        from services.ticket_alert_store import ensure_ticket_alert_indexes
        await ensure_ticket_alert_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Ticket alert indexes not ensured: {e}")
    # FE-4: index notifications userId+readAt
    try:
        from services.notification_store import ensure_notification_indexes
        await ensure_notification_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Notification indexes not ensured: {e}")
    # FE-5: index chat sessions/messages
    try:
        from services.chat_store import ensure_chat_indexes
        await ensure_chat_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Chat indexes not ensured: {e}")
    # FE-7: index knowledge library + refs workspace
    try:
        from services.knowledge_store import ensure_knowledge_indexes
        await ensure_knowledge_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Knowledge indexes not ensured: {e}")
    # FE-8: index services library + refs project/knowledge
    try:
        from services.service_store import ensure_service_indexes
        await ensure_service_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Service indexes not ensured: {e}")
    # grounding docs DB (agent_docs) — index category+key unique
    try:
        from services.agent_docs_store import ensure_agent_docs_indexes
        await ensure_agent_docs_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Agent docs indexes not ensured: {e}")
    # Offer Session — index tawaran aksi lanjutan (Tahap 1-3)
    try:
        from services.offer_session import ensure_offer_indexes
        await ensure_offer_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Offer indexes not ensured: {e}")
    # LLM Usage — index pencatatan pemakaian token per agent
    try:
        from services.llm_usage import ensure_llm_usage_indexes
        await ensure_llm_usage_indexes()
    except Exception as e:
        logging.getLogger(__name__).warning(f"LLM usage indexes not ensured: {e}")
    # BYOK LLM (Fix #54): load config LLM dari DB ke cache factory (tanpa restart saat ganti)
    try:
        from services.llm_factory import load_llm_config_from_db
        await load_llm_config_from_db()
    except Exception as e:
        logging.getLogger(__name__).warning(f"LLM config load dari DB gagal (fallback settings): {e}")
    # Warm cache grounding docs (agent_docs) di startup — agent TIDAK buka DB saat request
    # (list_all_services/build_agent_context baca cache; reload_docs() utk invalidate manual).
    try:
        from services.doc_loader import load_all_docs
        await load_all_docs()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Doc loader warm-up gagal (fallback file): {e}")
    polling_task = asyncio.create_task(start_polling())
    # SCALE plan Layer 1 (Fix B3): watchdog + auto_feedback TIDAK lagi berjalan
    # di proses FastAPI — jalankan `python watchdog_worker.py` terpisah
    # (WAJIB tepat 1 instance; lihat deploy/watchdog-deployment.yaml).
    #
    # ⚠️ CONSTRAINT: start_polling() (Telegram getUpdates) juga singleton-global.
    #    Scale-out Pod API >1 akan dobel polling → jangan scale API sebelum
    #    listener dipindah ke worker terpisah (lihat README bagian Scaling).
    yield
    # Shutdown
    for task in (polling_task,):
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await close_mongo()


app = FastAPI(
    title="Popov - Incident Response Agent",
    description="LangGraph multi-agent: MongoDB reader + Telegram notifier",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")
# Layer 2: Alertmanager push webhook per-tenant (SCALE_ESCALATION_PLAN)
from api.webhook import router as webhook_router  # noqa: E402
app.include_router(webhook_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(tickets_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(notification_channels_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(services_lib_router, prefix="/api/v1")
app.include_router(agent_docs_router, prefix="/api/v1")


# ── FE-6: serve SPA (web/dist) — satu container, satu domain ──────────────────
# Didaftarkan SETELAH semua router API → /api/*, /docs, /openapi.json tetap menang.
# Fallback ke index.html untuk path SPA (deep-link /w/x/y?ticket=…) refresh-safe.
from fastapi.responses import FileResponse  # noqa: E402

WEB_DIST = Path(__file__).parent / "web" / "dist"

if WEB_DIST.is_dir():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        # Path API yang tidak cocok route mana pun → 404 JSON, bukan HTML
        if full_path.startswith("api/") or full_path in ("openapi.json",):
            raise HTTPException(status_code=404, detail="Not found")
        # resolve() + cek prefix: blokir path traversal (../../.env) — Fix FE-6
        candidate = (WEB_DIST / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(WEB_DIST.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")

# FE-1: CORS untuk dev server Vite (build production diserve same-origin oleh FastAPI)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
