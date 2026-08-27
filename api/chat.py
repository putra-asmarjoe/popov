"""
Chat router — FE-5 Chat AI (SSE streaming + context injection tiket).

- POST /chat/sessions                     → buat session
- GET  /chat/sessions?projectId=          → list session user
- GET  /chat/sessions/{id}/messages       → history
- POST /chat/sessions/{id}/send           → persist user msg + jalankan pipeline (background)
- GET  /chat/sessions/{id}/stream?token=  → SSE: event agent/token + sentinel [DONE]

Bridge DRY: pipeline = graph.astream(stream_mode="updates") yang SUDAH ADA —
tanpa perubahan logika agent (hanya flag suppress_telegram agar tidak kirim
ke grup Telegram). Konteks tiket di-inject frontend sebagai prefix [context: ...].
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_current_user
from graph.workflow import app as langgraph_app
from services.chat_store import (
    add_message,
    create_session,
    get_messages,
    get_session,
    list_sessions,
    soft_delete_session,
    _public_message,
    _public_session,
)
from services.chat_stream import (
    DONE,
    publish,
    publish_sentinel,
    mark_done,
    register,
    release_reader,
    try_set_reader,
    unregister,
    is_active,
)
from services.request_log import generate_request_id, create_request_log, update_request_log
from services.conversation import build_conversation_history
from services.user_store import decode_token, get_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

PIPELINE_TIMEOUT_S = 120
TOKEN_CHUNK_SIZE = 80
TOKEN_CHUNK_DELAY = 0.02


# ── Request schema ─────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    projectId: Optional[str] = None
    ticketId: Optional[str] = None
    title: str = ""


class SendMessageRequest(BaseModel):
    message: str
    # Chat by Project — depth analisis per pesan: low (ringan, default) |
    # medium (+tawaran investigasi) | thinking (pipeline insiden penuh)
    mode: Optional[str] = None


VALID_CHAT_MODES = ("low", "medium", "thinking")


# ── Helper ─────────────────────────────────────────────────────────────────────

async def _owned_session(session_id: str, user: dict):
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session tidak ditemukan")
    if session.get("userId") != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Bukan session milikmu")
    return session


async def _user_from_token(token: str):
    payload = decode_token(token)
    if payload is None:
        return None
    return await get_user(payload.get("sub", ""))


def _chunks(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _strip_ticket_context_prefix(text: str) -> str:
    """Buang prefix FE `[context: ...]` dari intent (redundan — server sudah inject
    ticket_context terstruktur via Fix #49). Robust terhadap kurung bersarang
    (`title="[ALERT] ..."`). Return teks user yang bersih."""
    if not (text or "").lstrip().startswith("[context:"):
        return text
    depth = 0
    for i, ch in enumerate(text):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[i + 1:].lstrip()
    return text


async def _resolve_workspace_id(project_id: Optional[str]) -> Optional[str]:
    """FE-7: projectId sesi chat → workspaceId untuk knowledge kontekstual."""
    if not project_id:
        return None
    try:
        from services.workspace_store import find_project_by_id
        project = await find_project_by_id(project_id)
        return (project or {}).get("workspaceId")
    except Exception as e:
        logger.warning(f"Resolve workspace gagal untuk project={project_id}: {e}")
        return None


async def _require_project_member(project_id: str, user: dict) -> dict:
    """Chat by Project: hanya owner/member workspace pemilik project yang boleh
    membuat sesi / mengirim pesan. Return doc project (untuk auto-title)."""
    from services.workspace_store import find_project_by_id, find_workspace_by_id, get_membership

    project = await find_project_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project tidak ditemukan")
    ws = await find_workspace_by_id(str(project.get("workspaceId", "")))
    if ws is None or get_membership(ws, str(user["_id"])) is None:
        raise HTTPException(status_code=403, detail="Kamu bukan member workspace ini")
    return project


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def _run_pipeline(
    session_id: str, message: str, workspace_id: Optional[str] = None,
    project_id: Optional[str] = None, chat_depth: str = "low",
) -> None:
    """Background task: jalankan graph → publish progress + token → persist jawaban.
    Slot antrian SUDAH diklaim endpoint /send (register) — di sini hanya konsumsi.
    Fix #49: sesi terikat tiket → tiket di-load & konteksnya di-inject ke state
    (preset_service_name/preset_trace_ids/ticket_context) agar analisis mengikuti
    subject tiket, bukan tebakan LLM dari teks bebas."""
    # Inisialisasi SEBELUM try agar handler except selalu bisa mereferensikannya
    # (bila error terjadi sebelum variabel di-assign di dalam try).
    request_id = None
    merged: dict = {}
    started_at = _now_iso()
    # Fix #113: locale user utk pesan fallback backend (timeout/error/empty)
    # get_session = chat_store (sudah di-import level modul) — session punya userId.
    from services.user_store import get_user_locale
    try:
        _sess = await get_session(session_id)
        locale = await get_user_locale((_sess or {}).get("userId"))
    except Exception:
        locale = "id"
    try:
        request_id = generate_request_id()

        # ── Audit: catat masuknya request chat ke request_logs (channel="chat") ──
        # Sender kaya identitas (session_id + user_id) agar follow-up chat
        # ter-isolasi per sesi — get_latest_request mencocokkan sender.session_id.
        session = await get_session(session_id)
        sender = {
            "channel": "chat",
            "name": "web",
            "session_id": session_id,
            "user_id": (session or {}).get("userId") or None,
        }
        await create_request_log(
            channel="chat",
            message_raw=message,
            sender=sender,
            request_id=request_id,
        )

        # ── Fix #49: konteks tiket dari sesi (1 sesi chat = 1 tiket) ────────────
        ticket_context = None
        preset_service_name = None
        preset_trace_ids = None
        try:
            ticket_id = (session or {}).get("ticketId")
            if ticket_id:
                from services.ticket_store import get_ticket
                ticket = await get_ticket(ticket_id)
                if ticket:
                    preset_service_name = (ticket.get("serviceName") or "").strip() or None
                    if ticket.get("traceId"):
                        preset_trace_ids = [str(ticket["traceId"])]
                    ticket_context = {
                        "ticket_id": str(ticket["_id"]),
                        "ticketNumber": ticket.get("ticketNumber"),
                        "title": ticket.get("title"),
                        "description": ticket.get("description"),
                        "serviceName": ticket.get("serviceName"),
                        "environment": ticket.get("environment"),
                        "severity": ticket.get("severity"),
                        "kind": ticket.get("kind"),
                        "source": ticket.get("source"),
                        "tags": ticket.get("tags"),
                        "status": ticket.get("status"),
                    }
        except Exception as e:
            logger.warning(f"Ticket context load gagal (non-fatal): {e}")

        cleaned_message = _strip_ticket_context_prefix(message)
        initial_state = {
            "intent": cleaned_message,
            "service_name": "",
            "collection_name": "",
            "request_id": request_id,
            "message_raw": cleaned_message,
            "sender": sender,
            "agents_visited": [],
            "is_follow_up": False,
            "follow_up_context": None,
            "reply_to_agent": False,
            "data_mode": False,
            "data_limit": None,
            "raw_documents": [],
            "query_used": {},
            "formatted_message": "",
            "telegram_sent": False,
            "telegram_error": None,
            "suppress_telegram": True,  # FE-5: jangan kirim ke grup Telegram
            "workspace_id": workspace_id,  # FE-7: konteks knowledge workspace (None = global)
            "project_id": project_id,  # FE-8: match knowledge per-service milik project
            "knowledge_context": None,
            "preset_service_name": preset_service_name,  # Fix #49: subject tiket
            "preset_trace_ids": preset_trace_ids,
            "ticket_context": ticket_context,
            "chat_depth": chat_depth,  # Chat by Project: low | medium | thinking
            "conversation_history": await build_conversation_history(session_id),
            "next_agent": "supervisor",
            "error": None,
        }

        publish(session_id, {"type": "status", "data": "Pipeline dimulai"})
        deadline = asyncio.get_event_loop().time() + PIPELINE_TIMEOUT_S
        stream = langgraph_app.astream(initial_state, stream_mode="updates")
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            try:
                update = await asyncio.wait_for(stream.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                break
            for node_name, delta in (update or {}).items():
                if not isinstance(delta, dict):
                    continue
                merged.update(delta)
                if node_name and node_name != "__end__":
                    publish(session_id, {"type": "agent", "data": str(node_name)})

        answer = (
            merged.get("formatted_message")
            or merged.get("correlation_result")
            or ""
        ).strip()
        if merged.get("error"):
            err_head = {
                "id": f"⚠️ Pipeline selesai dengan error: {merged['error']}",
                "en": f"⚠️ Pipeline finished with an error: {merged['error']}",
            }
            answer = err_head.get(locale, err_head["id"])
        if not answer:
            empty_msg = {
                "id": "⚠️ Agent tidak menghasilkan jawaban. Coba ulangi pertanyaanmu.",
                "en": "⚠️ The agent did not produce an answer. Try asking again.",
            }
            answer = empty_msg.get(locale, empty_msg["id"])

        # ── Audit: tutup request_logs (success/failed + snapshot data mentah) ──
        if merged.get("error"):
            await update_request_log(request_id, merged, "failed", error=merged["error"])
        else:
            await update_request_log(
                request_id,
                merged,
                "success",
                reply={"text": answer},
                raw_documents=merged.get("raw_documents"),
            )

        meta = {
            "request_id": request_id,
            "routing_strategy": merged.get("routing_strategy"),
            "episode_id": merged.get("episode_id"),
            "agents_visited": merged.get("agents_visited", []),
        }
        # Chat by Project: meta utk FE — chips saran follow-up + link tiket
        project_result = merged.get("project_result") or {}
        if isinstance(project_result, dict) and project_result:
            meta["ticket_refs"] = project_result.get("ticket_refs") or []
            meta["suggestions"] = project_result.get("suggestions") or []
        await add_message(session_id, "assistant", answer, meta=meta)

        for chunk in _chunks(answer, TOKEN_CHUNK_SIZE):
            publish(session_id, {"type": "token", "data": chunk})
            await asyncio.sleep(TOKEN_CHUNK_DELAY)
        publish(session_id, {"type": "done", "data": ""})
        logger.info(f"Chat pipeline done session={session_id} agents={merged.get('agents_visited')}")
    except asyncio.TimeoutError:
        # Fix #116: pesan timeout berdiagnosis — bila telemetri menunjukkan
        # panggilan LLM lambat/timeout selama request ini, sebut penyebabnya.
        # Pesan generik hanya untuk penyebab tak dikenal (butuh cek log backend).
        from services.llm_usage import slowest_failure_since
        culprit = await slowest_failure_since(started_at)
        if culprit:
            lat = culprit.get("latency_ms")
            lat_txt = f"{lat / 1000:.0f}s" if isinstance(lat, (int, float)) else "?"
            diag = {
                "id": (
                    "⚠️ Analisis melebihi batas waktu (120 detik) karena respons LLM lambat/timeout — "
                    f"panggilan `{culprit.get('agent') or 'llm'}` ({culprit.get('model')}) memakan ~{lat_txt}. "
                    "Coba lagi (free-tier sering pulih) atau gunakan model/provider yang lebih cepat di Management → API Keys."
                ),
                "en": (
                    "⚠️ Analysis exceeded the time limit (120 seconds) due to a slow/timed-out LLM call — "
                    f"`{culprit.get('agent') or 'llm'}` ({culprit.get('model')}) took ~{lat_txt}. "
                    "Try again (free tiers often recover) or switch to a faster model/provider in Management → API Keys."
                ),
            }
            fallback = diag.get(locale, diag["id"])
        else:
            generic = {
                "id": "⚠️ Analisis melebihi batas waktu (120 detik). Coba pertanyaan yang lebih spesifik.",
                "en": "⚠️ Analysis exceeded the time limit (120 seconds). Try a more specific question.",
            }
            fallback = generic.get(locale, generic["id"])
        try:
            await add_message(session_id, "assistant", fallback, meta={"timeout": True})
        except Exception:
            pass
        await update_request_log(request_id, merged or {}, "failed", error="Pipeline timeout (120s)")
        publish(session_id, {"type": "error", "data": "timeout"})
    except Exception as e:
        logger.error(f"Chat pipeline failed session={session_id}: {e}", exc_info=True)
        try:
            await add_message(
                session_id, "assistant",
                ({"id": f"⚠️ Terjadi error internal saat analisis: {str(e)[:200]}",
                  "en": f"⚠️ An internal error occurred during analysis: {str(e)[:200]}"}.get(locale)),
                meta={"error": True},
            )
        except Exception:
            pass
        await update_request_log(request_id, merged or {}, "failed", error=str(e)[:500])
        publish(session_id, {"type": "error", "data": str(e)[:200]})
    finally:
        # Tandai selesai dulu → /active langsung False meski registry
        # masih terpasang selama jeda drain reader (anti re-attach race, Fix #114)
        mark_done(session_id)
        publish_sentinel(session_id, DONE)
        # Beri waktu reader mengosongkan antrian sebelum unregister
        await asyncio.sleep(1.0)
        unregister(session_id)


# ── Session CRUD ───────────────────────────────────────────────────────────────

@router.post("/sessions", status_code=201)
async def create_chat_session(
    body: CreateSessionRequest,
    current_user: dict = Depends(get_current_user),
):
    project_doc = None
    if body.projectId:
        # Chat by Project: guard owner/member workspace + auto-title bermakna
        project_doc = await _require_project_member(body.projectId, current_user)
    session = await create_session(
        str(current_user["_id"]), body.projectId, body.ticketId, body.title
    )
    # Auto-title sesi project (bila user tidak memberi judul): "Chat Project · <nama> · <tgl>"
    if (
        project_doc is not None
        and not (body.title or "").strip()
        and (session.get("title") or "") in ("", "Chat baru")
    ):
        from datetime import datetime, timezone as _tz

        pname = project_doc.get("name") or "Project"
        tgl = datetime.now(_tz.utc).strftime("%d %b %Y")
        from services.chat_store import _now_iso, get_db, SESSIONS_COLLECTION

        title = f"Chat Project · {pname} · {tgl}"
        await get_db()[SESSIONS_COLLECTION].update_one(
            {"_id": session["_id"]}, {"$set": {"title": title}}
        )
        session["title"] = title
    return _public_session(session)


@router.get("/sessions")
async def my_chat_sessions(
    projectId: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    sessions = await list_sessions(str(current_user["_id"]), projectId, limit)
    return {"sessions": [_public_session(s) for s in sessions]}


@router.get("/sessions/{session_id}/messages")
async def chat_history(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _owned_session(session_id, current_user)
    messages = await get_messages(session_id)
    return {"messages": [_public_message(m) for m in messages]}


# ── Send + Stream ──────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/active")
async def session_stream_active(session_id: str, current_user: dict = Depends(get_current_user)):
    """True bila pipeline masih berjalan utk session ini (slot aktif).
    Dipakai FE setelah refresh agar tombol Stop tampil (bukan Send) saat
    respons server masih berjalan — Fix #114."""
    await _owned_session(session_id, current_user)
    return {"active": is_active(session_id)}


@router.post("/sessions/{session_id}/send")
async def send_chat_message(
    session_id: str,
    body: SendMessageRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """Persist pesan user + jalankan pipeline di background. Stream via GET /stream."""
    session = await _owned_session(session_id, current_user)  # Fix FE-8: tangkap return (dulu NameError → 500)
    message = (body.message or "").strip()
    if len(message) < 2:
        raise HTTPException(status_code=422, detail="Pesan minimal 2 karakter")
    chat_depth = (body.mode or "low").lower()
    if chat_depth not in VALID_CHAT_MODES:
        raise HTTPException(status_code=422, detail="mode harus salah satu dari: low, medium, thinking")
    project_id = (session.get("projectId") or "") or None
    # Chat by Project: guard owner/member workspace pemilik project
    if project_id:
        await _require_project_member(project_id, current_user)
    if is_active(session_id):
        raise HTTPException(status_code=409, detail="Tunggu respons selesai (atau stop stream)")

    # Klaim slot SEKALIGUS di endpoint (bukan di background task) — anti race
    # dua kirim super-cepat: keduanya tidak bisa lolos guard bersamaan.
    register(session_id)
    try:
        user_msg = await add_message(session_id, "user", message)
    except Exception:
        unregister(session_id)  # jangan tinggalkan slot menetap bila persist gagal
        raise
    background_tasks.add_task(
        _run_pipeline, session_id, message,
        await _resolve_workspace_id(project_id), project_id, chat_depth,
    )
    return {"messageId": str(user_msg["_id"])}


@router.get("/sessions/{session_id}/stream")
async def stream_chat(
    session_id: str,
    token: str = Query(...),
):
    """SSE stream respons session (EventSource tidak bisa set header → token via query)."""
    user = await _user_from_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Token tidak valid")
    session = await get_session(session_id)
    if session is None or session.get("userId") != str(user["_id"]):
        raise HTTPException(status_code=404, detail="Session tidak ditemukan")
    if not try_set_reader(session_id):
        raise HTTPException(status_code=409, detail="Stream sedang dibaca klien lain")

    async def event_generator():
        from services.chat_stream import get_queue
        queue = get_queue(session_id)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keepalive
                    continue
                if item == DONE:
                    yield "data: [DONE]\n\n"
                    return
                if isinstance(item, str) and item.startswith("__"):
                    yield f"data: {json.dumps({'type': 'error', 'data': 'internal'})}\n\n"
                    continue
                yield f"data: {item}\n\n"
        finally:
            release_reader(session_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Soft-delete session (Fix #118) ───────────────────────────────────────────

@router.delete("/sessions/{session_id}", status_code=200)
async def delete_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Soft-delete sesi chat project (owner only).

    - Sesi terikat tiket (ticketId) DITOLAK — arsip komunikasi tiket, bukan aset.
    - Sesi yang sedang berjalan (stream aktif) DITOLAK — tunggu/hentikan dulu.
    - Cascade flag deletedAt ke semua pesan agar history lenyap dari endpoint.
    - Data tetap utuh di DB untuk pemulihan manual via Mongo (tanpa endpoint restore).
    """
    session = await _owned_session(session_id, current_user)
    if session.get("ticketId"):
        raise HTTPException(
            status_code=409,
            detail="Sesi terikat tiket tidak bisa dihapus dari sini",
        )
    if is_active(session_id):
        raise HTTPException(
            status_code=409,
            detail="Tidak bisa menghapus sesi yang sedang berjalan — tunggu/hentikan stream dulu",
        )
    # Lepas registry stream kalau masih ada (defensive; biasanya sudah unregister setelah [DONE])
    try:
        unregister(session_id)
    except Exception:
        pass
    result = await soft_delete_session(session_id, str(current_user["_id"]))
    if result is None:
        raise HTTPException(status_code=404, detail="Session tidak ditemukan")
    return result
