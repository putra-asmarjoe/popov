"""CHAT3 Phase 2 — Conversational lane (chat_agent).

Spec: devdocs/chat/CHAT3.md §5.1-5.6 + CHAT3-IMPL-NOTES.md D-P2.0..D-P2.12.

Position (K1/K7): fallback lane — reached ONLY when supervisor's deterministic
gates matched nothing AND effective chat_depth in (medium, thinking). Pure
insertion inside `if not matched_service:` — no gate reorder. K6: Telegram
never sends mode → default "low" → lane structurally unreachable.

Lane = operational conversation (stance → evidence → recommendation →
next-step offer), NOT a generic fallback chatbot (K8). ONE LLM call per turn
(§5.2), grounded in conversation_state (chat_sessions) + project context —
never re-collects observability data (K3). Grounding: facts only from context,
inference allowed, correlation never stated as causation; FACTS / EVIDENCE /
HYPOTHESES / UNCERTAINTIES are prompt-internal sections (never shown).

Topic memory (§5.3): ONE conversation_state object per chat session.
  - topic_context + current_intent  → written by THIS lane end-of-turn
  - investigation_context           → written by response_agent (D-P2.9)
Topic shift is FIRST-CLASS: a newly named service overwrites topic_context and
re-anchors (resets) investigation_context — stale last_findings must never
leak across topics. The shift is detected from the same LLM turn, so the
prompt for this turn still carries the OLD context; the system prompt enforces
"discuss the new service only", then the shift is persisted.

Turn metadata (D-P2.10): trailing tagged lines CURRENT_INTENT / TOPIC_SERVICE /
RESOLVED_REF regex-parsed correlation-style (correlation_agent.py pattern);
no JSON mode. Emitted TOPIC_SERVICE is validated against the service list —
hallucinated topics rejected. Missing tags → safe defaults (intent
follow_up, topic unchanged).

Return contract (D-P2.7) — identical keys to response_agent so the key-driven
meta build + _resolve_chat_answer + persist + SSE work unchanged:
  {formatted_message, telegram_sent, telegram_error, next_agent: "end",
   agents_visited, chat_suggestions?, context_pill?}

CHAT3 Phase 4 (D-P4) — agentic tool lane (see devdocs/chat/PHASE4_DESIGN.md):
  - Turn 1 (plan): lane LLM may emit TOOL_CALL lines (read-only catalogue in
    the user prompt). Parsed quote/comma-aware; unknown tools skipped.
  - Tool execution is NON-LLM (adapters → real signatures, creds server-side).
  - Turn 2 (reply): the ORIGINAL plan-turn reply text is replaced
    DETERMINISTICALLY by formatted tool results — no second reply LLM call.
    §5.2 "single LLM call" now means single REPLY-SHAPING call per turn;
    see D-P4.1. Total extra wall-clock bounded by MAX_TOOLS_PER_TURN ×
    TOOL_TIMEOUT_S; lane timeout envelope raised (LANE_TIMEOUT_S_P4).
  - Budget: max 5 tools/turn (hard slice) + session_tool_count persisted in
    conversation_state (cap 25). record_call() on ALL attempts.
  - Write tools are NOT in the LLM catalogue; a write TOOL_CALL becomes a
    needs_confirmation entry surfaced as a confirmation chip — never executed.
"""
from __future__ import annotations

import asyncio
import contextlib as _contextlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from state.schema import AgentState
from services.prompt_loader import render as render_prompt
from services.llm_factory import get_chat_llm
from services.conversation import resolve_state_locale

logger = logging.getLogger(__name__)

LANE_TIMEOUT_S = 8.0  # §5.4: same timeout class as other LLM points

# ── CHAT3 P4 (D-P4.1): agentic tool lane — §5.2 amended ─────────────────────
# Turn 1 = plan LLM (≤8s). Tools run non-LLM afterwards; turn 2 reuses the
# ORIGINAL reply deterministically (no second reply LLM call). Envelope must
# cover plan call + worst-case tool fan-out sequentially.
# M1 option (b): §5.2 formally amended — "single REPLY-SHAPING LLM call".
LANE_TIMEOUT_S_P4 = 48.0  # 8s plan + 5 tools × 8s sequential worst case

# P4 tool-call gate (cost guard, same class as P3B summary gate): tools run
# only at these depths. Low (incl. Telegram default) = reply-only, no tools.
TOOL_DEPTHS = ("medium", "thinking")

INTENT_VALUES = ("explain", "investigate", "compare", "recommend", "execute", "clarify", "follow_up")
DEFAULT_INTENT = "follow_up"  # D-P2.10: missing tag → safe default

_CURRENT_TOPIC_MAX = 120

# ── Tag parsing (correlation_agent regex style — strict, no narrative fallback) ──
_INTENT_RE = re.compile(
    r"CURRENT_INTENT\s*:\s*\[?\s*(explain|investigate|compare|recommend|execute|clarify|follow_up)\s*\]?",
    re.IGNORECASE,
)
_TOPIC_RE = re.compile(r"TOPIC_SERVICE\s*:\s*\[?\s*([A-Za-z0-9_.\-]+)\s*\]?", re.IGNORECASE)
_REF_RE = re.compile(r"RESOLVED_REF\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_META_LINE_RE = re.compile(r"^\s*(CURRENT_INTENT|TOPIC_SERVICE|RESOLVED_REF)\s*:", re.IGNORECASE)
_SUGGESTION_RE = re.compile(r"^\s*SUGGESTION\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

# ── Deterministic fallback (K4 — no fake success, no invented data) ─────────────
_FALLBACK_REPLY = {
    "en": (
        "I couldn't compose a full answer just now (my language model did not respond in time). "
        "I don't want to guess without data. "
        "{offer}"
    ),
    "id": (
        "Saya belum bisa menyusun jawaban lengkap saat ini (model bahasa tidak merespons tepat waktu). "
        "Saya tidak ingin menebak tanpa data. "
        "{offer}"
    ),
}
_FALLBACK_OFFER = {
    "en": "Want me to check the current status or metrics of {service}?",
    "id": "Mau saya cek status atau metrics {service} sekarang?",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render_history(history: Optional[List[dict]]) -> str:
    """Render history untuk prompt. History SUDAH depth-sized (api/chat.py P1
    window 10×400/14×500) — jangan dipotong lagi di sini (§5.2 input #1)."""
    if not history:
        return "-"
    return "\n".join(f"[{h.get('role')}] {h.get('content', '')}" for h in history)


def _summary_history_messages(history_block: str) -> List:
    """CHAT3 P3B (D-P3.2): summary LLM input sebagai [HumanMessage] (bukan raw
    dict) — ChatOpenAI.ainvoke menerima string | BaseMessage | list; raw dict
    {role, content} tidak dijamin valid di semua versi langchain-core."""
    from services.conversation_state import build_summary_prompt

    return [HumanMessage(content=build_summary_prompt(history_block))]


async def _service_names(state: dict) -> List[str]:
    """Service identifiers untuk validasi TOPIC_SERVICE — sumber baca yang SAMA
    dengan yang dipakai routing (doc_loader) + konteks workspace/project (K5).
    Baca murah, tanpa LLM; failure per-sumber ditelan (best-effort list)."""
    names: set = set()
    try:
        from services.doc_loader import list_all_services

        names |= set((await list_all_services() or {}).keys())
    except Exception as e:
        logger.warning(f"[ChatAgent] service list (doc_loader) gagal: {e}")
    ws_id = state.get("workspace_id")
    if ws_id:
        try:
            from services.workspace_service_registry import list_for_workspace

            for item in (await list_for_workspace(str(ws_id), enabled_only=True)) or []:
                sid = item.get("service_id") or item.get("serviceId")
                if sid:
                    names.add(str(sid))
        except Exception as e:
            logger.warning(f"[ChatAgent] service list (registry) gagal: {e}")
    if state.get("project_id"):
        try:
            from services.service_store import service_ids_for_project

            names |= set(await service_ids_for_project(str(state["project_id"])))
        except Exception as e:
            logger.warning(f"[ChatAgent] service list (project refs) gagal: {e}")
    return sorted(n for n in names if n)


def _ticket_facts(state: dict) -> List[str]:
    """Facts tiket dari state — HANYA yang benar-benar ada (K4: no fabrication)."""
    facts: List[str] = []
    tc = state.get("ticket_context") or {}
    if tc:
        facts.append(
            f"- current ticket: {tc.get('ticketNumber') or '(unnumbered)'} — "
            f"{(tc.get('title') or '')[:100]} (status={tc.get('status') or '-'}, "
            f"severity={tc.get('severity') or '-'}, service={tc.get('serviceName') or '-'})"
        )
    return facts


async def _project_ticket_facts(state: dict) -> List[str]:
    """Open ticket count/titles — hanya bila sesi punya project (K5-scoped read).
    Reuse ticket_store reads (pola project_agent), tanpa query baru di luar itu."""
    project_id = state.get("project_id")
    if not project_id:
        return []
    try:
        from services.ticket_store import OPEN_STATUSES, recent_tickets_by_project

        recent = await recent_tickets_by_project(str(project_id), since_hours=None, limit=20)
        open_tickets = [t for t in (recent or []) if (t.get("status") or "") in OPEN_STATUSES]
        if not open_tickets:
            return ["- open tickets in project: 0"]
        titles = "; ".join(
            f"{t.get('projectKey') or '?'}-{t.get('ticketNumber')} {(t.get('title') or '')[:60]}"
            for t in open_tickets[:5]
        )
        more = f" (+{len(open_tickets) - 5} more)" if len(open_tickets) > 5 else ""
        return [f"- open tickets in project: {len(open_tickets)} — {titles}{more}"]
    except Exception as e:
        logger.warning(f"[ChatAgent] project ticket facts gagal: {e}")
        return []


def _episodes_block(second_brain: Optional[dict]) -> str:
    """Render hasil read_similar_episodes (reuse reader — bukan collection baru)."""
    if not second_brain:
        return "(no similar episodes on record)"
    lines: List[str] = []
    matches = second_brain.get("top_matches") or []
    if matches:
        for m in matches[:3]:
            lines.append(
                f"- {m.get('episode_id') or '(episode)'}: root_cause={m.get('root_cause') or 'unknown'}, "
                f"feedback={m.get('feedback') or 'none'}"
            )
    probable = second_brain.get("probable_cause")
    if probable and probable != "unknown":
        lines.append(f"- historical probable cause: {probable} (informational, not verified this turn)")
    if not lines:
        return "(no similar episodes on record)"
    return "\n".join(lines)


def _build_sections(
    *,
    topic_service: str,
    ticket_facts: List[str],
    project_facts: List[str],
    investigation: dict,
    episodes_text: str,
    conversation_summary: str = "",
) -> Tuple[str, str, str, str]:
    """FACTS / EVIDENCE / HYPOTHESES / UNCERTAINTIES — prompt-internal (§5.2).

    Deterministik; HANYA berisi data yang benar-benar ada. Bagian kosong
    diberi penanda eksplisit TANPA angka (hallucination guard §5.6.9: tidak ada
    nilai tiruan untuk di-echo model).
    """
    findings = (investigation.get("last_findings") or "").strip()
    last_rca = (investigation.get("last_root_cause") or "").strip()

    # FACTS — nilai deterministik dari konteks sesi/project
    facts = list(ticket_facts) + list(project_facts)
    facts.insert(0, f"- active topic service: {topic_service or '(none yet)'}")

    # CHAT3 P3B (D-P3.2): conversation_summary → FACTS block (long-session
    # continuity). Unknown-safe: hanya inject bila non-empty string; kwarg
    # eksplisit (bukan dari `investigation`) agar kontrak pemanggil jelas.
    _summary = (conversation_summary or "").strip()
    if _summary:
        facts.append(
            "[CONVERSATION SUMMARY]\n"
            "(how we got here — summary of prior turns)\n"
            + _summary
        )

    # EVIDENCE — temuan investigasi tercatat + episode historis (data nyata)
    evidence: List[str] = []
    if findings:
        evidence.append(f"- last investigation findings:\n{findings}")
    if last_rca:
        evidence.append(f"- last recorded root cause: {last_rca}")
    evidence.append(f"- similar past episodes:\n{episodes_text}")

    # HYPOTHESES — interpretasi plausibel, SELALU berlabel belum terverifikasi
    hypotheses: List[str] = []
    if last_rca and last_rca != "unknown":
        hypotheses.append(
            f"- {last_rca} remains the leading hypothesis from the previous investigation "
            "(verify before asserting causation)"
        )
    if not hypotheses:
        hypotheses.append("(none — do not invent)")

    # UNCERTAINTIES — apa yang TIDAK ada di konteks (anti-hallucination anchor)
    uncertainties = [
        "- no live data was collected this turn: quote numbers only from EVIDENCE above; "
        "anything else must be offered as a check, not stated",
    ]
    if not findings:
        uncertainties.append("- no investigation findings recorded for this session yet")
    if not last_rca or last_rca == "unknown":
        uncertainties.append("- root cause not yet established")

    # ── CHAT3 P3A (D-P3.1): hypotheses[] + last_actions[] from investigation_context ──
    hyp_list = investigation.get("hypotheses") or []
    if isinstance(hyp_list, list) and hyp_list:
        hyp_block = "[INVESTIGATION HYPOTHESES]\n" + "\n".join(f"- {h}" for h in hyp_list)
        facts.append(hyp_block)

    act_list = investigation.get("last_actions") or []
    if isinstance(act_list, list) and act_list:
        act_block = "[ACTIONS TAKEN]\n" + "\n".join(f"- {a}" for a in act_list)
        facts.append(act_block)

    return "\n".join(facts), "\n".join(evidence), "\n".join(hypotheses), "\n".join(uncertainties)


def _parse_turn_metadata(reply: str) -> Dict[str, Any]:
    """Regex-parse trailing tagged lines (D-P2.10, correlation style)."""
    intent = DEFAULT_INTENT
    topic_service: Optional[str] = None
    resolved_ref: Optional[Dict[str, str]] = None
    if reply:
        m = _INTENT_RE.search(reply)
        if m:
            intent = m.group(1).lower()
        m = _TOPIC_RE.search(reply)
        if m:
            topic_service = m.group(1).strip().lower()
        m = _REF_RE.search(reply)
        if m:
            raw = m.group(1).strip()
            for sep in ("→", "->"):
                if sep in raw:
                    original, resolved = raw.split(sep, 1)
                    original = original.strip().strip("\"'")
                    resolved = resolved.strip().strip("\"'")
                    if original and resolved:
                        resolved_ref = {"original": original, "resolved": resolved.lower()}
                    break
    return {"intent": intent, "topic_service": topic_service, "resolved_ref": resolved_ref}


def _strip_metadata_lines(reply: str) -> str:
    """Tagged lines tidak pernah tampil ke user."""
    from services.tool_executor import _TOOL_RE  # local: hindari import cycle

    out = []
    for line in (reply or "").splitlines():
        if _META_LINE_RE.match(line):
            continue
        if _TOOL_RE.match(line):  # P4: TOOL_CALL lines never shown
            continue
        out.append(line)
    return "\n".join(out).strip()


# ── CHAT3 P4 (D-P4): tool lane helpers ───────────────────────────────────────
_P4_TOOL_INTRO = {
    "en": "Here's what I found:",
    "id": "Berikut hasil pengecekan saya:",
}
_P4_TOOL_FAIL_NOTE = {
    "en": "(some checks failed — results below are partial)",
    "id": "(sebagian pengecekan gagal — hasil di bawah ini parsial)",
}
_P4_CONFIRM_TEXT = {
    "en": 'Reply "yes" to confirm: {label}',
    "id": 'Balas "ya" untuk konfirmasi: {label}',
}


def _build_tools_block() -> str:
    """C4: LLM-visible tool catalogue (read-only only — M2)."""
    from services.tool_registry import format_tools_for_llm

    return (
        "[AVAILABLE TOOLS]\n"
        "To check live data, emit one TOOL_CALL line per tool (each on its own "
        "line). Syntax: TOOL_CALL: <name> key=value, key2=value2 — quote values "
        "containing commas. Credentials are resolved server-side; never pass "
        "passwords, tokens, URLs, or workspace ids. Max 5 calls per turn. "
        "Read-only checks run automatically; anything else needs confirmation.\n"
        + format_tools_for_llm()
    )


@_contextlib.asynccontextmanager
async def _p4_envelope():
    """M1(b): lane wall-clock envelope — plan call + sequential tool fan-out.
    asyncio.wait_for around the whole execution block; partial results are
    kept by the caller (timeout there surfaces as TimeoutError)."""
    try:
        async with asyncio.timeout(LANE_TIMEOUT_S_P4):
            yield
    except AttributeError:
        # Python 3.9/3.10: no asyncio.timeout — unbounded (per-tool timeouts
        # still apply via wait_for inside execute_tool_calls).
        yield


def _format_tool_reply(results: list, locale: str) -> str:
    """M1(a): deterministic tool-result reply — NO second LLM call.
    Prose + per-tool bullets; failures shown honestly (K4, non-fatal)."""
    intro = _P4_TOOL_INTRO.get(locale, _P4_TOOL_INTRO["en"])
    lines = [intro]
    if results and all(not r.get("ok") for r in results
                        if not r.get("needs_confirmation")):
        note = _P4_TOOL_FAIL_NOTE.get(locale, _P4_TOOL_FAIL_NOTE["en"])
        lines.append(note)
    for r in results or []:
        name = r.get("name", "?")
        if r.get("needs_confirmation"):
            label = f"{name} {r.get('params') or {}}"
            confirm = _P4_CONFIRM_TEXT.get(locale, _P4_CONFIRM_TEXT["en"])
            lines.append(f"- `{name}`: {confirm.format(label=label)}")
            continue
        status = "\u2705" if r.get("ok") else "\u26a0\ufe0f"
        lines.append(f"{status} `{name}`: {(r.get('result') or '')[:600]}")
    return "\n".join(lines).strip()


def _validate_topic(new_service: Optional[str], services: List[str]) -> Optional[str]:
    """TOPIC_SERVICE valid = ada di service list (case-insensitive) → canonical form.
    Unknown/hallucinated topic → None (D-P2.10)."""
    if not new_service:
        return None
    lowered = new_service.lower()
    for s in services:
        if s.lower() == lowered:
            return s
    return None


def _validate_ref_value(ref: Optional[Dict[str, str]], services: List[str]) -> Optional[Dict[str, str]]:
    """RESOLVED_REF hanya di-emit bila nilainya identifier service yang dikenal —
    hallucination guard (konsisten dengan TOPIC_SERVICE)."""
    if not ref:
        return None
    lowered = ref["resolved"].lower()
    for s in services:
        if s.lower() == lowered:
            return {"original": ref["original"], "resolved": s}
    return None


def _fallback_reply(service: Optional[str], locale: str) -> str:
    """K4: LLM gagal/timeout → jujur admit limitation + tawaran cek, TANPA data
    karangan (tanpa angka). Bilingual via dict (pola Fix #201)."""
    offer = _FALLBACK_OFFER.get(locale, _FALLBACK_OFFER["en"]).format(service=service or "the affected service")
    return _FALLBACK_REPLY.get(locale, _FALLBACK_REPLY["en"]).format(offer=offer)


def _lane_suggestions(
    *,
    service: str,
    last_rca: str,
    locale: str,
    message: str,
    history: Optional[List[dict]],
    project_id: Optional[str],
    ticket_ctx: Optional[dict],
    context: Optional[dict] = None,
) -> List[str]:
    """2-3 chips via infrastruktur existing (C7 / D-P2.7). Plain strings — FE
    memperlakukan missing type sebagai ACTION (kontrak §4A.7, additive).

    CHAT6 P6.3: `context` = conversation_state fields untuk offer_planner
    context mapping (chips kontekstual tool/non-tool turns). Non-fatal: failure
    → deterministic investigate chip fallback (K4, unchanged)."""
    try:
        from services.offer_planner import build_chat_suggestions

        chips = build_chat_suggestions(
            ticket=ticket_ctx or None,
            project={"id": project_id} if project_id else None,
            service_name=service,
            root_cause=last_rca or "unknown",
            has_open_tickets=False,
            want_knowledge=bool(project_id),
            locale=locale,
            intent=message,
            asked_intents=[h.get("content") for h in (history or []) if h.get("role") == "user"],
            context=context,
        )
        if chips:
            return chips[:3]
    except Exception as e:
        logger.warning(f"[ChatAgent] build_chat_suggestions gagal: {e}")
    # Fallback deterministik: chip investigate (satu sumber teks: offer_planner)
    if service:
        try:
            from services.offer_planner import chat_suggestion

            return [chat_suggestion("investigate", locale, svc=service)]
        except Exception:
            return []
    return []


async def chat_agent(state: AgentState) -> dict:
    """Conversational lane node — single LLM turn over operational context (§5.2)."""
    message = (state.get("message_raw") or state.get("intent") or "").strip()
    agents_visited = state.get("agents_visited", []) + ["chat_agent"]
    locale = await resolve_state_locale(state)
    reply_language = "English" if locale == "en" else "Bahasa Indonesia"

    sender = state.get("sender") or {}
    session_id = sender.get("session_id") or state.get("session_id") or ""
    suppress_telegram = bool(state.get("suppress_telegram"))

    # ── Input assembly (§5.2): conversation_state + project context (cheap reads,
    #    K3 — reuse, never re-collect). ──────────────────────────────────────────
    conv_state: dict = {}
    if session_id:
        try:
            from services.chat_store import get_conversation_state

            conv_state = await get_conversation_state(str(session_id))
        except Exception as e:
            logger.warning(f"[ChatAgent] get_conversation_state gagal (non-fatal): {e}")
    topic_context = conv_state.get("topic_context") or {}
    investigation = conv_state.get("investigation_context") or {}
    topic_service = (topic_context.get("active_service") or "").strip()
    # CHAT3 P3B (D-P3.2): summary + turn counter read (non-fatal get di atas).
    conv_summary = conv_state.get("conversation_summary") \
        if isinstance(conv_state.get("conversation_summary"), str) else ""

    services = await _service_names(state)
    ticket_facts = _ticket_facts(state)
    project_facts = await _project_ticket_facts(state)

    # Second-brain reader di service TOPIK aktif (bukan re-collection) — None-safe.
    second_brain: Optional[dict] = None
    if topic_service:
        try:
            from services.second_brain import read_similar_episodes

            second_brain = await read_similar_episodes(
                dict(state, service_name=topic_service), limit=3
            )
        except Exception as e:
            logger.warning(f"[ChatAgent] read_similar_episodes gagal (non-fatal): {e}")

    facts, evidence, hypotheses, uncertainties = _build_sections(
        topic_service=topic_service,
        ticket_facts=ticket_facts,
        project_facts=project_facts,
        investigation=investigation,
        episodes_text=_episodes_block(second_brain),
        conversation_summary=conv_summary,
    )

    # ── CHAT3 P4 (D-P4, C4): tool catalogue → system prompt (convention:
    #    prompt file preferred). tools_block var exists in chat_agent_user.md;
    #    render_prompt leaves unknown vars untouched so old-file deploys stay
    #    valid — but we pass it explicitly here. ────────────────────────────
    _tools_allowed = (state.get("chat_depth") or "low") in TOOL_DEPTHS
    user_prompt = render_prompt(
        "chat_agent_user",
        message=message or "-",
        history_block=_render_history(state.get("conversation_history")),
        facts=facts,
        evidence=evidence,
        hypotheses=hypotheses,
        uncertainties=uncertainties,
        services_block="\n".join(f"- {s}" for s in services) if services else "(no services registered)",
        topic_service=topic_service or "(none yet)",
        service_list=", ".join(services) if services else "(unknown)",
        reply_language=reply_language,
        tools_block=_build_tools_block() if _tools_allowed else "",
    )

    # ── Single LLM call (§5.4: satu panggilan, ≤8s, tanpa fan-out) ────────────
    reply_text = ""
    try:
        llm = get_chat_llm(temperature=0.3)
        response = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content=render_prompt("chat_agent_system", reply_language=reply_language)),
                    HumanMessage(content=user_prompt),
                ]
            ),
            timeout=LANE_TIMEOUT_S,
        )
        reply_text = (getattr(response, "content", "") or "").strip()
    except Exception as e:
        logger.warning(f"[ChatAgent] LLM call gagal → deterministic fallback: {e}")
        reply_text = ""

    parsed = _parse_turn_metadata(reply_text)
    clean_reply = _strip_metadata_lines(reply_text)
    if not clean_reply:
        # K4: jangan fake success — fallback jujur, tanpa angka karangan.
        clean_reply = _fallback_reply(topic_service or None, locale)

    # ── CHAT3 P4 (D-P4): agentic tool execution ─────────────────────────────
    # Turn 1 (plan) done above. Parse TOOL_CALL → execute read-only tools →
    # replace reply DETERMINISTICALLY (M1-a: no second reply LLM call).
    # Gated: tools only at medium/thinking (low = reply-only, K6 cost guard).
    # Non-fatal: tool failure → graceful fallback, lane never crashes.
    tool_results: list = []
    pending_confirmations: list = []
    new_session_tool_count: Optional[int] = None
    synthesis_succeeded = False
    synthesis_attempted = False
    _syn_text = ""
    # CHAT6 P6.3 (W1): last successfully-executed read-only tool this turn
    # (persisted to conversation_state for chip context) + a service derived
    # from tool params (ONLY the explicit `service` param — trivially derivable).
    last_tool_used: Optional[str] = None
    _tool_service: Optional[str] = None
    if _tools_allowed and reply_text:
        from services.tool_executor import (
            ToolBudget, execute_tool_calls, format_tool_results, parse_tool_calls,
        )
        from services.tool_registry import MAX_TOOLS_PER_TURN

        _parsed_calls = parse_tool_calls(reply_text)
        if _parsed_calls:
            _parsed_calls = _parsed_calls[:MAX_TOOLS_PER_TURN]  # C3: hard slice
            try:
                _prev_tool_count = int(conv_state.get("session_tool_count") or 0)
            except (TypeError, ValueError):
                _prev_tool_count = 0
            _budget = ToolBudget(max_per_turn=MAX_TOOLS_PER_TURN,
                                 session_count=_prev_tool_count)
            _tool_ctx: dict = {
                # topic_service hint: current active topic (plan-turn context).
                # Adapters fall back to state.service_name when empty.
                "state": dict(state, topic_service=topic_service),
            }
            try:
                from services.observability_store import (
                    get_central_log_config_for_state, get_observ_config_for_state,
                    resolve_k8s_targets_for_state,
                )
                _tool_ctx["observ_cfg"] = await get_observ_config_for_state(state) or {}
                _tool_ctx["k8s_targets"] = await resolve_k8s_targets_for_state(state) or []
                _tool_ctx["log_cfg"] = await get_central_log_config_for_state(dict(state))
            except Exception as e:
                logger.warning(f"[ChatAgent] tool ctx resolve gagal (non-fatal): {e}")
                _tool_ctx.setdefault("observ_cfg", {})
                _tool_ctx.setdefault("k8s_targets", [])
                _tool_ctx.setdefault("log_cfg", None)
            try:
                async with _p4_envelope():
                    tool_results, _budget = await execute_tool_calls(
                        _parsed_calls, _tool_ctx, _budget)
            except asyncio.TimeoutError:
                logger.warning("[ChatAgent] tool envelope timeout — partial results kept")
            new_session_tool_count = _budget.session_count
            pending_confirmations = [r for r in tool_results if r.get("needs_confirmation")]
            _read_results = [r for r in tool_results if not r.get("needs_confirmation")]
            # CHAT6 P6.3 (W1): last successful read-only tool (for
            # conversation_state.last_tool_used) + service derivation from the
            # explicit `service` param (nothing else is trivially derivable —
            # prom_instant carries promql, not a service id).
            for _r in _read_results:
                if _r.get("ok") and _r.get("name"):
                    last_tool_used = _r["name"]
                    break
            for _r in _read_results:
                # Review fix (Major 2): ONLY a successful tool result may hint
                # a service — a failed check reveals nothing.
                if not _r.get("ok"):
                    continue
                _psvc = (_r.get("params") or {}).get("service")
                if _psvc:
                    _tool_service = str(_psvc)
                    break
            if _read_results:
                # P5.5 R1: synthesis pass — re-answer with tool data in hand.
                # Build synthesis prompt: same context block as call #1, user message,
                # original plan-prose as reference, tool results as structured data.
                _tool_data_block = format_tool_results(_read_results)
                _synthesis_prompt = (
                    f"Conversation inputs (current turn):\n\n"
                    f"USER MESSAGE:\n{message or '-'}\n\n"
                    f"{facts}\n\n"
                    f"{evidence}\n\n"
                    f"{hypotheses}\n\n"
                    f"{uncertainties}\n\n"
                    f"Currently active topic service: {topic_service or '(none yet)'}\n\n"
                    f"---\n\n"
                    f"TOOL DATA (now available — re-answer the user):\n"
                    f"{_tool_data_block}\n\n"
                    f"ORIGINAL PLAN (your first draft — do NOT copy its hedging):\n"
                    f"{clean_reply}"
                )
                synthesis_attempted = True
                try:
                    _syn_llm = get_chat_llm(temperature=0.3)
                    _syn_resp = await asyncio.wait_for(
                        _syn_llm.ainvoke([
                            SystemMessage(content=render_prompt(
                                "chat_agent_synthesis",
                                reply_language=reply_language,
                                tool_data_block=_tool_data_block,
                                plan_prose=clean_reply,
                            )),
                            HumanMessage(content=_synthesis_prompt),
                        ]),
                        timeout=LANE_TIMEOUT_S,
                    )
                    _syn_text = (getattr(_syn_resp, "content", "") or "").strip()
                    if _syn_text:
                        # Strip ALL metadata lines (CURRENT_INTENT, TOPIC_SERVICE, RESOLVED_REF)
                        # before assigning to clean_reply. SUGGESTION lines are stripped
                        # separately at :782 after being parsed for chat_suggestions.
                        clean_reply = _strip_metadata_lines(_syn_text)
                        synthesis_succeeded = True
                except Exception as e:
                    logger.warning(f"[ChatAgent] synthesis LLM failed → fallback to append: {e}")
                if not synthesis_succeeded:
                    # K4: fallback to M1(a) deterministic append — never crash the lane.
                    # P6.1 GAP-B: append the compact user-facing rendering
                    # (_format_tool_reply: labeled bullets, truncated, bilingual
                    # intro) — the raw "[TOOL RESULTS]" LLM-context header
                    # (_tool_data_block, tool_executor.format_tool_results) is
                    # prompt-internal and must never reach the user-visible reply.
                    clean_reply = (clean_reply + "\n\n"
                                   + _format_tool_reply(_read_results, locale)).strip() \
                        if clean_reply else _format_tool_reply(_read_results, locale)

    # ── Topic shift (first-class, §5.3) ────────────────────────────────────────
    # TOPIC_SERVICE tervalidasi ≠ topik aktif → overwrite topic_context +
    # RE-ANCHOR investigation_context (reset) — stale findings tidak lolos.
    new_service = _validate_topic(parsed.get("topic_service"), services)
    topic_shift = bool(new_service and new_service != topic_service)
    effective_service = new_service or topic_service
    # CHAT6 P6.3 (W1): tool revealed a service (explicit `service` param on a
    # SUCCESSFUL result) and no topic is set → adopt it so
    # topic_context.active_service persists it. Review fix (Major 2): the
    # candidate passes the SAME hallucination guard as LLM-emitted topics —
    # a service the platform does not know is never adopted.
    _validated_tool_service = _validate_topic(_tool_service, services) \
        if _tool_service else None
    if not effective_service and _validated_tool_service:
        effective_service = _validated_tool_service

    # ── Persist conversation_state (best-effort, non-fatal — K4) ──────────────
    # CHAT3 P3B (D-P3.2): rolling summary — turn_count increment TIAP turn;
    # summary LLM call HANYA saat should_generate_summary (N=5, skip low).
    # History utk summary = state.conversation_history state-side (P1 window),
    # dirender ulang via _render_history (tanpa DB read tambahan); engsel DB
    # tambahan get_messages tidak dipakai (K3 — single source, no re-collect).
    new_turn_count: Optional[int] = None
    if session_id:
        try:
            _prev_turn = conv_state.get("turn_count") or 0
            new_turn_count = int(_prev_turn) + 1
        except (TypeError, ValueError):
            new_turn_count = 1
    if session_id:
        try:
            from services.chat_store import update_conversation_state

            ticket_number = (state.get("ticket_context") or {}).get("ticketNumber")
            topic_ctx = {
                "active_service": effective_service or None,
                "ticket_id": ticket_number,
                "current_topic": message[:_CURRENT_TOPIC_MAX],
                "updated_at": _now_iso(),
            }
            await update_conversation_state(
                str(session_id),
                topic_context=topic_ctx,
                reset_investigation=topic_shift,
                current_intent=parsed["intent"],
                turn_count=new_turn_count,
                # P4 (C3): persist cumulative session tool budget.
                **({"session_tool_count": new_session_tool_count}
                   if new_session_tool_count is not None else {}),
                # CHAT6 P6.3 (W1): last read-only tool — chip context.
                **({"last_tool_used": last_tool_used}
                   if last_tool_used else {}),
            )
        except Exception as e:
            logger.warning(f"[ChatAgent] update_conversation_state gagal (non-fatal): {e}")

    # ── CHAT3 P3B (D-P3.2): rolling summary generation (cost-gated) ──────────
    # Syarat: turn_count % 5 == 0 DAN chat_depth != low (skip low = K6).
    # LLM call TERPISAH dari lane call (§5.2 "single LLM call" = jawaban user;
    # summary adalah persist-side write-back seperti offer/knowledge writes).
    # Non-fatal total: LLM gagal → turn_count TETAP naik (persist di atas).
    if new_turn_count is not None and session_id:
        try:
            from services.conversation_state import (
                build_summary_prompt,
                cap_summary,
                should_generate_summary,
            )

            _chat_depth = state.get("chat_depth") or "low"
            if should_generate_summary(new_turn_count, _chat_depth):
                try:
                    _history = state.get("conversation_history") or []
                    _history_block = _render_history(_history)
                    _summary_llm = get_chat_llm(temperature=0.3)
                    _summary_resp = await asyncio.wait_for(
                        _summary_llm.ainvoke(
                            _summary_history_messages(_history_block)
                        ),
                        timeout=LANE_TIMEOUT_S,
                    )
                    _summary = cap_summary(getattr(_summary_resp, "content", "") or "")
                    if _summary:
                        try:
                            from services.chat_store import update_conversation_state as _update_cs

                            await _update_cs(
                                str(session_id), conversation_summary=_summary
                            )
                        except Exception as e:
                            logger.warning(
                                f"[ChatAgent] summary persist gagal (non-fatal): {e}"
                            )
                except Exception as e:
                    logger.warning(f"[ChatAgent] summary generation failed: {e}")
        except Exception as e:
            logger.warning(f"[ChatAgent] summary gate gagal (non-fatal): {e}")

    # ── P4 (M2): write-tool confirmation chip ───────────────────────────────
    # Write TOOL_CALLs are NEVER executed — surfaced as a confirmation chip
    # (plain-string suggestion, FE treats missing type as ACTION). The chip
    # text names the tool + params so "yes" can be routed to execution later.
    # Read-only suggestions below are unchanged.
    # ── Suggestions (C7 infra) + optional proactive investigate offer ─────────
    # Web-only (pola response_agent — chat_suggestions/context_pill adalah
    # metadata channel web; Telegram structurally unreachable via depth gate).
    chat_suggestions: List[str] = []
    # P4 (M2) confirmations FIRST so _lane_suggestions extend keeps them.
    if suppress_telegram and pending_confirmations:
        for _pc in pending_confirmations[:2]:
            _plabel = f"{_pc.get('name')} {(_pc.get('params') or {})}"
            chat_suggestions.append(
                _P4_CONFIRM_TEXT.get(locale, _P4_CONFIRM_TEXT["en"]).format(label=_plabel)
            )
    # P5.5 R2: SUGGESTION chips from synthesis pass (if synthesis succeeded).
    # Parse SUGGESTION: lines from synthesis reply; strip from user-visible text.
    _syn_suggestions: List[str] = []
    if synthesis_succeeded and _syn_text.strip():
        for _sm in _SUGGESTION_RE.finditer(_syn_text):
            _syn_suggestions.append(_sm.group(1).strip())
        # Strip SUGGESTION lines from clean_reply (they are metadata, not user-visible).
        if _syn_suggestions:
            clean_reply = "\n".join(
                line for line in clean_reply.splitlines()
                if not _SUGGESTION_RE.match(line)
            ).strip()
    if suppress_telegram:
        # CHAT6 P6.3 (W3, review-fixed): unified chip flow with the contract
        # priority MAPPING PORTION > SUGGESTION > legacy fill for TOOL turns.
        # The decision keys on the MAPPING PORTION being empty — NOT on the
        # bundled _lane_suggestions result (which mixes mapping chips with
        # legacy ticket fillers and would wrongly suppress SUGGESTION).
        # Non-tool turns: existing _lane_suggestions behavior + context
        # injection (mapping keys on intent/topic only). Non-fatal throughout:
        # any failure inside _lane_suggestions keeps the K4 fallback chain.
        _chip_context = {
            "current_intent": parsed["intent"],
            "topic_service": effective_service or None,
            "last_tool_used": last_tool_used
                or (conv_state.get("last_tool_used") or None),
            "last_findings": (investigation.get("last_findings") or "") or None,
        }
        _was_tool_turn = bool(tool_results)
        if _was_tool_turn:
            from services.offer_planner import _context_chip_pairs

            _mapping_occupied = bool(_context_chip_pairs(_chip_context, locale))
            if _mapping_occupied:
                # Mapping chips (primary slots) + legacy fillers for the
                # remaining slots — one composed result.
                chat_suggestions = chat_suggestions + _lane_suggestions(
                    service=effective_service,
                    last_rca=(investigation.get("last_root_cause") or ""),
                    locale=locale,
                    message=message,
                    history=state.get("conversation_history"),
                    project_id=state.get("project_id"),
                    ticket_ctx=state.get("ticket_context"),
                    context=_chip_context,
                )
            elif _syn_suggestions:
                # P5.5 FALLBACK: mapping portion empty → synthesis chips LEAD;
                # legacy templates fill only the remaining slots (≤3 cap below).
                chat_suggestions = chat_suggestions + _syn_suggestions[:2]
                _legacy_fill = _lane_suggestions(
                    service=effective_service,
                    last_rca=(investigation.get("last_root_cause") or ""),
                    locale=locale,
                    message=message,
                    history=state.get("conversation_history"),
                    project_id=state.get("project_id"),
                    ticket_ctx=state.get("ticket_context"),
                )
                chat_suggestions = list(dict.fromkeys(
                    chat_suggestions + _legacy_fill))
            else:
                # Mapping empty + no synthesis chips → legacy templates only.
                chat_suggestions = chat_suggestions + _lane_suggestions(
                    service=effective_service,
                    last_rca=(investigation.get("last_root_cause") or ""),
                    locale=locale,
                    message=message,
                    history=state.get("conversation_history"),
                    project_id=state.get("project_id"),
                    ticket_ctx=state.get("ticket_context"),
                )
        else:
            chat_suggestions = chat_suggestions + _lane_suggestions(
                service=effective_service,
                last_rca=(investigation.get("last_root_cause") or ""),
                locale=locale,
                message=message,
                history=state.get("conversation_history"),
                project_id=state.get("project_id"),
                ticket_ctx=state.get("ticket_context"),
                context=_chip_context,
            )
        # CHAT6 P6.3 (T6.3.5): chip count never exceeds 3 in any branch.
        chat_suggestions = chat_suggestions[:3]

        if parsed["intent"] == "investigate" and effective_service and session_id:
            # Proactive offer HANYA saat LLM menandai intent investigasi; dedup via
            # has_offer_type (F7: caveat expires_at diketahui & diterima).
            try:
                from services.offer_planner import build_investigate_offer, render_offer_question
                from services.offer_session import create_offer, has_offer_type

                if not await has_offer_type(str(session_id), "investigate"):
                    offer = build_investigate_offer(effective_service, locale=locale)
                    if offer:
                        offer_id = await create_offer(
                            type_=offer["type"], params=offer["params"], question=offer["question"],
                            needs_param=offer["needs_param"], session_id=str(session_id),
                        )
                        if offer_id:
                            clean_reply += f"\n\n{render_offer_question(offer)}"
            except Exception as e:
                logger.warning(f"[ChatAgent] proactive offer gagal (non-fatal): {e}")

    # ── Context pill (web-only; D-P2.8: ticket_id dari ticket_context) ────────
    context_pill: Optional[dict] = None
    if suppress_telegram:
        resolved_ref = _validate_ref_value(parsed.get("resolved_ref"), services)
        context_pill = {
            "type": "anaphora" if resolved_ref else "context",
            "service": effective_service or None,
            "ticket_id": (state.get("ticket_context") or {}).get("ticketNumber"),
            "resolved_ref": resolved_ref,
        }

    # ── Delivery — reuse response_agent helper (contract parity, §5.4) ────────
    # Telegram structurally unreachable (depth gate) tapi jalur tetap konsisten.
    from agents.response_agent import _deliver  # lazy: hindari sirkular impor

    success, send_error = await _deliver(state, clean_reply)

    # P5.1/R3: track which tools were executed this turn (non-LLM, deterministic).
    _executed_tool_names: Optional[List[str]] = None
    if tool_results:
        _executed_tool_names = [r["name"] for r in tool_results if r.get("name") and not r.get("needs_confirmation")]
        if not _executed_tool_names:
            _executed_tool_names = None

    # P5.5 R4: telemetry — track whether synthesis pass composed the final reply.
    # synthesis_used: True (success) | False (attempted, fallback) | None (not attempted).
    _synthesis_used = synthesis_succeeded if synthesis_attempted else None

    result: Dict[str, Any] = {
        "formatted_message": clean_reply,
        "telegram_sent": success,
        "telegram_error": send_error,
        "next_agent": "end",
        "agents_visited": agents_visited,
        **({"chat_suggestions": chat_suggestions} if chat_suggestions else {}),
        **({"context_pill": context_pill} if suppress_telegram and context_pill else {}),
        **({"tools_used": _executed_tool_names} if _executed_tool_names else {}),
        **({"synthesis_used": _synthesis_used} if _synthesis_used is not None else {}),
    }
    return result
