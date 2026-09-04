import asyncio
import json
import logging
from typing import List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from state.schema import AgentState
from services.doc_loader import build_agent_context, get_service_doc
from services.request_log import get_incident_history
from services.llm_factory import get_chat_llm
from services.offer_planner import build_investigate_offer, render_offer_question
from services.offer_session import create_offer
from services.prompt_loader import render as render_prompt
from agents.correlation_agent import llm_unavailable_note_for  # Fix #53/#113: pesan LLM down bilingual

logger = logging.getLogger(__name__)


# ── CHATFLOW V2.1 (Tahap 1C): blok confidence bilingual ───────────────────────
_CONFIDENCE_BLOCK_TEXTS = {
    "id": {
        "header": "⚠️ **Confidence analisis: {pct}%**",
        "gaps_title": "Data yang belum diperiksa:",
        "suggest_title": "Lanjutkan investigasi:",
    },
    "en": {
        "header": "⚠️ **Analysis confidence: {pct}%**",
        "gaps_title": "Data not yet examined:",
        "suggest_title": "Continue investigation:",
    },
}


def _append_confidence_block(formatted: str, confidence: float, data_gaps: list,
                             suggested_next: list, reply_language: str) -> str:
    """Tambahkan blok confidence bila confidence < threshold dan ada gaps.
    Bilingual via dict (bukan if/else). Tidak mengubah format utama."""
    from state.constants import CONFIDENCE_THRESHOLD

    if confidence >= CONFIDENCE_THRESHOLD or not data_gaps:
        return formatted
    texts = _CONFIDENCE_BLOCK_TEXTS.get(
        "id" if reply_language.lower() == "bahasa indonesia" else "en",
        _CONFIDENCE_BLOCK_TEXTS["en"],
    )
    header = f"\n\n---\n{texts['header'].format(pct=int(confidence * 100))}"
    gap_section = f"\n{texts['gaps_title']}\n" + "\n".join(
        f"• {(g.get('description') if isinstance(g, dict) else g)}" for g in data_gaps
    )
    suggest_section = ""
    if suggested_next:
        suggest_section = f"\n\n{texts['suggest_title']}\n" + "\n".join(
            f"→ {s}" for s in suggested_next
        )
    return formatted + header + gap_section + suggest_section


# ── Offer investigate gating (Fix #189) ──────────────────────────────────────
_PLACEHOLDER_SERVICES = {"", "unknown", "null", "-", "n/a", "none", "undefined"}

# Catatan span OTel setelah laporan insiden — bilingual (Fix #201: awalnya hardcode ID)
_SPAN_OTEL_NOTE = {
    "en": "📡 _Span detail OTel was also analyzed in the root cause assessment_",
    "id": "📡 _Span detail OTel turut dianalisis dalam root cause assessment_",
}


def _is_placeholder_service(name: str) -> bool:
    """True bila service name placeholder — investigasi "unknown" = noise, jangan tawari."""
    return (name or "").strip().lower() in _PLACEHOLDER_SERVICES


def _investigate_offer_has_value(state: dict) -> bool:
    """Offer "investigate lebih dalam" HANYA berarti bila investigasi belum dalam:
    masih ada data_gaps, ATAU confidence < threshold, ATAU planned_nodes belum
    mencakup full set collector (ada lane yang di-skip/narrow)."""
    from agents.investigation_planner import FULL_SET

    if state.get("data_gaps"):
        return True
    confidence = float(state.get("investigation_confidence") or 1.0)
    if confidence < 0.80:
        return True
    planned = state.get("planned_nodes") or []
    if planned and not set(FULL_SET).issubset(set(planned)):
        return True
    return False


async def _already_offered_investigate(session_id: str) -> bool:
    """Anti-reoffer: sudah pernah dibuat offer investigate utk sesi ini (status bukan cancelled)
    → jangan tawarkan lagi. Bunuh loop "ya" yang memproduksi laporan identik berulang."""
    try:
        from services.offer_session import has_offer_type
        return await has_offer_type(session_id=session_id, type_="investigate")
    except Exception as e:
        logger.warning(f"[Offer] already-offered check failed: {e}")
        return False


async def _resolve_channels_for_state(state) -> List[dict]:
    """Channel tujuan delivery (Fix #40, broadcast):
    - origin_notif_id (mention/callback/webhook via channel tertentu) → kirim balik ke
      channel ASAL saja.
    - selain itu → broadcast set: channel project-linked ∪ workspace-wide.
    Tanpa env fallback — murni DB (notification_targets).
    """
    from services.notification_store import get_notification, resolve_channels

    origin_notif_id = state.get("origin_notif_id")
    if origin_notif_id:
        doc = await get_notification(str(origin_notif_id))
        if doc and doc.get("enabled", True):
            return [doc]
        logger.warning(f"[Notification] origin channel {origin_notif_id} tidak ditemukan/disabled")
        return []
    return await resolve_channels(state.get("workspace_id"), state.get("project_id"))


async def _deliver(state, text: str, reply_markup: Optional[dict] = None):
    """Kirim pesan ke Telegram, kecuali di-suppress (channel chat web — FE-5).

    Fix #40: broadcast ke semua channel match (atau channel asal bila ada
    origin_notif_id). Returns (success, error_str).
    """
    if state.get("suppress_telegram"):
        logger.info("Telegram delivery suppressed (chat channel) — formatted_message tetap dihasilkan")
        return False, None
    try:
        channels = await _resolve_channels_for_state(state)
    except Exception as e:
        logger.warning(f"[Notification] resolve gagal: {e}")
        channels = []
    if not channels:
        # Fix #40: tanpa channel DB tidak ada lagi fallback .env global
        logger.warning("[Notification] tidak ada channel match — laporan TIDAK terkirim (murni DB)")
        return False, "Tidak ada channel notifikasi untuk konteks ini"
    try:
        from services.telegram_client import broadcast

        sent = await broadcast(channels, text, reply_markup=reply_markup)
        return sent > 0, None
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False, str(e)


# Prompt format insiden & mode lain dipindah ke file-driven: prompts/telegram_*.md
# (editable, hot-reload via POST /prompts/reload).


_BTN_TEXTS = {
    "en": {
        "health": "🏥 Check Health Dependency",
        "trace_latest": "🔍 View Latest Trace",
        "trace_detail": "🔍 View Trace Detail",
        "metrics": "📊 View Metrics",
        "trace": "🔍 Check Trace",
        "rawlog": "📋 Raw Log",
        "correct": "✅ Analysis Accurate",
        "wrong": "❌ Analysis Missed",
    },
    "id": {
        "health": "🏥 Cek Health Dependency",
        "trace_latest": "🔍 Lihat Trace Terbaru",
        "trace_detail": "🔍 Lihat Trace Detail",
        "metrics": "📊 Lihat Metrics",
        "trace": "🔍 Cek Trace",
        "rawlog": "📋 Log Mentah",
        "correct": "✅ Analisis Tepat",
        "wrong": "❌ Analisis Meleset",
    },
}


def _build_dynamic_buttons(state: dict, locale: str = "en") -> Optional[dict]:
    """
    FASE 6A: Build tombol dinamis berdasarkan root_cause_assessment.
    Baris aksi (row 0) berubah per root cause, baris feedback selalu di bawah jika episode_id ada.
    locale (Fix bahasa): label tombol bilingual (en/id) — bukan hardcode Indonesia.
    """
    service = state.get("service_name") or ""
    root_cause = state.get("root_cause_assessment") or "unknown"
    episode_id = state.get("episode_id")
    bt = _BTN_TEXTS.get(locale, _BTN_TEXTS["en"])

    # Baris aksi — dinamis
    if root_cause == "downstream":
        action_row = [
            {"text": bt["health"], "callback_data": f"health_check:{service}:all"},
            {"text": bt["trace_latest"], "callback_data": f"detail:{service}:latest"},
        ]
    elif root_cause == "service-fault":
        action_row = [
            {"text": bt["trace_detail"], "callback_data": f"detail:{service}:latest"},
            {"text": bt["metrics"], "callback_data": f"metrics:{service}"},
        ]
    else:  # unknown
        action_row = [
            {"text": bt["trace"], "callback_data": f"detail:{service}:latest"},
            {"text": bt["rawlog"], "callback_data": f"rawlog:{service}"},
        ]

    buttons: list[list[dict]] = [action_row]

    # Baris feedback — hanya jika episode berhasil disimpan
    if episode_id:
        buttons.append([
            {"text": bt["correct"], "callback_data": f"feedback:correct:{episode_id}"},
            {"text": bt["wrong"], "callback_data": f"feedback:wrong:{episode_id}"},
        ])

    return {"inline_keyboard": buttons}


async def response_agent(state: AgentState) -> dict:
    """
    1. Jika ini task Health Check (state memuat health_result): Format laporan status konektivitas & latency.
    2. Jika ini task Log Analysis: Load konteks dokumen + LLM analisis log error.
    3. Kirim notifikasi via Telegram Bot API.
    """
    service_name = state.get("resolved_service_name") or state.get("service_name", "unknown")
    intent = state.get("intent", "")
    documents = state.get("raw_documents", [])
    health_result = state.get("health_result")
    is_follow_up = state.get("is_follow_up", False)
    follow_up_context = state.get("follow_up_context")
    data_mode = state.get("data_mode", False)
    span_mode = state.get("span_mode", False)
    agents_visited = state.get("agents_visited", []) + ["response_agent"]

    # 0. Handling Span Detail (span_agent) — ringkasan "apa yang sebenarnya terjadi" dari traceId
    # Fix bahasa ID (CPRO-19): HANYA jalur span MANDIRI (detail traceId). Saat span adalah
    # anggota fan-out incident (ada triage_result/planned_nodes), format incident normal
    # (reply_language eksplisit) — kalau tidak, `span_mode` bocor dari span_agent → prompt
    # span (tanpa reply_language) dipakai → model default ke bahasa Indonesia.
    if span_mode and not state.get("triage_result") and not state.get("correlation_result"):
        logger.info("TelegramAgent formatting span detail (traceId lookup)")
        span_summary = state.get("span_summary") or "Tidak ada data trace."
        span_data = state.get("span_data")
        trace_id = state.get("trace_id")
        # Grounding docs untuk RCA lebih dalam (service dominan dari trace)
        span_service = state.get("service_name") or state.get("preset_service_name") or "unknown"
        # infer dari spans jika service_name masih kosong
        if (not span_service or span_service == "unknown") and span_data:
            spans_tmp = span_data.get("spans") or []
            if spans_tmp:
                from collections import Counter
                svc_counts = Counter(
                    (s.get("service") or "") for s in spans_tmp if isinstance(s, dict) and s.get("service")
                )
                if svc_counts:
                    span_service = svc_counts.most_common(1)[0][0].lower().replace("-", "_")
        doc_context = ""
        # Fix bahasa: jalur span mandiri juga wajib ikut bahasa user (detect → preferensi),
        # sama seperti format incident — bukan default model. Telegram → locale owner
        # workspace (pola Fix #140), web chat → isi percakapan + preferensi user.
        try:
            from services.conversation import detect_chat_locale
            from services.user_store import get_user_locale
            if state.get("suppress_telegram"):
                _ulocale = await get_user_locale((state.get("sender") or {}).get("user_id"))
                _span_locale = detect_chat_locale(state.get("conversation_history") or [], default=_ulocale)
            else:
                from services.locale_pref import get_workspace_locale
                _span_locale = await get_workspace_locale(state.get("workspace_id"))
        except Exception:
            _span_locale = "id"
        try:
            formatted = await _format_span_with_llm(intent, trace_id, span_summary, span_data, doc_context,
                                                history=state.get("conversation_history"),
                                                reply_language=("English" if _span_locale == "en" else "Bahasa Indonesia"))
        except Exception as e:
            logger.error(f"Span LLM formatting failed: {e}")
            formatted = _format_span_fallback(trace_id, span_summary) + await llm_unavailable_note_for(state)

        success, send_error = await _deliver(state, formatted)
        return {
            "formatted_message": formatted,
            "telegram_sent": success,
            "telegram_error": send_error,
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    # 0. Handling Ticket Agent (pengelolaan tiket) — konfirmasi deterministik, tanpa LLM
    if state.get("ticket_result") is not None:
        logger.info("TelegramAgent delivering ticket result (deterministic)")
        formatted = state.get("formatted_message") or "Tiket diproses."
        success, send_error = await _deliver(state, formatted)
        return {
            "formatted_message": formatted,
            "telegram_sent": success,
            "telegram_error": send_error,
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    # 0. Handling Data Retrieval (data_agent) — tampilkan data mentah terbaru
    if data_mode:
        logger.info(f"TelegramAgent formatting data retrieval, docs={len(documents)}")
        # Fix bahasa: jalur data wajib reply_language eksplisit (pola Fix #201/#217).
        try:
            from services.conversation import detect_chat_locale
            from services.user_store import get_user_locale
            _dloc = detect_chat_locale(
                state.get("conversation_history") or [],
                default=await get_user_locale((state.get("sender") or {}).get("user_id")),
            )
        except Exception:
            _dloc = "id"
        try:
            formatted = await _format_data_with_llm(
                intent, service_name, documents,
                reply_language=("English" if _dloc == "en" else "Bahasa Indonesia"),
            )
        except Exception as e:
            logger.error(f"Data LLM formatting failed: {e}")
            formatted = _format_data_fallback(service_name, documents, "id" if _dloc == "id" else "en") \
                + await llm_unavailable_note_for(state)

        success, send_error = await _deliver(state, formatted)
        return {
            "formatted_message": formatted,
            "telegram_sent": success,
            "telegram_error": send_error,
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    # 0. Handling Follow-up Question (Phase 1)
    if is_follow_up:
        logger.info("TelegramAgent handling follow-up question")
        # Fix bahasa: jalur follow-up wajib reply_language eksplisit (pola #201/#222).
        try:
            from services.conversation import detect_chat_locale
            from services.user_store import get_user_locale
            _floc = detect_chat_locale(
                state.get("conversation_history") or [],
                default=await get_user_locale((state.get("sender") or {}).get("user_id")),
            )
        except Exception:
            _floc = "id"
        try:
            formatted = await _format_follow_up(
                intent, follow_up_context,
                reply_language=("English" if _floc == "en" else "Bahasa Indonesia"),
            )
        except Exception as e:
            logger.error(f"Follow-up LLM formatting failed: {e}")
            formatted = _format_follow_up_fallback(follow_up_context, "id" if _floc == "id" else "en") \
                + await llm_unavailable_note_for(state)

        success, send_error = await _deliver(state, formatted)
        return {
            "formatted_message": formatted,
            "telegram_sent": success,
            "telegram_error": send_error,
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    # 1. Handling Health Check Report — hanya untuk jalur mandiri, bukan fan-out incident
    # Jika health_result datang bersama correlation/triage (downstream_timeout fan-out), jangan kirim health terpisah — biarkan correlation yang handle (prevent duplicate)
    if health_result and not state.get("correlation_result") and not state.get("triage_result"):
        logger.info("TelegramAgent formatting Health Check report (standalone)")
        try:
            formatted = await _format_health_with_llm(intent, health_result)
        except Exception as e:
            logger.error(f"Health LLM formatting failed: {e}")
            formatted = _format_health_fallback(health_result) + await llm_unavailable_note_for(state)

        success, send_error = await _deliver(state, formatted)
        return {
            "formatted_message": formatted,
            "telegram_sent": success,
            "telegram_error": send_error,
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    # 1.5 Supervisor pre-formatted reply (knowledge inventory, redirect/guard, offer decline).
    #     Supervisor sudah menyusun formatted_message final → kirim langsung, JANGAN
    #     re-format sebagai insiden (tanpa correlation/triage = bukan hasil analisis).
    if state.get("formatted_message") and not state.get("correlation_result") and not state.get("triage_result"):
        logger.info("TelegramAgent delivering supervisor pre-formatted message (non-incident)")
        preformatted = state["formatted_message"]
        success, send_error = await _deliver(state, preformatted)
        return {
            "formatted_message": preformatted,
            "telegram_sent": success,
            "telegram_error": send_error,
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    # 2. Handling Log Analysis Incident Alert
    logger.info(f"TelegramAgent processing service='{service_name}', docs={len(documents)}")

    doc_context = ""

    incident_history = await get_incident_history(service_name, hours=24, limit=5)
    if incident_history:
        logger.info(f"Loaded {len(incident_history)} prior request records as incident history")

    # Fix #201: resolve locale SEKALI DI LUAR try (dipakai format LLM, span note,
    # confidence block, dan offer investigate web) — gagal → "id", pipeline lanjut.
    # Fix #140: web chat (suppress_telegram) = deteksi isi percakapan (fallback preferensi
    # user); Telegram = locale owner workspace (Fix #105).
    try:
        if state.get("suppress_telegram"):
            from services.conversation import detect_chat_locale
            from services.user_store import get_user_locale

            hist_locale = state.get("conversation_history") or []
            user_locale = await get_user_locale((state.get("sender") or {}).get("user_id"))
            locale = detect_chat_locale(hist_locale, default=user_locale)
        else:
            from services.locale_pref import get_workspace_locale

            locale = await get_workspace_locale(state.get("workspace_id"))
    except Exception:
        locale = "id"

    try:
        correlation_result = state.get("correlation_result")
        # FASE 4A: span turut dianalisis di correlation → LLM telegram otomatis lebih kaya, cukup tambah catatan
        formatted = await _format_with_llm(
            intent, service_name, documents, doc_context, incident_history, correlation_result,
            history=state.get("conversation_history"),
            locale=locale,
        )
        if state.get("span_available") and state.get("correlation_result"):
            formatted += "\n\n" + _SPAN_OTEL_NOTE.get(locale, _SPAN_OTEL_NOTE["en"])
        # CHATFLOW V2.1 (Tahap 1C): blok confidence bila confidence rendah + ada gap.
        # Bilingual via _append_confidence_block (dict en/id).
        formatted = _append_confidence_block(
            formatted=formatted,
            confidence=state.get("investigation_confidence", 1.0),
            data_gaps=state.get("data_gaps", []),
            suggested_next=state.get("suggested_next", []),
            reply_language=("English" if locale == "en" else "Bahasa Indonesia"),
        )
    except Exception as e:
        logger.error(f"LLM formatting failed: {e}")
        formatted = await _fallback_message(service_name, documents, state) + await llm_unavailable_note_for(state)

    # FASE 6A: tombol dinamis per root_cause + feedback (feedback tetap di baris bawah)
    reply_markup = _build_dynamic_buttons(state, locale=locale)
    episode_id = state.get("episode_id")
    if episode_id:
        logger.info(f"TelegramAgent attaching dynamic buttons root_cause={state.get('root_cause_assessment')} episode_id={episode_id}")
    else:
        logger.info(f"TelegramAgent dynamic buttons without episode_id root_cause={state.get('root_cause_assessment')}")

    # ── Offer lanjutan (Tahap 1-3): setelah laporan insiden → tawarkan investigasi lebih dalam.
    #    HANYA web chat (suppress_telegram) — Telegram sudah punya 6A buttons + diagnostic 6C,
    #    supaya tidak dobel follow-up.
    #    Fix #189: gate "nilai kedalaman" — offer HANYA bila investigasi belum dalam:
    #      - service bukan placeholder (unknown/null/kosong → offer "cek unknown" = noise)
    #      - masih ada data_gaps, ATAU confidence < threshold, ATAU planned_nodes belum
    #        mencakup full set collector.
    #      - BELUM pernah ditawari investigate di sesi ini (anti-reoffer → anti-loop "ya").
    try:
        if (
            state.get("suppress_telegram")
            and state.get("correlation_result")
            and not _is_placeholder_service(service_name)
        ):
            session_id = (state.get("sender") or {}).get("session_id")
            offer_svc = state.get("resolved_service_name") or service_name
            if session_id and _investigate_offer_has_value(state) and not await _already_offered_investigate(session_id):
                offer = build_investigate_offer(offer_svc, locale=locale)
                if offer:
                    offer_id = await create_offer(
                        type_=offer["type"], params=offer["params"], question=offer["question"],
                        needs_param=offer["needs_param"], session_id=session_id,
                    )
                    if offer_id:
                        formatted += f"\n\n{render_offer_question(offer)}"
                        logger.info(f"[Offer] investigate question appended {offer_id} svc={offer_svc} (web)")
    except Exception as e:
        logger.warning(f"[Offer] investigate build failed: {e}")

    success, send_error = await _deliver(state, formatted, reply_markup=reply_markup)
    if send_error:
        return {
            "formatted_message": formatted,
            "telegram_sent": False,
            "telegram_error": send_error,
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    # FASE 6C: trigger diagnostic session (fire-and-forget, only for incident via Telegram)
    try:
        root_cause = state.get("root_cause_assessment") or "unknown"
        episode_id_diag = state.get("episode_id")
        # hanya untuk channel telegram (diagnostic via Telegram, bukan API)
        sender_diag = state.get("sender") or {}
        if isinstance(sender_diag, dict) and sender_diag.get("channel") != "telegram":
            raise ValueError("skip diagnostic for non-telegram")
        chat_id_diag = None
        if isinstance(sender_diag, dict):
            chat_id_diag = sender_diag.get("chat_id") or sender_diag.get("id")
        # Fix #40: konteks channel — sesi terikat (chat, notif) dan pertanyaan dikirim
        # via bot channel asal (bukan lagi .env global)
        channels_diag = await _resolve_channels_for_state(state)
        first_channel = channels_diag[0] if channels_diag else None
        token_diag = chat_channel_diag = notif_diag = None
        if first_channel:
            from services.notification_store import extract_telegram_creds

            token_diag, chat_channel_diag = extract_telegram_creds(first_channel)
            notif_diag = first_channel.get("notif_id")
        if not chat_id_diag:
            chat_id_diag = chat_channel_diag
        if success and episode_id_diag and chat_id_diag and token_diag and root_cause in (
            "downstream", "service-fault", "unknown",
        ):
            from services.diagnostic_session import create_session, _get_first_question
            from services.telegram_client import send_message as _diag_send

            async def _run_diag():
                try:
                    sid = await create_session(
                        episode_id_diag, service_name, root_cause, str(chat_id_diag), notif_id=notif_diag
                    )
                    if not sid:
                        return
                    q, btns = _get_first_question(root_cause)
                    if not q:
                        return
                    # btns is list[dict], kirim sebagai 1 row
                    markup = {"inline_keyboard": [btns]} if btns else None
                    await _diag_send(
                        q,
                        chat_id=str(chat_id_diag),
                        reply_markup=markup,
                        bot_token=token_diag or "",
                    )
                    logger.info(f"[Diagnostic] first question sent for {episode_id_diag} root={root_cause}")
                except Exception as e:
                    logger.warning(f"[Diagnostic] trigger failed: {e}")

            asyncio.create_task(_run_diag())
    except Exception as e:
        logger.warning(f"[Diagnostic] setup failed: {e}")

    # ── Chat suggestions (chips follow-up) — HANYA web chat (suppress_telegram) ──
    # CHATFLOW V2.1 (Tahap 2): build_contextual_suggestions — chips berbasis temuan
    # investigasi (deploy/Second Brain/trace/data_gaps), fallback generik.
    chat_suggestions = []
    try:
        if state.get("suppress_telegram"):
            from services.conversation import detect_chat_locale
            from services.offer_planner import build_contextual_suggestions
            from services.user_store import get_user_locale

            history = state.get("conversation_history") or []
            user_locale = await get_user_locale((state.get("sender") or {}).get("user_id"))
            locale = detect_chat_locale(history, default=user_locale)
            reply_language = "English" if locale == "en" else "Bahasa Indonesia"
            chat_suggestions = build_contextual_suggestions(state, reply_language)
    except Exception as e:
        logger.warning(f"[TelegramAgent] chat suggestions gagal: {e}")

    return {
        "formatted_message": formatted,
        "telegram_sent": success,
        "telegram_error": None,
        "next_agent": "end",
        "agents_visited": agents_visited,
        "session_id": f"DS-{episode_id}" if state.get("episode_id") else None,
        **({"chat_suggestions": chat_suggestions} if chat_suggestions else {}),
    }


async def _format_health_with_llm(intent: str, health_result: dict) -> str:
    """Format Laporan Health Check menggunakan LLM."""
    result_json = json.dumps(health_result, indent=2, default=str)
    user_content = render_prompt("telegram_health_user", intent=intent, health_json=result_json)
    messages = [
        SystemMessage(content=render_prompt("telegram_health_system")),
        HumanMessage(content=user_content),
    ]
    response = await get_chat_llm(temperature=0.3).ainvoke(messages)
    return response.content


def _format_health_fallback(health_result: dict) -> str:
    """Fallback manual formatting untuk laporan Health Check."""
    lines = ["🌐 *[Database Health Check Status]*\n"]
    if "status" in health_result:
        st = health_result.get("status", "unknown").upper()
        icon = "🟢" if st == "CONNECTED" else "🔴"
        engine = health_result.get("engine", "database").upper()
        lat = health_result.get("latency_ms", "N/A")
        host = health_result.get("host")
        db = health_result.get("db")
        lines.append(f"{icon} *Engine:* `{engine}` | *Status:* `{st}`")
        if host:
            lines.append(f"🔗 *Host:* `{host}`")
        if db:
            lines.append(f"🗄️ *Database:* `{db}`")
        lines.append(f"⏱️ *Latency:* `{lat} ms`")
        if health_result.get("error"):
            lines.append(f"❌ *Error:* `{health_result['error']}`")
    else:
        lines.append("```json\n" + json.dumps(health_result, indent=2, default=str) + "\n```")
    return "\n".join(lines)


async def _format_with_llm(
    intent: str,
    service_name: str,
    documents: list,
    doc_context: str,
    incident_history: list = None,
    correlation_result: dict = None,
    history: Optional[list] = None,
    locale: str = "id",
) -> str:
    """LLM analisis log dengan grounding dari dokumen service + riwayat insiden + observability correlation.

    locale (Fix #136/#140): bahasa jawaban eksplisit — web chat = deteksi dari isi
    percakapan (fallback preferensi user); Telegram = locale owner workspace (Fix #105).
    """

    # System prompt: template file-driven + konteks dokumen dari docs/
    system_content = render_prompt("telegram_incident_system")
    if doc_context:
        system_content += f"\n\n---\n# SYSTEM CONTEXT (use as decision reference)\n\n{doc_context}"

    # User prompt — blok disusun di kode (kondisional), template merender slot-nya
    if not documents:
        sample_block = "MongoDB query result: No error documents found."
    else:
        sample = documents[:10]
        docs_json = json.dumps(sample, indent=2, ensure_ascii=False, default=str)
        sample_block = (
            f"Intent: {intent}\n"
            f"Service: `{service_name}`\n"
            f"Total error documents found: {len(documents)}\n\n"
            f"Sample log (max 10 latest documents):\n```json\n{docs_json}\n```\n\n"
            f"Analyze the logs above and build a Telegram notification "
            f"based on the service document guide and thresholds."
        )

    correlation_block = ""
    if correlation_result:
        analysis_text = correlation_result.get("analysis", "")
        rc_assessment = correlation_result.get("root_cause_assessment", "unknown")
        # Fix #143: instruksi translate eksplisit — analysis LLM bisa saja dalam bahasa
        # berbeda; WAJIB disajikan ulang dalam reply_language (bukan disalin mentah).
        reply_lang_name = "English" if locale == "en" else "Bahasa Indonesia"
        correlation_block = (
            f"# OBSERVABILITY & ROOT CAUSE CORRELATION AGENT RESULT\n"
            f"Root Cause Assessment: `{rc_assessment}`\n"
            f"Correlation Agent analysis:\n{analysis_text}\n\n"
            f"Include this Root Cause Assessment ({rc_assessment}) and the Correlation Agent "
            f"recommendations in the Telegram notification.\n"
            f"IMPORTANT: Restate the analysis and recommendations in {reply_lang_name} — "
            f"translate if needed, never copy the analysis verbatim in another language."
        )

    incident_history_block = ""
    if incident_history:
        history_lines = "\n".join(
            f"- [{h.get('incoming_date')}] status={h.get('status')} | error={h.get('error') or '-'} "
            f"| message='{h.get('message')}'"
            for h in incident_history
        )
        incident_history_block = (
            f"# THIS SERVICE'S INCIDENT HISTORY (last 24h, from request_logs)\n"
            f"Use to recognize recurring patterns (same error repeated, previously failed actions). "
            f"Do not report an old request as a new error if it has returned to normal.\n"
            f"{history_lines}"
        )

    history_block = ""
    if history:
        hist_lines = "\n".join(f"[{h.get('role')}] {h.get('content', '')}" for h in history[-6:])
        history_block = (
            f"# PREVIOUS CONVERSATION (session context)\n"
            f"Use to resolve references like 'that one' / 'continue'. Do NOT treat conversation as new facts (secondary).\n"
            f"{hist_lines}"
        )

    user_content = render_prompt(
        "telegram_incident_user",
        sample_block=sample_block,
        correlation_block=correlation_block,
        incident_history_block=incident_history_block,
        history_block=history_block,
        reply_language=("English" if locale == "en" else "Bahasa Indonesia"),
    )

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]

    response = await get_chat_llm(temperature=0.3).ainvoke(messages)
    return response.content


# Fallback deterministic insiden (LLM down) — bilingual via dict, struktur blank-line
# (Fix #209/#210): seragam dgn format laporan LLM agar semua balasan human-readable.
_FALLBACK_TEXTS = {
    "en": {
        "ticket_title": "{emoji} *[{sev}]* Ticket {num} — {title}",
        "error_title": "{emoji} *[{severity}]* Error in `{svc}`",
        "info_title": "ℹ️ *[INFO]* No errors found",
        "service": "• *Service:* `{svc}` ({criticality})",
        "kind_env": "• *Kind:* {kind} · *Environment:* {env}",
        "desc": "*Description:*\n{desc}",
        "total": "• *Total error:* {count}",
        "latest": "• *Latest error:* `{msg}`",
        "time": "• *Time:* {ts}",
        "status": "• *Status:* System normal",
        "escalation": "*Escalation:*\n{escalation}",
        "diagnostic": "*Diagnostic steps:*\n{diag}",
    },
    "id": {
        "ticket_title": "{emoji} *[{sev}]* Tiket {num} — {title}",
        "error_title": "{emoji} *[{severity}]* Error di `{svc}`",
        "info_title": "ℹ️ *[INFO]* Tidak ada error ditemukan",
        "service": "• *Service:* `{svc}` ({criticality})",
        "kind_env": "• *Kind:* {kind} · *Environment:* {env}",
        "desc": "*Deskripsi:*\n{desc}",
        "total": "• *Total error:* {count}",
        "latest": "• *Error terbaru:* `{msg}`",
        "time": "• *Waktu:* {ts}",
        "status": "• *Status:* Sistem normal",
        "escalation": "*Eskalasi:*\n{escalation}",
        "diagnostic": "*Langkah diagnostik:*\n{diag}",
    },
}


async def _fallback_message(
    service_name: str, documents: list, state: Optional[dict] = None
) -> str:
    """Fallback jika LLM tidak tersedia. Fix #50: ticket-aware — JANGAN klaim
    'Sistem normal' untuk tiket alert; beri konteks tiket + langkah diagnostik
    actionable (KubePodNotReady/HPA/down). Fix #210: bilingual + struktur blank-line
    seragam dgn laporan LLM (human-readable)."""
    svc_doc = await get_service_doc(service_name)
    criticality = svc_doc["meta"].get("criticality", "unknown") if svc_doc else "unknown"
    escalation = svc_doc["meta"].get("escalation", {}).get("primary", "-") if svc_doc else "-"
    tc = (state or {}).get("ticket_context") or {}

    locale = "en"
    try:
        if (state or {}).get("suppress_telegram"):
            from services.conversation import detect_chat_locale
            from services.user_store import get_user_locale
            ulocale = await get_user_locale(((state or {}).get("sender") or {}).get("user_id"))
            locale = detect_chat_locale((state or {}).get("conversation_history") or [], default=ulocale)
        else:
            from services.locale_pref import get_workspace_locale
            locale = await get_workspace_locale((state or {}).get("workspace_id"))
    except Exception:
        locale = "en"
    t = _FALLBACK_TEXTS.get(locale, _FALLBACK_TEXTS["en"])

    if tc:
        from agents.correlation_agent import infra_diag_steps
        title = tc.get("title") or ""
        svc = tc.get("serviceName") or service_name
        sev = (tc.get("severity") or "unknown").upper()
        num = tc.get("ticketNumber")
        emoji = "🚨" if sev in ("CRITICAL", "HIGH") else "⚠️"
        parts = [t["ticket_title"].format(emoji=emoji, sev=sev, num=num, title=title)]
        parts.append(t["service"].format(svc=svc, criticality=criticality))
        parts.append(t["kind_env"].format(
            kind=tc.get("kind") or "-", env=tc.get("environment") or "-"
        ))
        desc = (tc.get("description") or "").strip()
        if desc:
            parts.append("")
            parts.append(t["desc"].format(desc=desc[:300]))
        diag = infra_diag_steps(title)
        if diag:
            parts.append("")
            parts.append(t["diagnostic"].format(diag=diag))
        else:
            parts.append("")
            parts.append(t["escalation"].format(escalation=escalation))
        return "\n".join(parts)

    count = len(documents)
    if count == 0:
        return (
            t["info_title"] + "\n" +
            t["service"].format(svc=service_name, criticality=criticality) + "\n" +
            t["status"]
        )

    latest = documents[0]
    msg = latest.get("message") or latest.get("msg") or "N/A"
    ts = latest.get("timestamp") or latest.get("ts") or "N/A"

    emoji = "🚨" if count >= 10 else "⚠️"
    severity = "CRITICAL" if count >= 10 else "WARNING"

    return (
        t["error_title"].format(emoji=emoji, severity=severity, svc=service_name) + "\n\n" +
        t["service"].format(svc=service_name, criticality=criticality) + "\n" +
        t["total"].format(count=count) + "\n" +
        t["latest"].format(msg=msg) + "\n" +
        t["time"].format(ts=ts) + "\n\n" +
        t["escalation"].format(escalation=escalation)
    )


async def _format_follow_up(intent: str, follow_up_context: dict,
                            reply_language: str = "English") -> str:
    """Format jawaban pertanyaan lanjutan menggunakan konteks riwayat sebelumnya.
    reply_language (Fix bahasa): jalur follow-up wajib bahasa eksplisit (pola #201/#222)."""
    if not follow_up_context or follow_up_context.get("not_found"):
        followup_block = (
            f"No previous check history available. Politely tell the user there is no history, "
            f"and suggest sending a new check command."
        )
    else:
        prev_raw = follow_up_context.get("prev_raw_snapshot") or []
        raw_json = json.dumps(prev_raw, indent=2, ensure_ascii=False, default=str) if prev_raw else "No raw data stored."
        followup_block = (
            f"# PREVIOUS RESULT CONTEXT\n"
            f"*Check date:* {follow_up_context.get('prev_date')}\n"
            f"*Service:* {follow_up_context.get('prev_service') or '-'}\n"
            f"*User's initial message:* {follow_up_context.get('prev_message')}\n\n"
            f"**Previous agent reply:**\n"
            f"{follow_up_context.get('prev_reply') or '-'}\n\n"
            f"**Stored raw data (snapshot):**\n```json\n{raw_json}\n```"
        )

    user_content = render_prompt(
        "telegram_followup_user", intent=intent, followup_block=followup_block,
        reply_language=reply_language,
    )

    messages = [
        SystemMessage(content=render_prompt("telegram_followup_system")),
        HumanMessage(content=user_content),
    ]
    response = await get_chat_llm(temperature=0.3).ainvoke(messages)
    return response.content


def _format_follow_up_fallback(follow_up_context: dict, locale: str = "id") -> str:
    """Fallback manual jika LLM tidak tersedia untuk pertanyaan lanjutan.
    locale (Fix bahasa): "id"/"en" — bukan hardcode Indonesia."""
    if not follow_up_context or follow_up_context.get("not_found"):
        if locale == "en":
            return (
                "ℹ️ *[INFO]* No previous check history.\n"
                'Please send a new check command (e.g. "check error <service-name>").'
            )
        return (
            "ℹ️ *[INFO]* Tidak ada riwayat pengecekan sebelumnya.\n"
            "Silakan kirim perintah pengecekan baru (mis. \"cek error <nama-service>\")."
        )
    if locale == "en":
        return (
            "ℹ️ *[INFO]* Previous check result:\n"
            f"*Date:* {follow_up_context.get('prev_date') or '-'}\n"
            f"*Service:* `{follow_up_context.get('prev_service') or '-'}`\n"
            f"*Reply:* {follow_up_context.get('prev_reply') or '-'}"
        )
    return (
        "ℹ️ *[INFO]* Hasil pengecekan sebelumnya:\n"
        f"*Tanggal:* {follow_up_context.get('prev_date') or '-'}\n"
        f"*Service:* `{follow_up_context.get('prev_service') or '-'}`\n"
        f"*Balasan:* {follow_up_context.get('prev_reply') or '-'}"
    )


async def _format_data_with_llm(intent: str, service_name: str, documents: list,
                                reply_language: str = "English") -> str:
    """Format data mentah yang diminta user (bukan analisis error).
    reply_language (Fix bahasa): jalur data wajib bahasa eksplisit — sama pola
    Fix #201/#217, bukan "same language as user" yang lemah."""
    if not documents:
        records_block = (
            f"No records found in the database for this request. "
            f"Politely tell the user there is no data, without inventing any."
        )
    else:
        docs_json = json.dumps(documents, indent=2, ensure_ascii=False, default=str)
        records_block = (
            f"Total records requested/available: {len(documents)}\n\n"
            f"Records:\n```json\n{docs_json}\n```"
        )

    user_content = render_prompt(
        "telegram_data_user", intent=intent, service_name=service_name,
        records_block=records_block, reply_language=reply_language,
    )

    messages = [
        SystemMessage(content=render_prompt("telegram_data_system")),
        HumanMessage(content=user_content),
    ]
    response = await get_chat_llm(temperature=0.3).ainvoke(messages)
    return response.content


def _format_data_fallback(service_name: str, documents: list, locale: str = "id") -> str:
    """Fallback manual jika LLM tidak tersedia untuk tampilan data mentah.
    locale (Fix bahasa): "id"/"en" — bukan hardcode Indonesia."""
    if not documents:
        head = "ℹ️ *[INFO]* No records found" if locale == "en" else "ℹ️ *[INFO]* Tidak ada record ditemukan"
        empty = "*Data:* Empty" if locale == "en" else "*Data:* Kosong"
        return (
            f"{head}\n"
            f"*Service:* `{service_name}`\n"
            f"{empty}"
        )

    title = "📄 *Latest Data*" if locale == "en" else "📄 *Data Terbaru*"
    total = f"*Total records:* {len(documents)}" if locale == "en" else f"*Total record:* {len(documents)}"
    rec_label = "Record" if locale == "en" else "Record"
    lines = [f"{title} — `{service_name}`", total]
    for i, doc in enumerate(documents, 1):
        fields = "\n".join(f"    • `{k}`: {v}" for k, v in doc.items())
        lines.append(f"\n**{rec_label} {i}:**\n{fields}")
    return "\n".join(lines)


async def _strip_env(docs: list) -> list:
    """Hapus field 'env' dari dokumen agar LLM tidak memakainya sebagai dasar analisis."""
    out = []
    for d in docs:
        if isinstance(d, dict):
            d = {k: v for k, v in d.items() if k != "env"}
        out.append(d)
    return out


async def _format_span_with_llm(
    intent: str,
    trace_id: Optional[str],
    span_summary: str,
    span_data: Optional[dict],
    doc_context: str = "",
    history: Optional[list] = None,
    reply_language: str = "English",
) -> str:
    """LLM menceritakan apa yang sebenarnya terjadi pada satu traceId (dari app_logs_db).
    reply_language (Fix bahasa CPRO-19): "English" / "Bahasa Indonesia" — prompt span
    wajib bahasa eksplisit, bukan "same language as user" yang lemah (model free default ID)."""
    system_content = render_prompt("telegram_span_system")
    if doc_context:
        system_content += (
            "\n\n---\n# SYSTEM CONTEXT & PLAYBOOK (use for deeper RCA)\n"
            "Use the service, connectivity, schema, and playbook documents below to enrich "
            "root-cause analysis and actionable recommendations (thresholds, escalation, "
            "auto_remediation_allowed). Do not repeat verbatim; use as grounding.\n\n" + doc_context
        )

    if span_data:
        spans = span_data.get("spans") or []
        http_logs = span_data.get("http_logs") or []
        spans_clean = await _strip_env(spans[:10])
        http_clean = await _strip_env(http_logs)
        extra_block = "\n\nRaw span data (sample):\n```json\n" + json.dumps(
            spans_clean, indent=2, ensure_ascii=False, default=str
        ) + "\n```"
        if http_clean:
            extra_block += "\n\nHTTP logs:\n```json\n" + json.dumps(
                http_clean, indent=2, ensure_ascii=False, default=str
            ) + "\n```"
    else:
        extra_block = ""

    history_block = ""
    if history:
        hist_lines = "\n".join(f"[{h.get('role')}] {h.get('content', '')}" for h in history[-6:])
        history_block = f"# PREVIOUS CONVERSATION (session context — secondary)\n{hist_lines}"

    user_content = render_prompt(
        "telegram_span_user",
        intent=intent,
        trace_id=trace_id or "N/A",
        span_summary=span_summary,
        extra_block=extra_block,
        history_block=history_block,
        reply_language=reply_language,
    )

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]
    response = await get_chat_llm(temperature=0.3).ainvoke(messages)
    return response.content


def _format_span_fallback(trace_id: Optional[str], span_summary: str) -> str:
    """Fallback manual jika LLM tidak tersedia untuk detail traceId."""
    return (
        f"🔍 *[SPAN DETAIL]* TraceID: `{trace_id or 'N/A'}`\n\n"
        f"{span_summary}"
    )
