"""Test renderer prompt — file-driven (prompts/*.md) + fallback DEFAULT_PROMPTS.

Menjamin: setiap template ter-render penuh (tanpa placeholder tersisa), dan bila
file hilang maka fallback default tetap menghasilkan prompt yang valid.
"""
from __future__ import annotations

import pytest

import services.prompt_loader as pl

RENDER_VARS = {
    "correlation_system": {},
    "correlation_user": dict(historical_block="", doc_context="", knowledge_section="",
                             conversation_section="", ticket_section="", mongo_summary="",
                             metrics_summary="", trace_summary="", span_section="", health_section="",
                             reply_language="English"),
    "telegram_incident_system": {},
    "telegram_incident_user": dict(sample_block="", correlation_block="", incident_history_block="", history_block="", reply_language="English"),
    "telegram_span_system": {},
    "telegram_span_user": dict(intent="", trace_id="", span_summary="", extra_block="", history_block=""),
    "telegram_data_system": {},
    "telegram_data_user": dict(intent="", service_name="", records_block=""),
    "telegram_followup_system": {},
    "telegram_followup_user": dict(intent="", followup_block=""),
    "telegram_health_system": {},
    "telegram_health_user": dict(intent="", health_json=""),
    "supervisor_classify": dict(service_list="- x", intent="cek"),
    "ticket_parse": dict(ticket_number="21", ticket_status="open", ticket_severity="high",
                         ticket_tags="[]", ticket_assignees="-", member_list="-", intent="close"),
    "ticket_summary": dict(ticket_json="{}", history="-", intent="apa?", reply_language="English"),
    "ticket_clarify": dict(context="-", history="-", options="-", rule="-", intent="apa?"),
    "pattern_miner_narrative": dict(service="x", total="3", cluster_json="[]", unclassified="0"),
}


def test_all_prompts_render_without_leftover_placeholders():
    for name in pl.list_prompts():
        vars_ = RENDER_VARS[name]
        rendered = pl.render(name, **vars_)
        assert rendered.strip(), f"{name} kosong"
        assert "{{" not in rendered, f"{name} masih ada placeholder belum ter-render: {rendered[:200]}"


def test_english_reply_language_instruction_present():
    """Prompt yang menghasilkan balasan natural wajib menginstruksikan reply ikut bahasa user."""
    natural = [
        "correlation_system", "correlation_user",
        "telegram_incident_system", "telegram_span_system",
        "telegram_data_system", "telegram_followup_system", "telegram_health_system",
        "ticket_summary", "ticket_clarify", "pattern_miner_narrative",
    ]
    for name in natural:
        rendered = pl.render(name, **RENDER_VARS[name])
        assert "language" in rendered.lower(), f"{name} tidak memuat instruksi reply-language"


def test_fallback_defaults_when_file_missing(monkeypatch, tmp_path):
    """Bila folder prompts hilang → DEFAULT_PROMPTS tetap menghasilkan prompt valid."""
    monkeypatch.setattr(pl, "PROMPTS_ROOT", tmp_path)  # folder kosong
    pl.reload_prompts()
    rendered = pl.render("correlation_system")
    assert "Root Cause Analysis" in rendered


def test_hot_reload_reflects_file_change(monkeypatch, tmp_path):
    """Edit file .md → reload_prompts() → template baru terpakai."""
    target = tmp_path / "ticket_parse.md"
    target.write_text("EDITED PROMPT {{intent}}", encoding="utf-8")
    monkeypatch.setattr(pl, "PROMPTS_ROOT", tmp_path)
    pl.reload_prompts()
    rendered = pl.render("ticket_parse", intent="x")
    assert rendered == "EDITED PROMPT x"


def test_unknown_prompt_raises_keyerror():
    with pytest.raises(KeyError):
        pl.render("tidak_ada")