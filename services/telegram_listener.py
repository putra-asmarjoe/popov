"""
Telegram Listener — Fix #40: MULTI-BOT polling dari DB (notification_targets).

PollerSupervisor tiap ±15s memuat channel telegram enabled lalu start/stop task
poller per notif_id secara dinamis (ikuti CRUD tanpa restart). Setiap poller
memiliki offset + dedup sendiri, memakai bot_token channel-nya, dan hanya
menerima pesan/callback dari chat tujuan channel tsb.

Semua balasan (laporan pipeline, notice error, pertanyaan diagnostik, feedback)
dikirim via bot channel ASAL — tidak ada lagi bot global .env.

⚠️ Tetap berjalan di proses FastAPI untuk sekarang: jangan scale API Pod >1
   sebelum listener dipindah ke worker terpisah (handoff scale-escalation).
"""
import asyncio
import hashlib
import httpx
import logging
from typing import Optional

from config.settings import settings
from graph.workflow import app as langgraph_app
from services.telegram_client import (
    send_message,
    answer_callback_query,
    edit_message_reply_markup,
    normalize_telegram_markdown,  # noqa: F401 (dipakai formatter lain via modul ini)
)
from services.request_log import (
    create_request_log,
    update_request_log,
    get_watchdog_alert,
)
from services.diagnostic_session import get_active_session, advance_session
from services.offer_session import get_offer, accept_offer, cancel_offer

logger = logging.getLogger(__name__)

SUPERVISOR_TICK_SECONDS = 15


def _api(token: str, method: str) -> str:
    return f"{settings.telegram_api_base}/bot{token}/{method}"


async def _get_bot_info(token: str) -> dict:
    """getMe untuk satu bot channel → {username, id}."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(_api(token, "getMe"))
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                return {
                    "username": data["result"].get("username", ""),
                    "id": data["result"].get("id"),
                }
        except Exception as e:
            logger.error(f"Failed to get bot info: {e}")
    return {"username": "", "id": None}


def _is_reply_to_agent(message: dict, bot_id) -> bool:
    """True bila pesan adalah balasan/reply (atau quote) terhadap pesan bot."""
    if bot_id is None:
        return False
    reply_to = message.get("reply_to_message") or {}
    if reply_to.get("from", {}).get("id") == bot_id:
        return True
    quote = message.get("quote") or {}
    if quote.get("from", {}).get("id") == bot_id:
        return True
    return False


def _extract_sender(message: dict) -> dict:
    """Ekstrak info pengirim dari message Telegram."""
    from_user = message.get("from", {})
    name = (from_user.get("first_name") or "") + " " + (from_user.get("last_name") or "")
    return {
        "channel": "telegram",
        "id": from_user.get("id"),
        "username": from_user.get("username"),
        "name": name.strip(),
        "chat_id": str(message.get("chat", {}).get("id")),
    }


async def _process_intent(
    intent: str,
    sender: dict = None,
    message_raw: str = None,
    reply_to_agent: bool = False,
    preset_service_name: str = None,
    preset_trace_ids: list = None,
    ctx: dict = None,
):
    """Run the langgraph pipeline for a given intent.

    ctx (Fix #40): {token, chat_id, notif_id, workspace_id} dari channel asal pesan —
    dipakai utk notice error/timeout DAN disuntik ke state agar telegram_agent
    membalas via channel yang sama (origin_notif_id).
    """
    ctx = ctx or {}
    logger.info(
        f"Telegram Listener[{ctx.get('notif_id', '-')}] → processing intent: '{intent}' "
        f"(reply_to_agent={reply_to_agent}, preset_service={preset_service_name}, "
        f"preset_trace_ids={preset_trace_ids})"
    )

    request_id = await create_request_log(
        channel="telegram",
        message_raw=message_raw or intent,
        sender=sender or {"channel": "telegram"},
    )

    initial_state = {
        "intent": intent,
        "service_name": preset_service_name or "",
        "collection_name": "",
        "request_id": request_id,
        "message_raw": message_raw or intent,
        "sender": sender or {"channel": "telegram"},
        "agents_visited": [],
        "is_follow_up": False,
        "follow_up_context": None,
        "reply_to_agent": reply_to_agent,
        "data_mode": False,
        "data_limit": None,
        "raw_documents": [],
        "query_used": {},
        "formatted_message": "",
        "telegram_sent": False,
        "telegram_error": None,
        "next_agent": "supervisor",
        "error": None,
        "trace_id": preset_trace_ids[0] if preset_trace_ids else None,
        "preset_trace_ids": preset_trace_ids or [],
        "preset_service_name": preset_service_name or None,
        # Fix #40: konteks channel asal — bukan lagi global None
        "workspace_id": ctx.get("workspace_id"),
        "observ_id": None,
        "episode_id": None,
        "second_brain_context": None,
        "origin_notif_id": ctx.get("notif_id"),
    }

    async def _notice(text: str):
        try:
            await send_message(text, chat_id=str(ctx.get("chat_id") or ""), bot_token=ctx.get("token") or "")
        except Exception as e2:
            logger.error(f"Failed to send notice via channel {ctx.get('notif_id')}: {e2}")

    try:
        result = await asyncio.wait_for(langgraph_app.ainvoke(initial_state), timeout=120)
        if result.get("error"):
            logger.info(f"Telegram Listener → pipeline finished with error: '{result['error']}'")
            await update_request_log(request_id, result, "failed", error=result["error"])
            await _notice(f"❌ *[ERROR]* `{intent}`\n\n{result['error'][:400]}")
        else:
            logger.info(f"Telegram Listener → successfully processed intent: '{intent}'")
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
    except asyncio.TimeoutError:
        logger.error(f"Telegram Listener → pipeline timeout for intent: '{intent}'")
        await update_request_log(request_id, initial_state, "failed", error="Pipeline timeout (120s)")
        await _notice(f"⚠️ *[TIMEOUT]* Pipeline tidak selesai dalam 120 detik untuk intent:\n`{intent}`")
    except Exception as e:
        logger.error(f"Telegram Listener → Graph execution failed: {e}", exc_info=True)
        await update_request_log(request_id, initial_state, "failed", error=str(e))
        await _notice(
            f"❌ *[ERROR]* Pipeline gagal diproses:\n`{intent}`\n\n"
            f"Error: `{str(e)[:200]}`"
        )


class ChannelPoller:
    """Long-polling untuk SATU channel telegram (satu bot, satu chat, satu offset)."""

    def __init__(self, channel: dict):
        self.channel = dict(channel)
        self.notif_id = channel.get("notif_id", "?")
        self.token = ((channel.get("config") or {}).get("telegram") or {}).get("bot_token") or ""
        self.target_chat_id = str(((channel.get("config") or {}).get("telegram") or {}).get("chat_id") or "")
        self.workspace_id = channel.get("workspace_id")
        self.offset: Optional[int] = None
        self.timeout = 25  # seconds (long poll)
        self.seen_update_ids: set[int] = set()
        self.seen_message_keys: set[str] = set()
        self.bot_username = ""
        self.bot_id = None

    @property
    def mention_tag(self) -> str:
        return f"@{self.bot_username}"

    def _ctx(self) -> dict:
        return {
            "token": self.token,
            "chat_id": self.target_chat_id,
            "notif_id": self.notif_id,
            "workspace_id": self.workspace_id,
        }

    async def run(self) -> None:
        name = self.channel.get("name", self.notif_id)
        info = await _get_bot_info(self.token)
        if not info["username"]:
            logger.warning(f"[{name}] getMe gagal — cek ulang dalam 60s (token salah / network?)")
            await asyncio.sleep(60)
            return
        self.bot_username = info["username"]
        self.bot_id = info["id"]
        logger.info(
            f"[{name}] polling @{self.bot_username} mulai (chat {self.target_chat_id}, "
            f"ws={self.workspace_id or '-'})"
        )

        async with httpx.AsyncClient(timeout=self.timeout + 5) as client:
            while True:
                try:
                    params = {"timeout": self.timeout, "allowed_updates": ["message", "callback_query"]}
                    if self.offset:
                        params["offset"] = self.offset

                    resp = await client.get(_api(self.token, "getUpdates"), params=params)

                    # Token dicabut/dirotasi → refresh kredensial dari DB lalu reconnect
                    if resp.status_code in (401, 404):
                        logger.warning(f"[{name}] unauthorized ({resp.status_code}) — refresh channel dari DB")
                        fresh = await self._reload_channel()
                        if fresh is None:
                            logger.info(f"[{name}] channel dihapus/disabled — poller berhenti")
                            return
                        await asyncio.sleep(5)
                        return  # supervisor akan menjalankan ulang dengan config baru

                    resp.raise_for_status()
                    data = resp.json()
                    if not data.get("ok"):
                        logger.error(f"[{name}] Telegram getUpdates error: {data}")
                        await asyncio.sleep(5)
                        continue

                    for update in data.get("result", []):
                        upd_id = update.get("update_id")
                        if upd_id in self.seen_update_ids:
                            self.offset = upd_id + 1
                            continue
                        self.seen_update_ids.add(upd_id)
                        if len(self.seen_update_ids) > 200:
                            self.seen_update_ids = set(list(self.seen_update_ids)[-100:])
                        self.offset = upd_id + 1
                        try:
                            await self._handle_update(update, client)
                        except Exception as e:
                            logger.error(f"[{name}] handle update gagal: {e}", exc_info=True)

                except asyncio.CancelledError:
                    logger.info(f"[{name}] Telegram polling cancelled.")
                    raise
                except httpx.ReadTimeout:
                    # Normal for long polling
                    continue
                except Exception as e:
                    logger.error(f"[{name}] Error in Telegram polling loop: {e}")
                    await asyncio.sleep(5)

    async def _reload_channel(self) -> Optional[dict]:
        """Ambil ulang dokumen channel dari DB (bila masih enabled)."""
        from services.notification_store import get_notification

        doc = await get_notification(self.notif_id)
        if not doc or doc.get("enabled") is False:
            return None
        self.channel = doc
        self.token = ((doc.get("config") or {}).get("telegram") or {}).get("bot_token") or ""
        self.target_chat_id = str(((doc.get("config") or {}).get("telegram") or {}).get("chat_id") or "")
        return doc

    # ── Update processing ────────────────────────────────────────────────────

    async def _handle_update(self, update: dict, client: httpx.AsyncClient) -> None:
        # 1. Inline keyboard buttons (callback_query)
        callback_q = update.get("callback_query")
        if callback_q:
            cb_msg = callback_q.get("message", {})
            chat_id = str(cb_msg.get("chat", {}).get("id"))
            if chat_id != self.target_chat_id:
                return
            await self._handle_callback(callback_q, chat_id)
            return

        # 2. Normal messages (mention / jawaban sesi diagnostik)
        message = update.get("message")
        if not message:
            return
        chat_id = str(message.get("chat", {}).get("id"))
        if chat_id != self.target_chat_id:
            return
        await self._handle_message(message, chat_id)

    async def _handle_callback(self, callback_q: dict, chat_id: str) -> None:
        query_id = callback_q.get("id")
        cb_data = callback_q.get("data", "")
        cb_msg = callback_q.get("message", {})
        sender = _extract_sender({"from": callback_q.get("from", {}), "chat": cb_msg.get("chat", {})})
        ctx = self._ctx()

        if cb_data.startswith("detail:"):
            parts = cb_data.split(":", 1)[1].split(":", 1)
            service = parts[0]
            alert_id = parts[1] if len(parts) > 1 else None

            preset_trace_ids = []
            if alert_id:
                alert_doc = await get_watchdog_alert(alert_id)
                if alert_doc:
                    service = alert_doc.get("service_name") or service
                    preset_trace_ids = alert_doc.get("trace_ids") or (
                        [alert_doc["trace_id"]] if alert_doc.get("trace_id") else []
                    )
                    logger.info(
                        f"Callback Cek Detail alert_id={alert_id} → "
                        f"service='{service}', trace_ids={preset_trace_ids}"
                    )

            await answer_callback_query(query_id, f"🔍 Memproses cek detail untuk '{service}'...", bot_token=self.token)
            intent_str = f"cek error pada {service}"
            asyncio.create_task(
                _process_intent(
                    intent_str,
                    sender=sender,
                    message_raw=f"[Button Cek Detail] {intent_str}",
                    preset_service_name=service,
                    preset_trace_ids=preset_trace_ids,
                    ctx=ctx,
                )
            )
        elif cb_data.startswith("skip:"):
            service = cb_data.split(":", 1)[1]
            await answer_callback_query(query_id, f"⏭️ Insiden '{service}' di-skip.", bot_token=self.token)
        # FASE 6A: Dynamic buttons — health_check / metrics / rawlog
        elif cb_data.startswith("health_check:"):
            parts = cb_data.split(":")
            service = parts[1] if len(parts) > 1 else "unknown"
            await answer_callback_query(query_id, f"🏥 Cek health untuk '{service}'...", bot_token=self.token)
            intent_str = f"cek koneksi semua db untuk {service}" if service and service != "unknown" else "cek koneksi semua db"
            asyncio.create_task(_process_intent(intent_str, sender=sender, message_raw=f"[Button Health] {intent_str}", ctx=ctx))
        elif cb_data.startswith("metrics:"):
            service = cb_data.split(":", 1)[1] if ":" in cb_data else "unknown"
            await answer_callback_query(query_id, f"📊 Cek metrics untuk '{service}'...", bot_token=self.token)
            intent_str = f"cek metrics {service}" if service and service != "unknown" else "cek metrics"
            asyncio.create_task(_process_intent(intent_str, sender=sender, message_raw=f"[Button Metrics] {intent_str}", ctx=ctx))
        elif cb_data.startswith("rawlog:"):
            service = cb_data.split(":", 1)[1] if ":" in cb_data else "unknown"
            await answer_callback_query(query_id, f"📋 Ambil log mentah untuk '{service}'...", bot_token=self.token)
            intent_str = f"berikan 5 data terakhir {service}" if service and service != "unknown" else "berikan 5 data terakhir"
            asyncio.create_task(_process_intent(intent_str, sender=sender, message_raw=f"[Button RawLog] {intent_str}", ctx=ctx))
        # Offer Session callbacks offer:{id}:accept|cancel (Tahap 3)
        elif cb_data.startswith("offer:"):
            parts = cb_data.split(":", 2)
            offer_id = parts[1] if len(parts) > 1 else ""
            action = parts[2] if len(parts) > 2 else ""
            offer = await get_offer(offer_id)
            if not offer:
                await answer_callback_query(query_id, "⚠️ Tawaran tidak ditemukan/kedaluwarsa.", bot_token=self.token)
            elif action == "accept":
                await accept_offer(offer_id)
                await answer_callback_query(query_id, "✅ Tawaran diterima, memproses...", bot_token=self.token)
                if offer.get("type") == "investigate":
                    svc = (offer.get("params") or {}).get("service_name") or "unknown"
                    it = (offer.get("params") or {}).get("intent") or f"cek error pada {svc}"
                    asyncio.create_task(
                        _process_intent(
                            it,
                            sender=sender,
                            message_raw=f"[Offer Accept] {it}",
                            preset_service_name=svc,
                            ctx=ctx,
                        )
                    )
                else:
                    await send_message(
                        "Tawaran aksi tiket hanya berlaku di chat web.",
                        chat_id=str(chat_id), bot_token=self.token,
                    )
            elif action == "cancel":
                await cancel_offer(offer_id)
                await answer_callback_query(query_id, "❌ Tawaran dibatalkan.", bot_token=self.token)
            else:
                await answer_callback_query(query_id, "⚠️ Format tawaran tidak valid.", bot_token=self.token)
        # FASE 6C: Diagnostic session callbacks diag:* (Fix #40: sesi per chat+notif)
        elif cb_data.startswith("diag:"):
            await answer_callback_query(query_id, "⏳ Memproses...", bot_token=self.token)
            sess = await get_active_session(chat_id, self.notif_id)
            if not sess:
                await send_message(
                    "ℹ️ Sesi diagnostik tidak ditemukan atau sudah expired.",
                    chat_id=chat_id,
                    bot_token=self.token,
                )
            else:
                res = await advance_session(sess["session_id"], cb_data)
                if res.get("next_question"):
                    btns = res.get("next_buttons")
                    markup = {"inline_keyboard": [btns]} if btns else None
                    try:
                        await send_message(
                            res["next_question"], chat_id=chat_id, reply_markup=markup, bot_token=self.token
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send diagnostic next question: {e}")
                trig = res.get("trigger_pipeline")
                if trig and isinstance(trig, dict):
                    intent_diag = trig.get("intent") or f"cek error pada {sess.get('service_name')}"
                    asyncio.create_task(_process_intent(
                        intent_diag,
                        sender=sender,
                        message_raw=f"[Diagnostic] {intent_diag}",
                        preset_service_name=trig.get("service_name") or sess.get("service_name"),
                        ctx=ctx,
                    ))
                if res.get("completed") and not res.get("next_question"):
                    await send_message("✅ Sesi diagnostik selesai. Terima kasih!", chat_id=chat_id, bot_token=self.token)
        elif cb_data.startswith("feedback:"):
            # Format: feedback:correct:EP-2026-08-21-A7F3  atau feedback:wrong:EP-...
            parts = cb_data.split(":")
            if len(parts) == 3:
                _, feedback_type, episode_id = parts
                from services.second_brain import update_episode_feedback

                success = await update_episode_feedback(episode_id, feedback_type)
                if success:
                    label = "✅ Ditandai: Analisis Tepat" if feedback_type == "correct" else "❌ Ditandai: Analisis Meleset"
                    new_kb = {"inline_keyboard": [[{"text": label, "callback_data": "feedback:done"}]]}
                    msg_id = cb_msg.get("message_id")
                    try:
                        if msg_id:
                            await edit_message_reply_markup(chat_id, msg_id, new_kb, bot_token=self.token)
                    except Exception as e:
                        logger.warning(f"Failed to edit feedback keyboard: {e}")
                    await answer_callback_query(
                        query_id,
                        "✅ Feedback disimpan!" if feedback_type == "correct" else "📝 Ditandai kurang tepat.",
                        bot_token=self.token,
                    )
                else:
                    await answer_callback_query(query_id, "ℹ️ Feedback sudah pernah diberikan.", bot_token=self.token)
            else:
                await answer_callback_query(query_id, "⚠️ Format feedback tidak valid.", bot_token=self.token)

    async def _handle_message(self, message: dict, chat_id: str) -> None:
        ctx = self._ctx()

        # FASE 6C: sesi diagnostik aktif diprioritaskan (Fix #40: scoped chat+notif)
        try:
            diag_sess = await get_active_session(chat_id, self.notif_id)
            if diag_sess:
                text_diag = message.get("text", "") or ""
                stage = diag_sess.get("stage", "")
                is_endpoint_stage = stage == "awaiting_endpoint_detail"
                text_lower_diag = text_diag.lower()
                mention_lower_diag = self.mention_tag.lower()
                has_mention = mention_lower_diag in text_lower_diag
                should_handle_as_diag = is_endpoint_stage or not has_mention
                if should_handle_as_diag and text_diag.strip():
                    res = await advance_session(diag_sess["session_id"], text_diag)
                    if res.get("next_question"):
                        btns = res.get("next_buttons")
                        markup = {"inline_keyboard": [btns]} if btns else None
                        try:
                            await send_message(
                                res["next_question"], chat_id=chat_id, reply_markup=markup, bot_token=self.token
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send diag next question: {e}")
                    trig = res.get("trigger_pipeline")
                    if trig and isinstance(trig, dict):
                        intent_diag = trig.get("intent") or f"cek error pada {diag_sess.get('service_name')}"
                        asyncio.create_task(_process_intent(
                            intent_diag,
                            sender=_extract_sender(message),
                            message_raw=f"[Diagnostic] {intent_diag}",
                            preset_service_name=trig.get("service_name") or diag_sess.get("service_name"),
                            ctx=ctx,
                        ))
                    if res.get("completed") and not res.get("next_question"):
                        try:
                            await send_message(
                                "✅ Sesi diagnostik selesai. Terima kasih!", chat_id=chat_id, bot_token=self.token
                            )
                        except Exception:
                            pass
                    return  # jangan proses sebagai intent baru
        except Exception as e:
            logger.warning(f"Diagnostic session check failed: {e}")

        text = message.get("text", "")
        # Dedup per message_id (Telegram kadang resend bila ack lambat)
        msg_id_key = f"{chat_id}:{message.get('message_id')}:{text[:80]}"
        if msg_id_key in self.seen_message_keys:
            logger.info(f"Skipping duplicate message {msg_id_key}")
            return
        self.seen_message_keys.add(msg_id_key)
        if len(self.seen_message_keys) > 200:
            self.seen_message_keys = set(list(self.seen_message_keys)[-100:])
        text_lower = text.lower()
        mention_lower = self.mention_tag.lower()
        if mention_lower in text_lower:
            idx = text_lower.find(mention_lower)
            intent = (text[:idx] + text[idx + len(mention_lower):]).strip()
            if intent:
                sender = _extract_sender(message)
                reply_to_agent = _is_reply_to_agent(message, self.bot_id)
                asyncio.create_task(
                    _process_intent(
                        intent, sender=sender, message_raw=text, reply_to_agent=reply_to_agent, ctx=ctx
                    )
                )


class PollerSupervisor:
    """Kelola siklus hidup poller per-channel (Fix #40).

    Tiap ±15s: load channel telegram enabled dari DB → start poller baru,
    stop poller channel yang hilang/disabled, dan RESTART poller bila config
    berubah (bot_token/chat_id/workspace dirotasi).
    """

    def __init__(self):
        self._tasks: dict[str, tuple[str, asyncio.Task]] = {}  # notif_id → (fingerprint, task)

    @staticmethod
    def _fingerprint(channel: dict) -> str:
        cfg = ((channel.get("config") or {}).get("telegram") or {})
        raw = f"{cfg.get('bot_token', '')}|{cfg.get('chat_id', '')}|{channel.get('workspace_id', '')}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    async def run_forever(self) -> None:
        logger.info("PollerSupervisor dimulai (multi-bot, sumber: notification_targets)")
        while True:
            try:
                from services.notification_store import list_channels_internal

                channels = [
                    c for c in await list_channels_internal(channel="telegram", enabled_only=True)
                    if ((c.get("config") or {}).get("telegram") or {}).get("bot_token")
                ]
            except Exception as e:
                logger.error(f"PollerSupervisor gagal load channels: {e}")
                channels = []

            desired = {}
            for ch in channels:
                nid = ch.get("notif_id")
                if nid:
                    desired[nid] = ch

            # Stop yang tidak ada / disabled
            for nid in list(self._tasks.keys()):
                if nid not in desired:
                    fp, task = self._tasks.pop(nid)
                    if not task.done():
                        task.cancel()
                    logger.info(f"PollerSupervisor: stop poller {nid}")

            # Start baru / restart bila config berubah
            for nid, ch in desired.items():
                fp = self._fingerprint(ch)
                existing = self._tasks.get(nid)
                if existing is None:
                    task = asyncio.create_task(ChannelPoller(ch).run())
                    self._tasks[nid] = (fp, task)
                    logger.info(f"PollerSupervisor: start poller {nid} ('{ch.get('name')}')")
                elif existing[0] != fp:
                    old_fp, old_task = self._tasks.pop(nid)
                    if not old_task.done():
                        old_task.cancel()
                    task = asyncio.create_task(ChannelPoller(ch).run())
                    self._tasks[nid] = (fp, task)
                    logger.info(f"PollerSupervisor: restart poller {nid} (config berubah)")

            # Reap task selesai (mis. reload path return) supaya bisa distart ulang tick berikutnya
            for nid in list(self._tasks.keys()):
                _, task = self._tasks[nid]
                if task.done():
                    err = task.exception() if not task.cancelled() else None
                    if err:
                        logger.warning(f"Poller {nid} mati: {err} — akan di-restart tick berikutnya")
                    self._tasks.pop(nid)

            if not desired:
                logger.info("PollerSupervisor: 0 channel telegram enabled — Telegram polling idle")

            await asyncio.sleep(SUPERVISOR_TICK_SECONDS)


_supervisor = PollerSupervisor()


async def start_polling():
    """Entry-point lifespan (dipertahankan namanya agar main.py stabil)."""
    await _supervisor.run_forever()
