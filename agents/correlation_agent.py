import asyncio
import logging
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
from state.schema import AgentState
from services.llm_factory import get_chat_llm
from services.prompt_loader import render as render_prompt
from config.settings import settings

logger = logging.getLogger(__name__)

# Fix #54: LLM dibangun lazily saat invoke (config BYOK dari DB, refresh tanpa restart).

# Fix #53: pesan profesional saat LLM tidak tersedia — dipakai correlation fallback
# & response_agent (semua branch LLM). Arahkan user cek config/limit, bukan bingung.
# Fix #113: bilingual — locale dari preferensi user (localePreference), fallback "id".
_LLM_UNAVAILABLE_TEXTS = {
    "id": (
        "\n\n_⚠️ *LLM tidak tersedia saat ini* — analisis AI tidak dapat dihasilkan. "
        "Periksa konfigurasi LLM (provider, model, API key) atau batas kredit pada "
        "dashboard penyedia layanan Anda, lalu kirim ulang pertanyaan._"
    ),
    "en": (
        "\n\n_⚠️ *LLM is currently unavailable* — AI analysis could not be generated. "
        "Check your LLM configuration (provider, model, API key) or credit limit on "
        "your provider dashboard, then resend your question._"
    ),
}


def llm_unavailable_note(locale: str = "id") -> str:
    return _LLM_UNAVAILABLE_TEXTS.get(locale, _LLM_UNAVAILABLE_TEXTS["id"])


async def llm_unavailable_note_for(state: dict) -> str:
    """Resolusi locale dari sender.user_id di AgentState (web chat punya Mongo user_id;
    Telegram biasanya tidak → fallback "id")."""
    from services.user_store import get_user_locale
    uid = (state.get("sender") or {}).get("user_id") or ""
    return llm_unavailable_note(await get_user_locale(uid))


# Backward-compat: pemakaian lama tanpa state (dihindari untuk kode baru)
LLM_UNAVAILABLE_NOTE = llm_unavailable_note("id")


def infra_diag_steps(title: str) -> str:
    """Actionable diagnostic steps by alert type (Fix #50) — used in
    correlation (injected into prompt) & telegram fallback (no-LLM answer)."""
    t = (title or "").lower()
    if "podnotready" in t or "pod not ready" in t:
        return (
            "Diagnostic steps (KubePodNotReady):\n"
            "1. `kubectl get pods -n <ns>` — find pods in NotReady state\n"
            "2. `kubectl describe pod <pod> -n <ns>` — read Events (ImagePullBackOff / OOMKilled / CrashLoopBackOff / failed probe)\n"
            "3. `kubectl logs <pod> -n <ns> --previous` — logs before crash\n"
            "4. `kubectl top pod <pod> -n <ns>` — check CPU/mem vs limits\n"
            "5. `kubectl get nodes` — ensure nodes are not NotReady / DiskPressure / MemoryPressure"
        )
    if "hpa" in t or "maxout" in t or "scale" in t:
        return (
            "Diagnostic steps (HPA/Scale):\n"
            "1. `kubectl get hpa -n <ns>` — target vs current replicas (maxed out?)\n"
            "2. `kubectl get pods -n <ns>` — replica status (Pending/OOMKilled?)\n"
            "3. Check Prometheus: request rate vs limits, HPA target utilization"
        )
    if "down" in t or "unreachable" in t or "outage" in t:
        return (
            "Diagnostic steps (Down/Unreachable):\n"
            "1. `kubectl get pods -n <ns>` — deployment status\n"
            "2. `kubectl describe pod <pod> -n <ns>` — Events\n"
            "3. Verify connectivity/network policy between services"
        )
    return ""

# Prompt system RCA dipindah ke file-driven: prompts/correlation_system.md
# (editable, hot-reload via POST /prompts/reload).

from state.constants import CONFIDENCE_THRESHOLD, AUTO_LOOP_MAX


async def _resolve_investigation_locale(state: dict) -> str:
    """Resolusi locale utk teks V2.1 (gap/suggested): web chat → preferensi user
    (detect dari isi percakapan dulu), telegram → locale owner workspace (Fix #105)."""
    try:
        from services.conversation import detect_chat_locale
        from services.user_store import get_user_locale

        sender = state.get("sender") or {}
        if sender.get("channel") == "telegram":
            from services.locale_pref import get_workspace_locale
            return await get_workspace_locale(state.get("workspace_id"))
        user_locale = await get_user_locale(sender.get("user_id"))
        return detect_chat_locale(state.get("conversation_history") or [], default=user_locale)
    except Exception:
        return "id"


# ── CHATFLOW V2.1 (Tahap 1): gap, confidence, suggested_next — TANPA LLM ──────
# Semua teks user-facing bilingual (konvensi multi-bahasa Popov), bukan if/else.

_GAP_DESCRIPTIONS = {
    "id": {
        "metrics_agent": "Error rate & HPA metrics belum diperiksa (relevan untuk traffic spike / resource exhaustion)",
        "mongo_agent":   "Application logs belum diperiksa (relevan untuk error patterns & database issues)",
        "trace_agent":   "Distributed traces belum diperiksa (relevan untuk downstream timeout & latency)",
        "health_agent":  "Koneksi database belum diuji (relevan untuk downstream connection failures)",
        "span_agent":    "Detail span central log belum diperiksa (relevan untuk tracing error spesifik)",
    },
    "en": {
        "metrics_agent": "Error rate & HPA metrics not yet examined (relevant for traffic spike / resource exhaustion)",
        "mongo_agent":   "Application logs not yet examined (relevant for error patterns & database issues)",
        "trace_agent":   "Distributed traces not yet examined (relevant for downstream timeout & latency)",
        "health_agent":  "Database connection not yet tested (relevant for downstream connection failures)",
        "span_agent":    "Central log span detail not yet examined (relevant for specific error tracing)",
    },
}


# suggested_action per node (label chip / button) — bilingual
_GAP_ACTIONS = {
    "id": {
        "metrics_agent": "Cek error rate & HPA metrics",
        "mongo_agent":   "Cek application logs",
        "trace_agent":   "Lihat distributed traces",
        "health_agent":  "Uji koneksi database",
        "span_agent":    "Periksa detail span",
    },
    "en": {
        "metrics_agent": "Check error rate & HPA metrics",
        "mongo_agent":   "Check application logs",
        "trace_agent":   "View distributed traces",
        "health_agent":  "Test database connections",
        "span_agent":    "Inspect span details",
    },
}

# Priority per hypothesis — node paling relevan dapat prioritas lebih tinggi (1 = paling penting)
_GAP_PRIORITY = {
    "regression_post_deploy": {"mongo_agent": 1, "trace_agent": 2},
    "downstream_timeout":     {"trace_agent": 1, "health_agent": 2},
    "hpa_maxout":             {"metrics_agent": 1, "mongo_agent": 2},
    "db_connection":          {"health_agent": 1, "mongo_agent": 2},
    "traffic_spike":          {"metrics_agent": 1, "trace_agent": 2},
    "unknown":                {"mongo_agent": 1, "metrics_agent": 2, "trace_agent": 3},
}


def _compute_data_gaps(state: dict, locale: str = "id") -> list[dict]:
    """
    Bandingkan lanes yang SEHARUSNYA dijalankan (planned_nodes) vs yang BENAR-BENAR
    dijalankan (agents_visited). Gap 5: return list[dict] terstruktur.

    Setiap item:
      {node, description, reason, suggested_action, priority}
    gap_nodes di-derive dari sini (g["node"]) — backward compat utk loop router.
    """
    planned = set(state.get("planned_nodes") or [])
    visited = set(state.get("agents_visited") or [])
    missing = planned - visited
    texts = _GAP_DESCRIPTIONS.get(locale, _GAP_DESCRIPTIONS["id"])
    actions = _GAP_ACTIONS.get(locale, _GAP_ACTIONS["en"])
    hypothesis = (state.get("triage_result") or {}).get("hypothesis", "unknown")
    prios = _GAP_PRIORITY.get(hypothesis, _GAP_PRIORITY["unknown"])

    gaps: list[dict] = []
    for node in missing:
        if node not in texts:
            continue
        txt = texts[node]
        desc, _, reason = txt.partition(" (")
        if reason:
            reason = reason.rstrip(")")
        gaps.append({
            "node": node,
            "description": desc.strip(),
            "reason": reason or "",
            "suggested_action": actions.get(node, desc.strip()),
            "priority": prios.get(node, 99),
        })
    return gaps


def _compute_confidence(state: dict, data_gaps: list) -> float:
    """
    Heuristic confidence (tanpa LLM):
    - Penalti per gap (maks -30%)
    - Penalti hypothesis 'unknown' (-20%)
    - Bonus historical context Second Brain (+10%) — sinyal = second_brain_context
      (bukan knowledge_context yang merupakan playbook universal)
    """
    planned = state.get("planned_nodes") or []
    hypothesis = (state.get("triage_result") or {}).get("hypothesis", "unknown")
    # Fix #6 adaptasi: knowledge_context = playbook universal (bukan Second Brain);
    # sinyal historis yang benar = second_brain_context / historical_block.
    has_history = bool(state.get("second_brain_context")) or bool(state.get("historical_block"))

    base = 1.0
    if planned:
        gap_ratio = len(data_gaps) / max(len(planned), 1)
        base -= gap_ratio * 0.30
    if hypothesis == "unknown":
        base -= 0.20
    if has_history:
        base += 0.10
    return round(max(0.0, min(1.0, base)), 2)


def _compute_suggested_next(state: dict, data_gaps: list, confidence: float,
                            locale: str = "id") -> list[str]:
    """
    Bila confidence >= threshold & tidak ada gap → [].
    Bila ada gap → 2-3 aksi spesifik (deterministik mapping). Tanpa LLM.
    """
    from state.constants import CONFIDENCE_THRESHOLD

    if confidence >= CONFIDENCE_THRESHOLD and not data_gaps:
        return []

    hypothesis = (state.get("triage_result") or {}).get("hypothesis", "unknown")
    service = state.get("service_name") or "service ini"
    visited = set(state.get("agents_visited") or [])
    lang_id = locale == "id"
    suggestions = []

    if "metrics_agent" not in visited:
        suggestions.append(
            f"Cek error rate & CPU/memory metrics {service} 1 jam terakhir" if lang_id
            else f"Check error rate & CPU/memory metrics {service} for the last 1 hour"
        )
    if "health_agent" not in visited and hypothesis in ("downstream_timeout", "db_connection"):
        suggestions.append(
            f"Uji koneksi database {service}" if lang_id else f"Test database connection {service}"
        )
    if "trace_agent" not in visited:
        suggestions.append(
            f"Lihat distributed trace {service} untuk request yang gagal" if lang_id
            else f"View distributed trace {service} for failed requests"
        )
    if state.get("preset_trace_ids") and "span_agent" not in visited:
        suggestions.append(
            "Periksa detail span traceId yang terlampir di tiket" if lang_id
            else "Check the span detail of the traceId attached to the ticket"
        )

    return suggestions[:3]


async def correlation_agent(state: AgentState) -> dict:
    """
    Gabungkan ringkasan dari Mongo Agent, Metrics Agent, dan Trace Agent.
    Fase 2: READ Second Brain (Hybrid Search) sebelum LLM untuk prior knowledge.
    Exception safe — Second Brain tidak blocking.
    """
    service_name = state.get("resolved_service_name") or state.get("service_name", "unknown")
    mongo_summary = state.get("mongo_summary") or "Log MongoDB: Tidak ada data ringkasan."
    metrics_summary = state.get("metrics_summary") or "Metrics Prometheus: Tidak tersedia."
    trace_summary = state.get("trace_summary") or "Trace Tempo: Tidak tersedia."
    span_summary_raw = state.get("span_summary") or ""
    span_available = state.get("span_available", False)
    health_result = state.get("health_result")
    agents_visited = ["correlation_agent"]
    # Fix #143: bahasa analisis eksplisit — dipakai utk reply_language di prompt LLM
    # DAN teks V2.1 (gap/suggested). Web chat = detect → user pref; telegram = owner ws.
    locale = await _resolve_investigation_locale(state)

    logger.info(f"CorrelationAgent performing root cause analysis for service='{service_name}'")

    doc_context = ""
    # Gap 1 Fase 6: Pipeline B removed — knowledge_agent now handles all knowledge retrieval
    # via search_relevant_knowledge() including agent_docs. doc_context kept as empty string
    # for prompt template compatibility. Rollback: uncomment below to restore Pipeline B.
    # try:
    #     from services.doc_loader import build_agent_context
    #     doc_context = await build_agent_context(
    #         service_id=service_name,
    #         workspace_id=state.get("workspace_id"),
    #     )
    # except Exception as e:
    #     logger.warning(f"[Correlation] build_agent_context failed: {e}")

    # ── Second Brain Fase 2: READ (Hybrid Search + confidence boost, non-blocking) ─
    second_brain_context: dict | None = None
    historical_block = ""
    try:
        from services.second_brain import read_similar_episodes
        # timeout 2s agar tidak tambah latency pipeline (prinsip tidak blocking)
        second_brain_context = await asyncio.wait_for(read_similar_episodes(state), timeout=2.0)
        if second_brain_context and second_brain_context.get("similar_episodes", 0) > 0:
            tier = second_brain_context.get("confidence_tier", "INFO_ONLY")
            boost = second_brain_context.get("confidence_boost", 0.0)
            # INFO_ONLY tetap tampil sebagai catatan, tidak boost
            note = " (informational only, do not boost confidence — N<5)" if tier == "INFO_ONLY" else ""
            historical_block = f"""### 0. HISTORICAL CONTEXT — Second Brain ({second_brain_context.get('match_level')}, N={second_brain_context.get('similar_episodes')} valid, boost +{boost:.2f} {tier}{note})
- Probable cause: {second_brain_context.get('probable_cause')} ({second_brain_context.get('probable_cause_ratio',0):.0%} of {second_brain_context.get('total_candidates')} candidates, excluded_wrong={second_brain_context.get('excluded_wrong')})
- Suggested focus: {', '.join(second_brain_context.get('suggested_focus', []))}
- Historical resolution: {second_brain_context.get('historical_resolution')}
- Top matches: {second_brain_context.get('top_matches_brief') or '-'} (top_sim={second_brain_context.get('top_similarity')})
- Tier: {tier} — {"treat as a note only" if tier=="INFO_ONLY" else "use in the analysis and boost confidence according to tier"}

"""
            logger.info(f"[SecondBrain] Context injected for {service_name}: {second_brain_context.get('match_level')} N={second_brain_context.get('similar_episodes')} boost={boost:.3f}")
        elif second_brain_context:
            # N=0 → Unknown Pattern
            historical_block = f"""### 0. HISTORICAL CONTEXT — Second Brain (Unknown Pattern, N=0)
- No similar episodes in the last 30 days for service '{service_name}' — likely a new problem; perform full fan-out analysis.
"""
    except asyncio.TimeoutError:
        logger.warning("[SecondBrain] read_similar_episodes timeout (2s) — lanjut tanpa context")
    except Exception as e:
        logger.warning(f"[SecondBrain] READ failed (non-fatal): {e}")

    # FASE 4A: Span Detail (OTel) — bedakan jelas dari Trace Tempo, truncate jaga token budget
    span_summary = (span_summary_raw[:1500] + " …[truncated]" ) if len(span_summary_raw) > 1500 else span_summary_raw
    if span_summary_raw and span_available:
        span_section = f"""### 3. SPAN DETAIL (OTel — Per-Request Detail)
Source: app_logs_db (span_logs + http_logs) — individual request level, not a Tempo aggregate.
{span_summary}"""
    else:
        span_section = "### 3. SPAN DETAIL (OTel)\n⚠️ Not available or no traceId."

    # FASE 4B downstream: health_result bila ada (fan-out health_agent → correlation)
    if health_result:
        import json as _json
        health_section = f"### 3b. HEALTH CHECK (DB Connectivity)\n{_json.dumps(health_result, indent=2, default=str)[:1200]}"
    else:
        health_section = "### 3b. HEALTH CHECK\n⚠️ No health data (not part of this fan-out)."

    # FE-7: blok knowledge kontekstual dari knowledge_agent (universal + project/workspace)
    knowledge_section = ""
    if state.get("knowledge_context"):
        knowledge_section = (
            f"\n\n---\n### CONTEXTUAL KNOWLEDGE (Universal + Project/Workspace)\n"
            f"{state['knowledge_context']}\n"
        )

    # Fix #49: blok konteks tiket (chat terikat tiket) — grounding jawaban ke subject tiket
    ticket_section = ""
    tc = state.get("ticket_context") or {}
    if tc:
        tags = ", ".join(tc.get("tags") or []) or "-"
        diag = infra_diag_steps(tc.get("title") or "")
        diag_block = f"\n\n{diag}" if diag else ""
        ticket_section = f"""### TICKET CONTEXT — Ticket being discussed by the user
- Ticket: {tc.get('ticketNumber')} · Status: {tc.get('status')} · Severity: {tc.get('severity')} · Kind: {tc.get('kind')} · Source: {tc.get('source')}
- Title: {tc.get('title')}
- Related service: {tc.get('serviceName') or '-'} · Environment: {tc.get('environment') or '-'}
- Tags: {tags}
- Ticket description: {tc.get('description') or '-'}

Note: this analysis is for the ticket above. If observability/log data is thin or empty,
explain from the ticket description what might be happening; stay honest about data limitations.{diag_block}
"""

    # Multi-turn: 2-3 pertanyaan user terakhir (SEKUNDER, bukan bukti analisis)
    conversation_section = ""
    conv = state.get("conversation_history") or []
    user_turns = [c.get("content", "")[:300] for c in conv if c.get("role") == "user"][-3:]
    if user_turns:
        conversation_section = (
            "\n\n---\n### CONVERSATION CONTEXT (secondary — to understand the user's question)\n"
            "This is conversation context only, do NOT treat it as analysis evidence; empirical data "
            "comes from the 4 pillars above.\n"
            + "\n".join(f"- {t}" for t in user_turns)
            + "\n"
        )

    user_prompt = render_prompt(
        "correlation_user",
        historical_block=historical_block,
        doc_context=doc_context,
        knowledge_section=knowledge_section,
        conversation_section=conversation_section,
        ticket_section=ticket_section,
        mongo_summary=mongo_summary,
        metrics_summary=metrics_summary,
        trace_summary=trace_summary,
        span_section=span_section,
        health_section=health_section,
        reply_language=("English" if locale == "en" else "Bahasa Indonesia"),
    )

    try:
        messages = [
            SystemMessage(content=render_prompt("correlation_system")),
            HumanMessage(content=user_prompt),
        ]
        response = await get_chat_llm(temperature=0.2).ainvoke(messages)
        text_resp = response.content

        # Extract root_cause_assessment tag — Fase 2.B fix: regex strict hanya pada tag, hapus fallback substring yang kejebak Historical Context
        import re as _re
        assessment = "unknown"
        _m = _re.search(r"ROOT_CAUSE_ASSESSMENT\s*:\s*\[?\s*(service-fault|downstream|unknown)\s*\]?", text_resp, _re.I)
        if _m:
            assessment = _m.group(1).lower()
        # fallback substring dihapus — jika tag tidak match, tetap unknown (jangan tebak dari narasi)

        correlation_result = {
            "analysis": text_resp,
            "root_cause_assessment": assessment,
            "metrics_available": state.get("metrics_available", False),
            "trace_available": state.get("trace_available", False),
        }

        # ── CHATFLOW V2.1 (Tahap 1): gap, confidence, suggested_next — tanpa LLM ──
        # locale sudah di-resolve di awal fungsi (utk reply_language + teks V2.1).
        data_gaps = _compute_data_gaps(state, locale)
        gap_nodes = [g["node"] for g in data_gaps]
        confidence = _compute_confidence(state, data_gaps)
        suggested_next = _compute_suggested_next(state, data_gaps, confidence, locale)
        # Increment loop counter DI SINI (node), bukan di router — router pure.
        loop_count = state.get("internal_loop_count", 0)
        if confidence < CONFIDENCE_THRESHOLD and loop_count < AUTO_LOOP_MAX:
            loop_count += 1
        base_return = {
            "correlation_result": correlation_result,
            "root_cause_assessment": assessment,
            "episode_id": None,
            "second_brain_context": second_brain_context,
            "agents_visited": agents_visited,
            "investigation_confidence": confidence,
            "data_gaps": data_gaps,
            "gap_nodes": gap_nodes,
            "suggested_next": suggested_next,
            "internal_loop_count": loop_count,
        }

        # ── Second Brain Fase 1: Writer (fire-and-forget, non-blocking) ─────
        try:
            from services.second_brain import generate_episode_id, write_episode_bg
            episode_id = generate_episode_id(service_name)
            # copy state snapshot + inject assessment/result for writer
            state_snapshot = dict(state)
            state_snapshot["root_cause_assessment"] = assessment
            state_snapshot["correlation_result"] = correlation_result
            state_snapshot["episode_id"] = episode_id
            asyncio.create_task(write_episode_bg(state_snapshot, episode_id))
            logger.info(f"[SecondBrain] Episode {episode_id} scheduled for service={service_name}")
            # Gap 2 Fase 3: link episode → ticket (jika ada ticket di context, non-blocking)
            tc = state.get("ticket_context") or {}
            ticket_id = tc.get("ticket_id") or state.get("ticket_id")
            if ticket_id and episode_id:
                try:
                    from services.ticket_store import link_episode_to_ticket
                    asyncio.create_task(link_episode_to_ticket(str(ticket_id), episode_id))
                except Exception as e3:
                    logger.warning(f"[SecondBrain] link_episode_to_ticket scheduling failed (non-fatal): {e3}")
            return {**base_return, "episode_id": episode_id}
        except Exception as e2:
            logger.warning(f"[SecondBrain] scheduling write_episode failed (non-fatal): {e2}")
            return {**base_return, "episode_id": None}

    except Exception as e:
        logger.error(f"CorrelationAgent failed for service='{service_name}': {e}", exc_info=True)
        tc = state.get("ticket_context") or {}
        if tc:
            # Fix #50: LLM gagal tapi ada konteks tiket → grounded fallback, bukan "Gagal" telanjang
            diag = infra_diag_steps(tc.get("title") or "")
            analysis = (
                f"LLM analisis tidak tersedia ({str(e)[:120]}). Ringkasan dari konteks tiket:\n"
                f"Tiket {tc.get('ticketNumber')}: {tc.get('title')} "
                f"(severity {tc.get('severity')}, kind {tc.get('kind')}, env {tc.get('environment') or '-'}).\n"
                f"Service terkait: {tc.get('serviceName') or service_name}.\n"
                f"Deskripsi: {tc.get('description') or 'tidak ada'}\n"
                f"{diag}"
            ) + await llm_unavailable_note_for(state)
        else:
            analysis = f"Correlation Analysis Gagal: {str(e)}" + await llm_unavailable_note_for(state)
        fallback_result = {
            "analysis": analysis,
            "root_cause_assessment": "unknown",
            "metrics_available": state.get("metrics_available", False),
            "trace_available": state.get("trace_available", False),
        }
        # CHATFLOW V2.1: fallback juga hitung gap/confidence (transparansi walau LLM gagal)
        fb_gaps = _compute_data_gaps(state, locale)
        fb_gap_nodes = [g["node"] for g in fb_gaps]
        fb_conf = _compute_confidence(state, fb_gaps)
        fb_next = _compute_suggested_next(state, fb_gaps, fb_conf, locale)
        fb_loop = state.get("internal_loop_count", 0)
        if fb_conf < CONFIDENCE_THRESHOLD and fb_loop < AUTO_LOOP_MAX:
            fb_loop += 1
        fallback_base = {
            "correlation_result": fallback_result,
            "root_cause_assessment": "unknown",
            "episode_id": None,
            "second_brain_context": second_brain_context,
            "agents_visited": agents_visited,
            "investigation_confidence": fb_conf,
            "data_gaps": fb_gaps,
            "gap_nodes": fb_gap_nodes,
            "suggested_next": fb_next,
            "internal_loop_count": fb_loop,
        }
        # Still generate episode_id with unknown assessment (additive, jangan drop)
        try:
            from services.second_brain import generate_episode_id, write_episode_bg
            episode_id = generate_episode_id(service_name)
            state_snapshot = dict(state)
            state_snapshot["root_cause_assessment"] = "unknown"
            state_snapshot["correlation_result"] = fallback_result
            state_snapshot["episode_id"] = episode_id
            asyncio.create_task(write_episode_bg(state_snapshot, episode_id))
            return {**fallback_base, "episode_id": episode_id}
        except Exception:
            return {**fallback_base, "episode_id": None}
