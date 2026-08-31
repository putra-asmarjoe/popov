"""E2E gate untuk refactor prompt ke file-driven.

Menjamin tiap agent yang direfaktor tetap menghasilkan output yang benar setelah
prompt dipindah ke prompts/*.md: template ter-render penuh (tanpa {{var}} tersisa),
LLM di-mock (canned), dan perilaku inti tidak berubah.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import services.llm_factory as lf


class CannedLLM:
    """LLM tiruan: simpan semua prompt yang dikirim + balas canned reply."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    async def ainvoke(self, messages):
        for m in messages:
            self.prompts.append(getattr(m, "content", ""))
        return SimpleNamespace(content=self.reply)


def install_llm(monkeypatch, reply: str) -> CannedLLM:
    canned = CannedLLM(reply)
    # Patch modul sumber (dipakai modul yang import LAZY di dalam fungsi) ...
    monkeypatch.setattr(lf, "get_chat_llm", lambda **k: canned)
    # ... DAN modul yang bind get_chat_llm di top-level (referensi terikat).
    import importlib
    for mod_name in (
        "agents.correlation_agent", "agents.response_agent", "agents.supervisor",
        "agents.ticket_agent", "services.pattern_miner_service", "services.llm_config_store",
        "services.ticket_intent", "services.conversation",
    ):
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "get_chat_llm"):
                monkeypatch.setattr(mod, "get_chat_llm", lambda **k: canned)
        except Exception:
            pass
    return canned


def run(coro):
    return asyncio.run(coro)


def assert_no_unresolved(prompts: list[str]):
    for p in prompts:
        assert "{{" not in p, f"placeholder tak ter-render: {p[:200]}"


# ── Helpers async (dipanggil via await) ───────────────────────────────────────

async def _fake_user(uid):
    return {"_id": uid, "name": "Budi", "email": "budi@x.com"}


async def _fake_project(pid):
    return {"_id": pid, "key": "CORE", "workspaceId": "w1"}


async def _fake_ws(wid):
    return {"_id": wid, "members": [{"userId": "u1"}]}


def _fake_membership(ws, uid):
    return {"userId": uid}


def _fake_get_ticket(ticket):
    async def _gt(tid):
        return dict(ticket)
    return _gt


def _ticket_fixture():
    return {"_id": "t1", "ticketNumber": 21, "projectId": "p1", "status": "open", "severity": "high",
            "tags": [], "assignees": [], "createdBy": "u1", "title": "x", "description": "y", "progressLog": []}


def _patch_ticket_stores(monkeypatch, ticket):
    import agents.ticket_agent as ta
    monkeypatch.setattr(ta, "get_user", _fake_user)
    monkeypatch.setattr(ta, "find_project_by_id", _fake_project)
    monkeypatch.setattr(ta, "find_workspace_by_id", _fake_ws)
    monkeypatch.setattr(ta, "get_membership", _fake_membership)
    monkeypatch.setattr(ta, "get_ticket", _fake_get_ticket(ticket))


# ── Ticket Agent: aksi close (parse LLM canned) + offer ───────────────────────

def test_ticket_agent_close_action(monkeypatch):
    import agents.ticket_agent as ta
    ticket = _ticket_fixture()
    _patch_ticket_stores(monkeypatch, ticket)

    async def _parse(intent, pub, members):
        return {"action": "close", "params": {}}

    async def _change_status(ticket, target, user, *, via=None):
        ticket["status"] = target
        return ticket, None

    async def _create_offer(**kw):
        return "of1"

    monkeypatch.setattr(ta, "parse_ticket_intent", _parse)
    monkeypatch.setattr(ta, "change_status", _change_status)
    monkeypatch.setattr(ta, "create_offer", _create_offer)

    state = {"intent": "tutup tiket ini", "sender": {"channel": "chat", "user_id": "u1", "session_id": "s1"},
             "ticket_context": {"ticket_id": "t1"}, "agents_visited": []}
    res = run(ta.ticket_agent(state))
    assert res["ticket_result"]["ok"] is True
    assert res["ticket_result"]["action"] == "close"
    assert "CORE-21" in res["formatted_message"]


# ── Ticket Agent: pertanyaan → summary via LLM (prompt rendered) ──────────────

def test_ticket_agent_question_summary(monkeypatch):
    import agents.ticket_agent as ta
    canned = install_llm(monkeypatch, "Tiket *CORE-21* dalam status open.")
    _patch_ticket_stores(monkeypatch, _ticket_fixture())

    res = run(ta.ticket_agent({"intent": "apa yang terjadi pada tiket ini",
                               "sender": {"channel": "chat", "user_id": "u1", "session_id": "s1"},
                               "ticket_context": {"ticket_id": "t1"},
                               "conversation_history": [{"role": "user", "content": "tadi"}],
                               "agents_visited": []}))
    assert res["ticket_result"]["action"] == "summary"
    assert res["ticket_result"]["ok"] is True
    assert "CORE-21" in res["formatted_message"]
    assert_no_unresolved(canned.prompts)


# ── Ticket Intent parse (LLM canned) ──────────────────────────────────────────

def test_ticket_intent_parse(monkeypatch):
    from services.ticket_intent import parse_ticket_intent
    canned = install_llm(monkeypatch, '{"action": "set_severity", "params": {"severity": "low"}}')
    ticket = {"ticketNumber": 21, "status": "open", "severity": "high", "tags": [], "assigneesDetail": []}
    res = run(parse_ticket_intent("set tiket ke low", ticket, [{"userId": "u1", "name": "Budi", "email": "b@x.com"}]))
    assert res == {"action": "set_severity", "params": {"severity": "low"}}
    assert_no_unresolved(canned.prompts)


# ── Correlation Agent (LLM canned, prompt rendered) ───────────────────────────

def test_correlation_agent(monkeypatch):
    import agents.correlation_agent as ca
    canned = install_llm(
        monkeypatch,
        "ROOT_CAUSE_ASSESSMENT: service-fault\nSEVERITY: WARNING\nANALYSIS SUMMARY: x\nRECOMMENDED ACTIONS: y",
    )
    monkeypatch.setattr("services.doc_loader.build_agent_context", _fake_async("doc-context"))
    monkeypatch.setattr("services.second_brain.read_similar_episodes", _fake_async(None))
    monkeypatch.setattr("services.second_brain.generate_episode_id", lambda svc: "EP-TEST-0001")
    monkeypatch.setattr("services.second_brain.write_episode_bg", _fake_async(None))

    state = {"service_name": "svc_core_api", "intent": "error", "mongo_summary": "1 error",
             "metrics_summary": "", "trace_summary": "", "span_summary": "", "span_available": False,
             "health_result": None, "knowledge_context": "", "workspace_id": None,
             "conversation_history": [{"role": "user", "content": "kenapa 5xx?"}], "agents_visited": []}
    res = run(ca.correlation_agent(state))
    assert res["root_cause_assessment"] == "service-fault"
    assert res["episode_id"] == "EP-TEST-0001"
    assert_no_unresolved(canned.prompts)


# ── Conversation clarify (guard) ──────────────────────────────────────────────

def test_clarify_guard(monkeypatch):
    from services.conversation import clarify_reply
    canned = install_llm(monkeypatch, '{"route": null, "question": "Mari fokus ke *CORE-21*."}')
    res = run(clarify_reply("apa kabar?", context_text="Tiket CORE-21", mode="guard"))
    assert res["route"] is None
    assert "CORE-21" in res["question"]
    assert_no_unresolved(canned.prompts)


# ── Supervisor Strategy 5 (LLM canned) ────────────────────────────────────────

def test_supervisor_strategy5(monkeypatch):
    import agents.supervisor as sup
    canned = install_llm(
        monkeypatch,
        '{"service_name": "svc_core_api", "intent_type": "incident", "confidence": 0.7}',
    )
    monkeypatch.setattr(sup, "list_all_services", _fake_async({"svc_core_api": "logs_x"}))
    monkeypatch.setattr(sup, "get_active_offer", _fake_async(None))

    res = run(sup.supervisor_agent({"intent": "masalah berat di sistem tadi malam",
                                    "sender": {"channel": "chat", "user_id": "u1", "session_id": "s1"},
                                    "agents_visited": []}))
    assert res["next_agent"] == "triage_agent"
    assert res["service_name"] == "svc_core_api"
    assert res["routing_strategy"] == "llm_fallback"
    assert_no_unresolved(canned.prompts)


# ── Pattern Miner narrative (LLM canned) ──────────────────────────────────────

def test_pattern_miner_narrative(monkeypatch):
    from services.pattern_miner_service import generate_narrative_with_llm
    canned = install_llm(monkeypatch, "## Learned Patterns\n- Pattern A")
    patterns = [{"cluster_id": 0, "label": "HPA Maxout", "episode_count": 3, "probable_cause": "hpa_maxout",
                 "probable_cause_pct": 1.0, "distinguishing_symptoms": ["x"], "misleading_signals": [],
                 "avg_resolution_min": None, "feedback_quality": {"correct": 1, "auto_resolved": 0, "pending": 2},
                 "episode_ids": ["e1"]}]
    text = run(generate_narrative_with_llm("svc_core_api", patterns, 0, 3))
    assert "## Learned Patterns" in text
    assert_no_unresolved(canned.prompts)


# ── Telegram incident formatter (prompt rendered) ─────────────────────────────

def test_telegram_incident_format(monkeypatch):
    from agents.response_agent import _format_with_llm
    canned = install_llm(monkeypatch, "*[WARNING]* Service bermasalah.")
    text = run(_format_with_llm("error pada x", "svc_core_api", [{"message": "err", "ts": "t"}],
                                "doc-context", history=[{"role": "user", "content": "tadi"}]))
    assert text == "*[WARNING]* Service bermasalah."
    assert_no_unresolved(canned.prompts)


# ── Supervisor: knowledge query → inventory (bukan lane insiden) ───────────────

def test_supervisor_knowledge_query(monkeypatch):
    import agents.supervisor as sup
    monkeypatch.setattr(sup, "list_all_services", _fake_async({"svc_core_api": "logs_svc_core_api"}))
    monkeypatch.setattr(sup, "get_active_offer", _fake_async(None))

    async def _inv(svc, workspace_id=None, project_id=None, detail=False):
        return f"📚 Knowledge & Dokumen Service `{svc}`"

    monkeypatch.setattr("services.knowledge_listing.build_service_knowledge_inventory", _inv)

    res = run(sup.supervisor_agent({
        "intent": "dokumen atau knowledge apa saja yang ada pada service svc-core-api",
        "sender": {"channel": "chat", "user_id": "u1", "session_id": "s1"},
        "ticket_context": {"ticket_id": "t1", "ticketNumber": 10, "title": "T"},
        "agents_visited": [],
    }))
    assert res["next_agent"] == "response_agent"
    assert res["service_name"] == "svc_core_api"
    assert "Knowledge" in res["formatted_message"]


def _fake_async(value):
    async def _f(*args, **kwargs):
        return value
    return _f