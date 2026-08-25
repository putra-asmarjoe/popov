import asyncio
import logging
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
from state.schema import AgentState
from services.doc_loader import build_agent_context
from services.llm_factory import get_chat_llm
from services.prompt_loader import render as render_prompt
from config.settings import settings

logger = logging.getLogger(__name__)

# Fix #54: LLM dibangun lazily saat invoke (config BYOK dari DB, refresh tanpa restart).

# Fix #53: pesan profesional saat LLM tidak tersedia — dipakai correlation fallback
# & telegram_agent (semua branch LLM). Arahkan user cek config/limit, bukan bingung.
LLM_UNAVAILABLE_NOTE = (
    "\n\n_⚠️ *LLM tidak tersedia saat ini* — analisis AI tidak dapat dihasilkan. "
    "Periksa konfigurasi LLM (provider, model, API key) atau batas kredit pada "
    "dashboard penyedia layanan Anda, lalu kirim ulang pertanyaan._"
)


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


async def correlation_agent(state: AgentState) -> dict:
    """
    Gabungkan ringkasan dari Mongo Agent, Metrics Agent, dan Trace Agent.
    Fase 2: READ Second Brain (Hybrid Search) sebelum LLM untuk prior knowledge.
    Exception safe — Second Brain tidak blocking.
    """
    service_name = state.get("service_name", "unknown")
    mongo_summary = state.get("mongo_summary") or "Log MongoDB: Tidak ada data ringkasan."
    metrics_summary = state.get("metrics_summary") or "Metrics Prometheus: Tidak tersedia."
    trace_summary = state.get("trace_summary") or "Trace Tempo: Tidak tersedia."
    span_summary_raw = state.get("span_summary") or ""
    span_available = state.get("span_available", False)
    health_result = state.get("health_result")
    agents_visited = ["correlation_agent"]

    logger.info(f"CorrelationAgent performing root cause analysis for service='{service_name}'")

    doc_context = (await build_agent_context(service_name)) or "Tidak ada grounding doc khusus."

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
            return {
                "correlation_result": correlation_result,
                "root_cause_assessment": assessment,
                "episode_id": episode_id,
                "second_brain_context": second_brain_context,
                "agents_visited": agents_visited,
            }
        except Exception as e2:
            logger.warning(f"[SecondBrain] scheduling write_episode failed (non-fatal): {e2}")
            return {
                "correlation_result": correlation_result,
                "root_cause_assessment": assessment,
                "episode_id": None,
                "second_brain_context": second_brain_context,
                "agents_visited": agents_visited,
            }

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
            ) + LLM_UNAVAILABLE_NOTE
        else:
            analysis = f"Correlation Analysis Gagal: {str(e)}" + LLM_UNAVAILABLE_NOTE
        fallback_result = {
            "analysis": analysis,
            "root_cause_assessment": "unknown",
            "metrics_available": state.get("metrics_available", False),
            "trace_available": state.get("trace_available", False),
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
            return {
                "correlation_result": fallback_result,
                "root_cause_assessment": "unknown",
                "episode_id": episode_id,
                "second_brain_context": second_brain_context,
                "agents_visited": agents_visited,
            }
        except Exception:
            return {
                "correlation_result": fallback_result,
                "root_cause_assessment": "unknown",
                "episode_id": None,
                "second_brain_context": second_brain_context,
                "agents_visited": agents_visited,
            }
