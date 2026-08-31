"""Dedup window auto-ticket (1 tiket : N alert).

Menjamin: alert pertama → tiket baru + alert ter-link; alert berikutnya dalam
window dedup → TIDAK buat tiket baru, hanya dokumen alert ter-link; tiket
resolved/closed dan window lewat → tiket baru lagi.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import services.auto_ticket as at
from config.settings import settings
from services.ticket_store import OPEN_STATUSES, _linkable_query


def run(coro):
    return asyncio.run(coro)


# ── Fakes ─────────────────────────────────────────────────────────────────────

PROJECT = {"_id": "p1", "name": "Demo", "workspaceId": "w1", "key": "CORE"}
ALERTS = [
    {"name": "HighErrorRate", "severity": "critical", "trace_id": "abc123"},
    {"name": "HighErrorRate", "severity": "warning", "trace_id": None},
]


@pytest.fixture
def capture(monkeypatch):
    """Patch dependensi maybe_create_watchdog_ticket + rekam semua call."""
    calls = {"create": [], "record": [], "lookup": []}

    async def fake_resolve(**kwargs):
        return [dict(PROJECT)]

    async def fake_find_linkable(pid, content_fp, hours):
        calls["lookup"].append((pid, content_fp, hours))
        return calls.get("linkable_ticket")

    async def fake_create_ticket(project, user, **kw):
        ticket = {
            "_id": f"t{len(calls['create']) + 1}",
            "ticketNumber": len(calls['create']) + 1,
            "projectId": str(project["_id"]),
            "workspaceId": project.get("workspaceId", ""),
            "title": kw["title"],
            "status": "new",
            "alertsCount": 0,
        }
        calls["create"].append(kw)
        return ticket

    async def fake_record(ticket, **kw):
        calls["record"].append({"ticketId": str(ticket["_id"]), **kw})
        return {"alertId": "alt-x", "ticketId": str(ticket["_id"]), **kw}

    monkeypatch.setattr("services.incident_router.resolve_projects_for_incident", fake_resolve)
    monkeypatch.setattr(at, "find_linkable_ticket_by_fingerprint", fake_find_linkable)
    monkeypatch.setattr(at, "create_ticket", fake_create_ticket)
    monkeypatch.setattr(at, "record_ticket_alert", fake_record)
    calls["set_linkable"] = lambda t: calls.__setitem__("linkable_ticket", t)
    return calls


# ── Skenario inti ─────────────────────────────────────────────────────────────

def test_alert_pertama_buat_tiket_new_plus_alert(capture):
    tickets, refs = run(at.maybe_create_watchdog_ticket("svc", ALERTS, "aid-1", workspace_id="w1"))
    assert len(tickets) == 1
    assert refs["new"] == ["CORE-1"] and refs["linked"] == []
    assert len(capture["create"]) == 1
    kw = capture["create"][0]
    assert kw["source"] == "watchdog"
    assert kw["content_fp"]  # contentFp tersimpan utk dedup window
    assert kw["fingerprint"].endswith(kw["content_fp"]) or ":p1:" in kw["fingerprint"]
    # alert pertama ter-link ke tiket baru, TANPA progress note (initial_note cukup)
    rec = capture["record"][0]
    assert rec["ticketId"] == "t1"
    assert rec.get("note") is None   # initial_note tiket cukup utk alert pertama
    assert rec["trace_ids"] == ["abc123"]


def test_alert_kedua_link_ke_tiket_aktif_tanpa_tiket_baru(capture):
    capture["set_linkable"](
        {"_id": "t9", "ticketNumber": 7, "projectId": "p1", "alertsCount": 2}
    )
    tickets, refs = run(at.maybe_create_watchdog_ticket("svc", ALERTS, "aid-2", workspace_id="w1"))
    assert tickets == []                      # tidak ada tiket baru
    assert refs == {"new": [], "linked": ["CORE-7"]}   # label tiket ter-link utk broadcast
    assert capture["create"] == []
    rec = capture["record"][0]
    assert rec["ticketId"] == "t9"            # alert ke tiket lama
    # Linked alert HANYA di ticket_alerts (Linked Alerts), TIDAK ada progress note
    assert rec.get("note") is None


def test_window_dari_env_dipakai(capture):
    run(at.maybe_create_watchdog_ticket("svc", ALERTS, "aid-3", workspace_id="w1"))
    pid, fp, hours = capture["lookup"][0]
    assert pid == "p1"
    assert hours == settings.ticket_alert_dedup_hours  # default 12


def test_multi_project_tetap_satu_tiket_per_project(capture, monkeypatch):
    async def fake_resolve(**kwargs):
        return [dict(PROJECT), {**PROJECT, "_id": "p2", "name": "Lain"}]

    # resolve dipanggil lazy (`from ... import` di dalam fungsi) → patch titik sumber
    monkeypatch.setattr(
        "services.incident_router.resolve_projects_for_incident", fake_resolve
    )

    tickets, refs = run(at.maybe_create_watchdog_ticket("svc", ALERTS, "aid-4", workspace_id="w1"))
    assert len(tickets) == 2
    assert refs["new"] == ["CORE-1", "CORE-2"]
    assert {r["ticketId"] for r in capture["record"]} == {"t1", "t2"}


# ── Query dedup (pure) ────────────────────────────────────────────────────────

def test_linkable_query_status_aktif_saja():
    q = _linkable_query("p1", "fp", 12)
    assert q["status"]["$in"] == list(OPEN_STATUSES)
    assert "resolved" not in q["status"]["$in"]
    assert "closed" not in q["status"]["$in"]
    assert q["projectId"] == "p1"
    assert q["contentFp"] == "fp"


def test_linkable_query_cutoff_window():
    before = datetime.now(timezone.utc)
    q = _linkable_query("p1", "fp", 12)
    cutoff = datetime.fromisoformat(q["createdAt"]["$gte"])
    expected_lo = before - timedelta(hours=12, seconds=5)
    expected_hi = before - timedelta(hours=12) + timedelta(seconds=5)
    assert expected_lo <= cutoff <= expected_hi


def test_linkable_query_window_nol_tanpa_filter_waktu():
    q = _linkable_query("p1", "fp", 0)
    assert "createdAt" not in q
