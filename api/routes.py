from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from graph.workflow import app as langgraph_app
from api.deps import require_admin
from config.settings import settings
from services.doc_loader import list_all_services, build_agent_context, reload_docs
from services.request_log import create_request_log, update_request_log, generate_request_id
from services.mongodb_client import get_db
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response schema ──────────────────────────────────────────────────

class TriggerRequest(BaseModel):
    intent: str                 # "error pada <nama-service>"
    # Opsional: override collection langsung (bypass supervisor)
    collection_name: Optional[str] = None
    # Opsional: true bila ini balasan/mention jawaban agent sebelumnya (follow-up)
    reply_to_agent: Optional[bool] = None
    # MT isolation (SCALE plan A5): scope tenant — None = global/legacy
    workspace_id: Optional[str] = None
    observ_id: Optional[str] = None


class TriggerResponse(BaseModel):
    success: bool
    service_name: Optional[str]
    collection_name: Optional[str]
    documents_found: int
    telegram_sent: bool
    formatted_message: Optional[str]
    error: Optional[str]


class NotifyRequest(BaseModel):
    message: str                                # Pesan yang ingin dikirim langsung ke Telegram
    service_name: Optional[str] = "general"     # Service name untuk tombol Cek Detail
    show_buttons: Optional[bool] = True         # True untuk menampilkan tombol Inline [Cek Detail] & [Skip]
    # Fix #40 — target channel MURNI DB (raw chat_id dihapus):
    #   1) notif_id eksplisit, ATAU 2) workspace_id (+ project_id opsional) → broadcast union,
    #   3) keduanya kosong → 422 (tidak ada lagi fallback .env).
    notif_id: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None


class NotifyResponse(BaseModel):
    success: bool
    message: str
    telegram_sent: bool
    error: Optional[str] = None


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/notify", response_model=NotifyResponse)
async def notify_telegram(
    body: NotifyRequest,
):
    """
    Kirim pesan langsung ke Telegram DENGAN tombol interaktif (Cek Detail & Skip)
    TANPA melalui LLM agent.

    Fix #40: target channel dari DB — `notif_id` eksplisit (single channel asal),
    atau `workspace_id`(+`project_id`) → broadcast ke union channel project-linked
    ∪ workspace-wide. Raw chat_id tidak lagi diterima.
    """
    logger.info(f"POST /notify → service='{body.service_name}' notif={body.notif_id} ws={body.workspace_id}")
    try:
        from services.notification_store import get_notification, resolve_channels
        from services.telegram_client import broadcast, build_alert_buttons

        if body.notif_id:
            doc = await get_notification(body.notif_id)
            if not doc or doc.get("enabled") is False:
                return NotifyResponse(success=False, message="Channel tidak ditemukan / disabled",
                                      telegram_sent=False, error="channel_not_found")
            channels = [doc]
        elif body.workspace_id:
            channels = await resolve_channels(body.workspace_id, body.project_id)
            if not channels:
                return NotifyResponse(success=False, message="Tidak ada channel telegram enabled untuk konteks ini",
                                      telegram_sent=False, error="no_channel")
        else:
            return NotifyResponse(success=False, message="Wajib sertakan notif_id ATAU workspace_id",
                                  telegram_sent=False, error="missing_target")

        markup = build_alert_buttons(body.service_name) if body.show_buttons else None
        sent = await broadcast(channels, body.message, reply_markup=markup)
        ok = sent > 0
        return NotifyResponse(
            success=ok,
            message=f"Terkirim ke {sent}/{len(channels)} channel telegram",
            telegram_sent=ok,
            error=None if ok else "semua channel gagal",
        )
    except Exception as e:
        logger.error(f"POST /notify failed: {e}")
        return NotifyResponse(
            success=False,
            message="Gagal mengirim pesan ke Telegram",
            telegram_sent=False,
            error=str(e),
        )


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_agent(
    body: TriggerRequest,
    request: Request,
    x_user: Optional[str] = Header(default=None),
    x_ip: Optional[str] = Header(default=None),
):
    """
    Trigger the incident response agent pipeline.

    Contoh body:
    {
        "intent": "error pada <nama-service>"
    }
    """
    logger.info(f"POST /trigger → intent='{body.intent}'")

    request_id = generate_request_id()
    sender = {
        "channel": "api",
        "name": x_user or "anonymous",
        "ip": x_ip or request.client.host if request.client else None,
    }
    await create_request_log(
        channel="api",
        message_raw=body.intent,
        sender=sender,
        request_id=request_id,
    )

    initial_state = {
        "intent": body.intent,
        "service_name": "",
        "collection_name": body.collection_name or "",
        "request_id": request_id,
        "message_raw": body.intent,
        "sender": sender,
        "agents_visited": [],
        "is_follow_up": False,
        "follow_up_context": None,
        "reply_to_agent": body.reply_to_agent or False,
        "data_mode": False,
        "data_limit": None,
        "raw_documents": [],
        "query_used": {},
        "mongo_summary": None,
        "metrics_data": None,
        "metrics_summary": None,
        "metrics_available": False,
        "trace_data": None,
        "trace_summary": None,
        "trace_available": False,
        "trace_id": None,
        "correlation_result": None,
        "root_cause_assessment": None,
        "episode_id": None,
        "second_brain_context": None,
        "workspace_id": body.workspace_id or None,
        "observ_id": body.observ_id or None,
        "formatted_message": "",
        "telegram_sent": False,
        "telegram_error": None,
        "next_agent": "supervisor",
        "error": None,
    }

    try:
        result = await langgraph_app.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"Graph execution failed: {e}", exc_info=True)
        await update_request_log(request_id, initial_state, "failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Graph error: {str(e)}")

    # Jika ada error di pipeline
    if result.get("error"):
        await update_request_log(request_id, result, "failed", error=result["error"])
        return TriggerResponse(
            success=False,
            service_name=result.get("service_name"),
            collection_name=result.get("collection_name"),
            documents_found=0,
            telegram_sent=False,
            formatted_message=None,
            error=result["error"],
        )

    await update_request_log(
        request_id,
        result,
        "success",
        reply={
            "text": result.get("formatted_message"),
            "telegram_sent": result.get("telegram_sent"),
            "telegram_error": result.get("telegram_error"),
        },
        raw_documents=result.get("raw_documents"),
    )

    return TriggerResponse(
        success=True,
        service_name=result.get("service_name"),
        collection_name=result.get("collection_name"),
        documents_found=len(result.get("raw_documents", [])),
        telegram_sent=result.get("telegram_sent", False),
        formatted_message=result.get("formatted_message"),
        error=result.get("telegram_error"),
    )


@router.get("/docs/services")
async def get_services():
    """Lihat semua service yang terdeteksi dari DB (agent_docs) via list_all_services."""
    service_map = await list_all_services()
    return {
        "services": service_map,
        "total": len(service_map),
        "auto_discovered": list(service_map.keys()),
    }


@router.get("/docs/context/{service_id}")
async def get_context(service_id: str):
    """Preview konteks LLM untuk service tertentu."""
    context = await build_agent_context(service_id)
    if not context:
        raise HTTPException(status_code=404, detail=f"Dokumen service '{service_id}' tidak ditemukan.")
    return {
        "service_id": service_id,
        "context_length": len(context),
        "context": context,
    }


@router.post("/docs/reload")
async def reload_documentation():
    """Hot-reload dokumen dari docs/ tanpa restart server."""
    docs = await reload_docs()
    services = await list_all_services()
    return {
        "status": "success",
        "message": "Dokumen berhasil di-reload",
        "loaded": {k: len(v) for k, v in docs.items()},
        "services": list(services.keys()),
    }


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/observability/status")
async def observability_status():
    """Status konektivitas stack monitoring per-target dari DB observability_targets.
    Fix #45: sumber stack = DB (via UI), bukan env global."""
    from services.prometheus_client import query_prometheus, get_active_alerts
    from services.tempo_client import search_traces
    from services.mongodb_client import get_db

    targets = []
    try:
        rows = await get_db()["observability_targets"].find({"enabled": {"$ne": False}}).to_list(200)
        for t in rows:
            obs = {
                "observ_id": t.get("observ_id"),
                "name": t.get("name"),
                "webhook_mode": bool(t.get("webhook_mode")),
                "prometheus": {"url": t.get("prometheus_url"), "reachable": False},
                "alertmanager": {"url": t.get("alertmanager_url"), "reachable": False},
                "tempo": {"url": t.get("tempo_url"), "reachable": False},
            }
            if t.get("prometheus_url"):
                obs["prometheus"]["reachable"] = await query_prometheus("up", base_url_override=t.get("prometheus_url")) is not None
            if t.get("alertmanager_url"):
                await get_active_alerts("health-check", alertmanager_url_override=t.get("alertmanager_url"))
                obs["alertmanager"]["reachable"] = True
            if t.get("tempo_url"):
                obs["tempo"]["reachable"] = await search_traces("health-check", limit=1, tempo_url_override=t.get("tempo_url")) is not None
            targets.append(obs)
    except Exception as e:
        logger.warning(f"observability status target fetch failed: {e}")

    return {
        "observability_enabled": settings.observability_enabled,
        "target_count": len(targets),
        "targets": targets,
    }


@router.get("/logs")
async def get_request_logs(limit: int = 50, status: Optional[str] = None):
    """Lihat riwayat request yang tercatat di collection request_logs."""
    try:
        collection = get_db()["request_logs"]
        query = {"status": status} if status else {}
        cursor = collection.find(query).sort("incoming_date", -1).limit(min(limit, 500))
        docs = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            docs.append(doc)
        return {"total": len(docs), "logs": docs}
    except Exception as e:
        logger.error(f"Failed to fetch request logs: {e}")
        raise HTTPException(status_code=500, detail=f"Log fetch error: {str(e)}")


# ── Second Brain (Fase 1): Episodes ──────────────────────────────────────────

@router.get("/brain/episodes")
async def get_episodes(
    service: Optional[str] = None,
    limit: int = 20,
    status: str = "all",
):
    """
    List episode Second Brain.
    Query params:
      - service: filter service_name (optional)
      - limit: max 100, default 20
      - status: all | correct | wrong | pending
    """
    try:
        db = get_db()
        query: dict = {}
        if service:
            query["service_name"] = service
        if status == "correct":
            query["feedback"] = "correct"
        elif status == "wrong":
            query["feedback"] = "wrong"
        elif status == "pending":
            query["feedback"] = None
        # "all" → no feedback filter

        limit = min(max(limit, 1), 100)
        cursor = db["incident_episodes"].find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
        episodes = await cursor.to_list(length=limit)
        return {"total": len(episodes), "episodes": episodes}
    except Exception as e:
        logger.error(f"Failed to fetch episodes: {e}")
        raise HTTPException(status_code=500, detail=f"Episode fetch error: {str(e)}")


@router.delete("/brain/episodes/{episode_id}")
async def delete_episode(episode_id: str, admin: dict = Depends(require_admin)):
    """Hapus episode Second Brain (FE-6 MemoryViewer). Admin only."""
    result = await get_db()["incident_episodes"].delete_one({"episode_id": episode_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Episode tidak ditemukan")
    logger.info(f"Episode {episode_id} deleted by {admin.get('email')}")
    return {"deleted": episode_id}


@router.get("/brain/similar")
async def get_similar(
    service: str,
    mongo_summary: str = "",
    metrics_summary: str = "",
    trace_summary: str = "",
    intent: str = "",
    limit: int = 5,
    days: int = 30,
):
    """Debug Hybrid Search tanpa trigger pipeline full — DRY reuse read_similar_episodes."""
    try:
        from services.second_brain import read_similar_episodes
        state = {
            "service_name": service,
            "mongo_summary": mongo_summary,
            "metrics_summary": metrics_summary,
            "trace_summary": trace_summary,
            "intent": intent,
        }
        ctx = await read_similar_episodes(state, limit=min(limit, 20), days=days)
        if ctx is None:
            return {"service": service, "context": None, "note": "no data or service empty"}
        return {"service": service, "context": ctx}
    except Exception as e:
        logger.error(f"brain/similar failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/brain/mine")
async def trigger_pattern_miner(service: Optional[str] = None, days: int = 30):
    """Trigger manual Pattern Miner (Fase 5) — event-driven, no scheduler needed."""
    try:
        from agents.pattern_miner import run_pattern_miner
        result = await run_pattern_miner(service=service, days=days)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"Pattern miner failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/brain/patterns")
async def get_patterns(service: Optional[str] = None):
    """Preview patterns/<service>.json (Fase 5) — machine-readable."""
    try:
        from pathlib import Path
        import json
        if service:
            p = Path(f"patterns/{service}.json")
            if not p.exists():
                raise HTTPException(status_code=404, detail=f"Patterns for {service} not found")
            return json.loads(p.read_text(encoding="utf-8"))
        # all services
        out = {}
        for pf in Path("patterns").glob("*.json"):
            try:
                out[pf.stem] = json.loads(pf.read_text(encoding="utf-8"))
            except Exception:
                continue
        return {"patterns": out, "total": len(out)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/brain/sessions")
async def get_sessions(chat_id: Optional[str] = None, limit: int = 10):
    """Debug diagnostic sessions (Fase 6C) — optional."""
    try:
        from services.diagnostic_session import get_active_session
        from services.mongodb_client import get_db as _get_db
        if chat_id:
            sess = await get_active_session(chat_id)
            return {"session": sess}
        db = _get_db()
        cur = db["diagnostic_sessions"].find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
        docs = await cur.to_list(length=limit)
        return {"total": len(docs), "sessions": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/usage")
async def get_llm_usage(
    agent: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """Pencatatan pemakaian token LLM per panggilan (collection llm_usage).

    Filter opsional agent/model/status (ok|error|timeout).
    Menyertakan ringkasan agregat total token + breakdown per status.
    """
    try:
        db = get_db()
        coll = db["llm_usage"]
        query: dict = {}
        if agent:
            query["agent"] = agent
        if model:
            query["model"] = model
        if status:
            query["status"] = status
        limit = min(max(limit, 1), 500)
        cur = coll.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
        docs = await cur.to_list(length=limit)

        agg = await coll.aggregate([
            {"$match": query},
            {"$group": {
                "_id": None,
                "calls": {"$sum": 1},
                "ok": {"$sum": {"$cond": [{"$eq": ["$status", "ok"]}, 1, 0]}},
                "error": {"$sum": {"$cond": [{"$eq": ["$status", "error"]}, 1, 0]}},
                "timeout": {"$sum": {"$cond": [{"$eq": ["$status", "timeout"]}, 1, 0]}},
                "prompt_tokens": {"$sum": {"$ifNull": ["$prompt_tokens", 0]}},
                "completion_tokens": {"$sum": {"$ifNull": ["$completion_tokens", 0]}},
                "total_tokens": {"$sum": {"$ifNull": ["$total_tokens", 0]}},
                "avg_latency_ms": {"$avg": "$latency_ms"},
            }},
        ]).to_list(1)

        return {
            "total_calls": agg[0]["calls"] if agg else 0,
            "by_status": {
                "ok": agg[0]["ok"] if agg else 0,
                "error": agg[0]["error"] if agg else 0,
                "timeout": agg[0]["timeout"] if agg else 0,
            },
            "total_tokens": agg[0]["total_tokens"] if agg else 0,
            "prompt_tokens": agg[0]["prompt_tokens"] if agg else 0,
            "completion_tokens": agg[0]["completion_tokens"] if agg else 0,
            "avg_latency_ms": agg[0]["avg_latency_ms"] if agg else 0,
            "logs": docs,
        }
    except Exception as e:
        logger.error(f"llm/usage failed: {e}")
        raise HTTPException(status_code=500, detail=f"LLM usage fetch error: {str(e)}")


@router.get("/prompts")
async def list_prompts():
    """Daftar templat prompt LLM (file-driven, editable via prompts/*.md)."""
    from services.prompt_loader import list_prompts
    return {"total": len(list_prompts()), "prompts": list_prompts()}


@router.get("/prompts/{name}")
async def get_prompt(name: str):
    """Preview satu templat prompt."""
    from services.prompt_loader import get_prompt
    tpl = get_prompt(name)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' tidak ditemukan")
    return {"name": name, "template": tpl}


@router.post("/prompts/reload")
async def reload_prompts_endpoint():
    """Hot-reload templat prompt dari file (tanpa restart)."""
    from services.prompt_loader import reload_prompts
    reload_prompts()
    return {"status": "ok", "message": "Prompt cache di-reload"}


@router.get("/brain/episodes/{episode_id}")
async def get_episode_detail(episode_id: str):
    """Detail satu episode by episode_id."""
    try:
        db = get_db()
        doc = await db["incident_episodes"].find_one({"episode_id": episode_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Episode not found")
        return doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Episode fetch error: {str(e)}")

