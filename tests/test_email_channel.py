"""
Test channel notifikasi email (SMTP) — Fix email channel.

Cover: _strip_secrets email, encrypt/decrypt secret, extract_email_creds,
verify_smtp (mock), send_email (mock), _require_email_creds, retry,
broadcast_email mixed channels, outgoing dedup, parse address list.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.email_client import (
    _format_addr,
    _require_email_creds,
    broadcast_email,
    send_email,
)
from services.notification_store import (
    _strip_secrets,
    extract_email_creds,
    verify_smtp,
)
from services.secret_crypto import decrypt_secret, encrypt_secret, reencrypt_if_needed


def _email_doc(**overrides):
    cfg = {
        "smtp_host": "smtp.test:1025",
        "smtp_port": 1025,
        "security": "none",
        "smtp_user": "user",
        "smtp_pass": "f:encrypted",
        "from_addr": '"Popov" <alert@popov.test>',
        "to_addrs": ["ops@popov.test"],
        "cc_addrs": ["cc@popov.test"],
        "bcc_addrs": ["bcc@popov.test"],
    }
    cfg.update({k: v for k, v in overrides.items() if k in cfg})
    doc = {
        "notif_id": "ntf-abc",
        "name": "Ops Email",
        "channel": "email",
        "workspace_id": "ws-1",
        "project_ids": [],
        "config": {"email": cfg},
    }
    if "notif_id" in overrides:
        doc["notif_id"] = overrides["notif_id"]
    return doc


# ── _strip_secrets / extract ──────────────────────────────────────────────────

def test_strip_secrets_email():
    doc = _email_doc()
    out = _strip_secrets(doc)
    cfg = out["config"]["email"]
    assert "smtp_pass" not in cfg
    # token "f:encrypted" (11 chars) → mask 4 char terakhir "***pted"
    assert cfg.get("smtp_pass_masked") == "***pted"
    assert cfg["smtp_host"] == "smtp.test:1025"


def test_strip_secrets_telegram_masih_berfungsi():
    doc = {
        "notif_id": "ntf-1", "name": "Tg", "channel": "telegram",
        "config": {"telegram": {"bot_token": "123456:ABCDEF", "chat_id": "123"}},
    }
    out = _strip_secrets(doc)
    tg = out["config"]["telegram"]
    assert "bot_token" not in tg
    assert tg["bot_token_masked"] == "***CDEF"
    assert tg["chat_id"] == "123"


def test_extract_email_creds():
    with patch("services.secret_crypto.decrypt_secret", return_value="plainpass"):
        cfg = extract_email_creds(_email_doc())
    assert cfg["host"] == "smtp.test:1025"
    assert cfg["port"] == 1025
    assert cfg["password"] == "plainpass"
    assert cfg["to"] == ["ops@popov.test"]
    assert cfg["cc"] == ["cc@popov.test"]
    assert cfg["bcc"] == ["bcc@popov.test"]
    assert extract_email_creds({"channel": "telegram"}) is None


def test_extract_email_creds_comma_string():
    doc = _email_doc(to_addrs="a@x.com, b@x.com")
    cfg = extract_email_creds(doc)
    assert cfg["to"] == ["a@x.com", "b@x.com"]


# ── Enkripsi ──────────────────────────────────────────────────────────────────

def test_encrypt_decrypt_secret():
    enc = encrypt_secret("secret123")
    assert enc.startswith("f:")
    assert decrypt_secret(enc) == "secret123"


def test_decrypt_legacy_plaintext():
    # tanpa prefix f: → return as-is (lazy migrate on read)
    assert decrypt_secret("plain-old-token") == "plain-old-token"


def test_reencrypt_if_needed():
    enc = encrypt_secret("x")
    assert reencrypt_if_needed(enc) == enc  # sudah terenkripsi — tidak double
    assert reencrypt_if_needed("plain") is not None
    assert decrypt_secret(reencrypt_if_needed("plain")) == "plain"


# ── verify_smtp (mock aiosmtplib) ─────────────────────────────────────────────

def test_verify_smtp_ok():
    fake_ehlo = type("E", (), {"message": b"250 smtp.test"})()
    with patch("aiosmtplib.SMTP") as MockSMTP:
        inst = MockSMTP.return_value
        inst.connect = AsyncMock()
        inst.ehlo = AsyncMock(return_value=fake_ehlo)
        inst.quit = AsyncMock()
        result = asyncio.run(verify_smtp("smtp.test", 587, "starttls"))
    assert result["ok"] is True
    assert "250" in result["banner"]


def test_verify_smtp_auth_fail():
    with patch("aiosmtplib.SMTP") as MockSMTP:
        inst = MockSMTP.return_value
        inst.connect = AsyncMock()
        inst.ehlo = AsyncMock(return_value=type("E", (), {"message": b"250 ok"})())
        inst.login = AsyncMock(side_effect=Exception("535 auth failed"))
        result = asyncio.run(verify_smtp("smtp.test", 587, "starttls", "u", "p"))
    assert result["ok"] is False
    assert "535" in result["error"]


# ── _require_email_creds ──────────────────────────────────────────────────────

def test_require_email_creds_missing_host():
    with pytest.raises(ValueError):
        _require_email_creds({"port": 587, "from_addr": "a@b.c", "to": ["x@y.z"]})


def test_require_email_creds_missing_to():
    with pytest.raises(ValueError):
        _require_email_creds({"host": "h", "from_addr": "a@b.c", "to": []})


# ── send_email (mock) ─────────────────────────────────────────────────────────

@patch("services.email_client.aiosmtplib.SMTP")
def test_send_email_happy(MockSMTP):
    inst = MockSMTP.return_value
    inst.connect = AsyncMock()
    inst.ehlo = AsyncMock()
    inst.send_message = AsyncMock()
    inst.quit = AsyncMock()
    cfg = {
        "host": "smtp.test", "port": 1025, "security": "none",
        "user": None, "password": None,
        "from_addr": '"Popov" <alert@popov.test>',
        "to": ["ops@popov.test"], "cc": ["cc@popov.test"], "bcc": ["bcc@popov.test"],
    }
    result = asyncio.run(send_email(cfg, "Subj", "body"))
    assert result["ok"] is True
    inst.send_message.assert_awaited_once()
    msg = inst.send_message.await_args.args[0]
    assert "Popov" in msg["From"]
    assert "ops@popov.test" in msg["To"]
    assert "cc@popov.test" in msg["Cc"]
    assert "bcc@popov.test" in msg["Bcc"]
    assert msg["Subject"] == "Subj"


@patch("services.email_client.aiosmtplib.SMTP")
def test_send_email_retry_then_fail(MockSMTP):
    inst = MockSMTP.return_value
    inst.connect = AsyncMock()
    inst.ehlo = AsyncMock()
    inst.send_message = AsyncMock(side_effect=Exception("Connection refused"))
    inst.quit = AsyncMock()
    cfg = {
        "host": "h", "port": 587, "security": "starttls",
        "user": None, "password": None, "from_addr": "a@b.c",
        "to": ["x@y.z"], "cc": [], "bcc": [],
    }
    result = asyncio.run(send_email(cfg, "S", "b"))
    assert result["ok"] is False
    # retry 1x → total 2 attempt (guard _now mencegah loop tak hingga)
    assert inst.send_message.await_count == 2


# ── broadcast_email mixed channels ────────────────────────────────────────────

@patch("services.email_client.send_email", new=AsyncMock(return_value={"ok": True, "detail": "250 OK"}))
def test_broadcast_email_ignores_telegram():
    channels = [
        {"notif_id": "ntf-tg", "name": "Tg", "channel": "telegram",
         "config": {"telegram": {"bot_token": "t", "chat_id": "1"}}},
        _email_doc(),
        _email_doc(notif_id="ntf-abc2"),
    ]
    reports = asyncio.run(broadcast_email(channels, "Subj", "body"))
    # telegram di-ignore; 2 email (dedup by notif_id — 2 unique)
    assert len(reports) == 2
    assert all(r["channel"] == "email" for r in reports)


# ── outgoing dedup ────────────────────────────────────────────────────────────

@patch("services.email_client.aiosmtplib.SMTP")
def test_outgoing_dedup_email(MockSMTP):
    inst = MockSMTP.return_value
    inst.connect = AsyncMock()
    inst.ehlo = AsyncMock()
    inst.send_message = AsyncMock()
    inst.quit = AsyncMock()
    cfg = {
        "host": "h", "port": 587, "security": "starttls",
        "user": None, "password": None, "from_addr": "a@b.c",
        "to": ["x@y.z"], "cc": [], "bcc": [],
    }
    r1 = asyncio.run(send_email(cfg, "S", "b"))
    r2 = asyncio.run(send_email(cfg, "S", "b"))  # <60s → dedup
    assert r1["ok"] is True and r2["ok"] is True
    assert inst.send_message.await_count == 1


# ── parse address list ────────────────────────────────────────────────────────

def test_parse_address_list():
    from services.email_client import _build_message

    cfg = {
        "host": "h", "port": 587, "security": "starttls",
        "user": None, "password": None, "from_addr": '"Nama" <a@b.c>',
        "to": ["x@y.z", "w@v.u"], "cc": [], "bcc": [],
    }
    msg = _build_message(cfg, "S", "b")
    assert "x@y.z" in msg["To"] and "w@v.u" in msg["To"]


def test_format_addr_display_name():
    assert _format_addr('"Uptime Kuma" <example@kuma.pet>') == "Uptime Kuma <example@kuma.pet>"
    assert _format_addr("plain@email.com") == "plain@email.com"
