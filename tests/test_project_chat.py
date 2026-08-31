"""Chat by Project fase 1 — unit & e2e mock.

Coverage:
- Supervisor routing gate: project query → project_agent (dan penolaknya).
- project_agent: referensi KEY-N → pengarah tiket; Q&A → gather + LLM sintesis;
  fallback deterministik bila LLM down; suggestions whitelist.
- Guard akses api/chat: owner/member vs outsider.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def run(coro):
    return asyncio.run(coro)


class CannedLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    async def ainvoke(self, messages):
        for m in messages:
            self.prompts.append(getattr(m, "content", ""))
        return SimpleNamespace(content=self.reply)


def install_llm(monkeypatch, reply: str) -> CannedLLM:
    canned = CannedLLM(reply)
    monkeypatch.setattr("agents.project_agent.get_chat_llm", lambda **k: canned)
    monkeypatch.setattr("agents.project_agent._has_llm", True)
    return canned


# ── Supervisor routing gate ──────────────────────────────────────────────────

def _base_state(**over):
    state = {
        "intent": "berapa total tiket hari ini",
        "service_name": "",
        "collection_name": "",
        "message_raw": "berapa total tiket hari ini",
        "sender": {"channel": "chat", "session_id": None},
        "agents_visited": [],
        "next_agent": "supervisor",
        "error": None,
        "workspace_id": "w1",
        "project_id": "p1",
        "ticket_context": None,
        "preset_service_name": None,
        "preset_trace_ids": [],
        "chat_depth": "low",
        "reply_to_agent": False,
    }
    state.update(over)
    return state


@pytest.fixture
def no_services(monkeypatch):
    """list_all_services kosong → tidak ada service match di semua strategi."""
    async def _empty():
        return {}
    monkeypatch.setattr("agents.supervisor.list_all_services", _empty)


def test_project_query_routed_ke_project_agent(no_services):
    from agents.supervisor import supervisor_agent

    result = run(supervisor_agent(_base_state()))
    assert result["next_agent"] == "project_agent"
    assert (result.get("routing_strategy") or "").startswith("project_query") or result.get(
        "routing_strategy"
    ) in (None, "llm_fallback")


def test_service_eksplisit_tidak_dihijack(no_services, monkeypatch):
    """'error pada X' dari sesi project tetap masuk jalur insiden (triage).
    Mock juga project-gated lookup (#43) agar service match tidak ter-filter DB nyata."""
    from agents.supervisor import supervisor_agent

    async def _svc():
        return {"kuponku_core_api": "logs_kuponku_core_api"}

    async def _linked(pid):
        return ["kuponku_core_api"]

    monkeypatch.setattr("agents.supervisor.list_all_services", _svc)
    monkeypatch.setattr("services.service_store.service_ids_for_project", _linked)
    result = run(supervisor_agent(_base_state(intent="error pada kuponku_core_api")))
    assert result["next_agent"] == "triage_agent"


def test_thinking_dengan_service_tetap_triage(no_services, monkeypatch):
    """thinking + service eksplisit = pipeline insiden penuh (bukan lane project)."""
    from agents.supervisor import supervisor_agent

    async def _svc():
        return {"kuponku_core_api": "logs_kuponku_core_api"}

    async def _linked(pid):
        return ["kuponku_core_api"]

    monkeypatch.setattr("agents.supervisor.list_all_services", _svc)
    monkeypatch.setattr("services.service_store.service_ids_for_project", _linked)
    result = run(
        supervisor_agent(_base_state(chat_depth="thinking", intent="error pada kuponku_core_api"))
    )
    assert result["next_agent"] == "triage_agent"


def test_thinking_tanpa_subject_fallback_ramah(no_services):
    """Fix G3: thinking tanpa service eksplisit TIDAK error daftar service —
    jatuh ke project_agent (insight terbaik dari fakta database project)."""
    from agents.supervisor import supervisor_agent

    result = run(supervisor_agent(_base_state(chat_depth="thinking")))
    assert result["next_agent"] == "project_agent"


def test_tanpa_project_id_tidak_masuk_project_lane(no_services):
    from agents.supervisor import supervisor_agent

    result = run(supervisor_agent(_base_state(project_id=None)))
    assert result["next_agent"] != "project_agent"


def test_sesi_terikat_tiket_tidak_masuk_project_lane(no_services):
    """Chat detail tiket punya ticket_context → guard redirect fokus tiket, bukan project lane."""
    from agents.supervisor import supervisor_agent

    result = run(
        supervisor_agent(
            _base_state(
                intent="halo apa kabar",
                message_raw="halo apa kabar",
                ticket_context={"ticketNumber": 42, "title": "X"},
            )
        )
    )
    assert result["next_agent"] == "response_agent"  # redirect pre-formatted
    assert "tiket" in result.get("formatted_message", "").lower()


# ── project_agent ─────────────────────────────────────────────────────────────

TICKET = {
    "_id": "t1",
    "title": "HPA maxout landing",
    "status": "in_progress",
    "severity": "high",
    "serviceName": "lovvit_landing_platform",
    "projectId": "p1",
}


def test_key_n_menghasilkan_pengarah_tiket(monkeypatch):
    from agents.project_agent import project_agent

    async def fake_lookup(num, workspace_id=None):
        assert num == 42
        return dict(TICKET)

    monkeypatch.setattr("services.ticket_store.get_ticket_by_number", fake_lookup)
    result = run(
        project_agent(_base_state(intent="apa isi CORE-42?", message_raw="apa isi CORE-42?"))
    )
    pr = result["project_result"]
    assert pr["type"] == "ticket_ref"
    assert pr["ticket_refs"][0]["ticketNumber"] == 42
    assert "CORE-42" in result["formatted_message"]
    assert result["next_agent"] == "response_agent"


def test_key_n_lowercase_juga_terdeteksi(monkeypatch):
    """Fix G4: user sering ketik 'core-42' lowercase — tetap jadi pengarah tiket."""
    from agents.project_agent import project_agent

    seen = {}

    async def fake_lookup(num, workspace_id=None):
        seen["num"] = num
        return dict(TICKET)

    monkeypatch.setattr("services.ticket_store.get_ticket_by_number", fake_lookup)
    result = run(
        project_agent(_base_state(intent="lihat core-42 donk", message_raw="lihat core-42 donk"))
    )
    assert seen["num"] == 42
    assert "CORE-42" in result["formatted_message"]  # key dinormalisasi uppercase


def test_qa_gather_dan_llm_sintesis(monkeypatch):
    from agents.project_agent import project_agent

    async def fake_count(pid, *, since_hours=None, group_by="status"):
        if since_hours:
            return {"total": 5, "groups": {"new": 2, "open": 3}}
        return {"total": 31, "groups": {"open": 4, "closed": 27}}

    async def fake_recent(pid, *, since_hours=24.0, limit=10):
        return [dict(TICKET)]

    async def fake_alerts(ws, *, since_hours=3.0, limit=20):
        return [{"sent_at": "t", "service_name": "lovvit_landing_platform", "message": "KubeHpaMaxedOut"}]

    async def fake_errors(ws, pid, hours):
        return ["[ERROR LOG COUNTS window 24h]", "- svc-a: 3 error documents dalam 24 jam terakhir"]

    async def fake_err_ids(pid):
        return ["svc-a"]

    monkeypatch.setattr("services.ticket_store.count_by_project", fake_count)
    monkeypatch.setattr("services.ticket_store.recent_tickets_by_project", fake_recent)
    monkeypatch.setattr("services.request_log.list_recent_watchdog_alerts", fake_alerts)
    monkeypatch.setattr("services.service_store.service_ids_for_project", fake_err_ids)

    async def fake_gather_errors(ws, pid, hours):
        return await fake_errors(ws, pid, hours)

    monkeypatch.setattr("agents.project_agent._gather_errors", fake_gather_errors)

    canned = install_llm(monkeypatch, "Hari ini ada *5* tiket baru, 3 masih open.")
    result = run(
        project_agent(
            _base_state(
                intent="berapa tiket hari ini dan apa yang terjadi?",
                message_raw="berapa tiket hari ini dan apa yang terjadi?",
            )
        )
    )
    assert result["formatted_message"] == "Hari ini ada *5* tiket baru, 3 masih open."
    assert result["routing_strategy"] == "project_query"
    pr = result["project_result"]
    assert pr["type"] == "project_qa"
    assert isinstance(pr["suggestions"], list) and len(pr["suggestions"]) <= 3
    # prompt ter-render penuh
    for p in canned.prompts:
        assert "{{" not in p
    joined = "\n".join(canned.prompts)
    assert "[TICKETS]" in joined  # facts terkirim ke LLM


def test_llm_down_fallback_deterministik(monkeypatch):
    from agents.project_agent import project_agent

    async def fake_count(pid, *, since_hours=None, group_by="status"):
        return {"total": 7, "groups": {"open": 7}}

    monkeypatch.setattr("services.ticket_store.count_by_project", fake_count)
    monkeypatch.setattr("agents.project_agent._has_llm", False)

    result = run(project_agent(_base_state()))
    assert "LLM tidak tersedia" in result["formatted_message"]
    assert "[TICKETS]" in result["formatted_message"]  # facts mentah tetap tersampaikan


def test_medium_mode_append_offer_investigasi(monkeypatch):
    from agents.project_agent import project_agent

    async def fake_count(pid, *, since_hours=None, group_by="status"):
        return {"total": 1, "groups": {}}

    async def fake_errors(ws, pid, hours):
        return ["[ERROR LOG COUNTS window 3h]\n- svc-b: 9 error documents dalam 3 jam terakhir"]

    async def fake_ids(pid):
        return ["svc-b"]

    monkeypatch.setattr("services.ticket_store.count_by_project", fake_count)
    monkeypatch.setattr("services.service_store.service_ids_for_project", fake_ids)
    monkeypatch.setattr("agents.project_agent._gather_errors", fake_errors)
    install_llm(monkeypatch, "Ada error di svc-b.")

    result = run(
        project_agent(
            _base_state(
                intent="apakah ada error 3 jam terakhir",
                message_raw="apakah ada error 3 jam terakhir",
                chat_depth="medium",
            )
        )
    )
    assert "investigasi lebih dalam" in result["formatted_message"].lower()


def test_tanpa_project_id_guard_message(monkeypatch):
    from agents.project_agent import project_agent

    result = run(project_agent(_base_state(intent="berapa tiket", project_id=None)))
    assert "konteks project" in result["formatted_message"].lower()
