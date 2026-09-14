"""Conversation state helpers — CHAT3 §5.3 (P2), decisions D-P2.3/D-P2.9.

`build_investigation_context(state)` = DETERMINISTIC summarizer (no LLM):
menyusun `investigation_context` untuk chat_sessions.conversation_state dari
output pipeline yang SUDAH ADA di AgentState (correlation/triage) — persist
dipanggil response_agent di akhir investigasi (D-P2.9), dibaca chat_agent.

Budged: last_findings ≤ ~1600 char (≈400 token — kelas yang sama dengan
aturan K3 collector summary < 500 token). Producer HARUS meringkas/menyalin,
tidak pernah dump utuh (owner ALT3 §9).

Pure function of state — tidak baca DB, tidak panggil LLM.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# CHAT3 §5.3 (D-P2.9): hard cap ~1600 chars (~400 tokens) + penanda truncation.
INVESTIGATION_FINDINGS_MAX_CHARS = 1600
TRUNCATION_MARKER = " ...[truncated]"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cap_findings(text: str, max_chars: int = INVESTIGATION_FINDINGS_MAX_CHARS) -> str:
    """Cap keras + marker — mutatis mutandis pola _truncate_trace_value."""
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip() + TRUNCATION_MARKER


def build_investigation_context(state: dict) -> dict:
    """Susun `investigation_context` dari state investigasi yang selesai.

    Precedence `last_root_cause` (D-P2.9):
        correlation_result.root_cause_assessment
        > state.root_cause_assessment
        > triage_result.hypothesis
        > "unknown"

    `last_findings` (deterministik, NO LLM):
        base = correlation_result.analysis (fallback: triage hypothesis +
        severity + service); service_name + confidence disisipkan bila ada;
        HARD-CAP 1600 char dgn marker.

    Return {} bila TIDAK ada sumber data apa pun (tidak ada correlation_result,
    triage_result, atau root_cause_assessment) — caller skip write; jangan
    tulis "unknown" palsu (K4: no fake data). Unknown-safe: field hilang/None
    tidak pernah raise.

    CHAT3 P3B (D-P3.2): rolling summary helpers — `should_generate_summary`,
    `build_summary_prompt`, `cap_summary` (pure, no DB, no LLM).
    """
    if not isinstance(state, dict):
        return {}

    correlation = state.get("correlation_result") or {}
    if not isinstance(correlation, dict):
        correlation = {}
    triage = state.get("triage_result") or {}
    if not isinstance(triage, dict):
        triage = {}

    analysis = (correlation.get("analysis") or "").strip() if isinstance(correlation.get("analysis"), str) else ""
    corr_rca = (correlation.get("root_cause_assessment") or "").strip()
    state_rca = (state.get("root_cause_assessment") or "").strip()
    hypothesis = (triage.get("hypothesis") or "").strip()
    severity = (triage.get("severity") or "").strip()
    service = (state.get("resolved_service_name") or state.get("service_name") or "").strip()
    confidence: Optional[float] = triage.get("confidence")
    if confidence is None:
        inv_conf = state.get("investigation_confidence")
        if isinstance(inv_conf, (int, float)) and inv_conf > 0:
            confidence = inv_conf

    has_source = bool(correlation) or bool(triage) or bool(state_rca)
    if not has_source:
        return {}

    # ── last_root_cause — precedence chain (D-P2.9) ──────────────────────────
    last_root_cause = corr_rca or state_rca or hypothesis or "unknown"

    # ── last_findings — deterministic composition ────────────────────────────
    lines = []
    if service:
        lines.append(f"service: {service}")
    if analysis:
        lines.append(f"findings: {analysis}")
    else:
        fallback_bits = [b for b in (hypothesis, f"severity: {severity}" if severity else "") if b]
        if fallback_bits:
            lines.append("findings: " + "; ".join(fallback_bits))
        else:
            lines.append("findings: no detailed analysis recorded")
    if confidence is not None:
        try:
            lines.append(f"confidence: {float(confidence):.2f}")
        except (TypeError, ValueError):
            pass

    findings = _cap_findings("\n".join(lines))
    if not findings:
        # Semua sumber kosong-string tapi has_source (mis. correlation_result {} dict) —
        # jangan tulis findings kosong palsu; tetap tulis root cause bila ada.
        findings = last_root_cause

    # ── CHAT3 P3A (D-P3.1): hypotheses[] + last_actions[] ──────────────────
    hypotheses: List[str] = []
    if corr_rca and corr_rca != "unknown":
        hypotheses.append(corr_rca)
    if hypothesis and hypothesis != corr_rca and hypothesis != "unknown":
        hypotheses.append(hypothesis)
    if not hypotheses:
        hypotheses.append("(none — do not invent)")

    last_actions: List[str] = []
    step = (state.get("investigation_step") or "").strip()
    if step:
        last_actions.append(step)
    collectors = state.get("collectors_called") or []
    if isinstance(collectors, list):
        for c in collectors[-5:]:
            if isinstance(c, str) and c:
                last_actions.append(c)
    offers = state.get("offers_made") or []
    if isinstance(offers, list):
        for o in offers[-3:]:
            if isinstance(o, str) and o:
                last_actions.append(f"offer: {o}")

    return {
        "last_findings": findings,
        "last_root_cause": last_root_cause,
        "updated_at": _now_iso(),
        "hypotheses": hypotheses[:5],
        "last_actions": last_actions[:10],
    }


# ── CHAT3 P3B (D-P3.2): rolling conversation_summary ────────────────────────
# Cost-gated: summary hanya tiap SUMMARY_INTERVAL turn DAN bukan low depth.
# No new AgentState fields — turn_count + conversation_summary hidup di
# chat_sessions.conversation_state; chat_depth dibaca dari state (sudah ada).
SUMMARY_INTERVAL = 5
SUMMARY_MAX_CHARS = 800

_SUMMARY_PROMPT_PREFIX = (
    "Summarize this conversation in \u2264200 words (EN). "
    "Focus on: what was discussed, what was found, what remains open. "
    "Be factual, no speculation.\n\n"
    "Conversation:\n"
)


def should_generate_summary(turn_count: int, chat_depth: str) -> bool:
    """Phase 3B: generate summary every SUMMARY_INTERVAL turns, skip on low depth.

    Pure: turn_count kiriman caller = nilai SETELAH increment turn ini
    (conv.turn_count lama + 1). Unknown-safe: turn_count non-int/negatif →
    False. Gate = skip HANYA pada low (garbage/None depth diperlakukan
    seperti medium — extra call lebih aman daripada continuity hilang).
    """
    try:
        n = int(turn_count)
    except (TypeError, ValueError):
        return False
    if (chat_depth or "").strip().lower() == "low":
        return False
    return n > 0 and n % SUMMARY_INTERVAL == 0


def build_summary_prompt(history_block: str) -> str:
    """Prompt EN-canonical utk summary LLM — pure string composition."""
    return _SUMMARY_PROMPT_PREFIX + (history_block or "-")


def cap_summary(text: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """Hard cap summary (EN-canonical, strip). Non-str → ""."""
    if not isinstance(text, str):
        return ""
    t = text.strip()
    return t[:max_chars] if len(t) > max_chars else t
