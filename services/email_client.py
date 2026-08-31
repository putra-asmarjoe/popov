"""
Email Client — kirim email via SMTP (aiosmtplib async) utk channel notifikasi email.

Mirror `telegram_client.py`:
- `_require_email_creds`: host/port/from/to WAJIB; user/pass opsional (open relay dev).
- `send_email`: To/CC/BCC multi-recipient, retry 1x utk transient (5xx/conn reset),
  `ignore_tls_error` → validate_certs=False, `disable_starttls` → start_tls=False.
- `broadcast_email`: loop channel email, dedup by notif_id, satu gagal tak hentikan lain.
  Return list delivery-report (utk dicatat ke notification_delivery_logs).
- Outgoing dedup 60s per (host, from, to) — hash md5(subject).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Dict, List, Optional

import aiosmtplib

from services.markdown_html import markdown_to_html

logger = logging.getLogger(__name__)

# Outgoing dedup: key "sha1(host|from|to)[:10]" -> (md5(subject), timestamp)
_last_sent: Dict[str, tuple[str, float]] = {}
_DEDUP_WINDOW = 60.0

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _require_email_creds(cfg: dict) -> dict:
    """Validasi config email. host/port/from/to wajib; user/pass opsional. Return cfg."""
    host = (cfg.get("host") or "").strip()
    port = int(cfg.get("port") or 587)
    from_addr = (cfg.get("from_addr") or "").strip()
    to = [x for x in (cfg.get("to") or []) if str(x).strip()]
    if not host:
        raise ValueError("smtp_host wajib")
    if not from_addr:
        raise ValueError("from_addr wajib")
    if not to:
        raise ValueError("to_addrs wajib (min 1 penerima)")
    return {**cfg, "host": host, "port": port, "from_addr": from_addr, "to": to}


def _format_addr(raw: str) -> str:
    """Support 'Nama' <email> (formataddr) dan email polos."""
    raw = raw.strip()
    m = re.match(r'^"?(.+?)"?\s*<([^>]+)>$', raw)
    if m:
        return formataddr((m.group(1), m.group(2)))
    return raw


def _build_message(cfg: dict, subject: str, text: str, html: Optional[str] = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _format_addr(cfg["from_addr"])
    msg["To"] = ", ".join(_format_addr(x) for x in cfg["to"])
    if cfg.get("cc"):
        msg["Cc"] = ", ".join(_format_addr(x) for x in cfg["cc"])
    if cfg.get("bcc"):
        msg["Bcc"] = ", ".join(_format_addr(x) for x in cfg["bcc"])
    msg["Subject"] = subject
    if html:
        msg.set_content(text or "")
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(text or "")
    return msg


def _dedup_key(cfg: dict, subject: str) -> Optional[str]:
    """Kunci dedup outgoing: sha1(host|from|to) — 2 channel beda SMTP tidak saling tekan."""
    try:
        to_key = "|".join(sorted(cfg.get("to") or []))
        return hashlib.sha1(f"{cfg['host']}|{cfg['from_addr']}|{to_key}".encode()).hexdigest()[:10]
    except Exception:
        return None


async def send_email(
    cfg: dict,
    subject: str,
    text: str,
    html: Optional[str] = None,
    *,
    _now: Optional[float] = None,
) -> Dict[str, Any]:
    """Kirim satu email. Return {ok, detail} — detail ringkas (status SMTP/error), TANPA isi pesan."""
    cfg = _require_email_creds(cfg)
    dedup = _dedup_key(cfg, subject)
    now = _now or time.monotonic()
    if dedup:
        last = _last_sent.get(dedup)
        if last and now - last[1] < _DEDUP_WINDOW and last[0] == hashlib.md5(subject.encode()).hexdigest():
            logger.warning(f"Email dedup: skip duplicate send to {cfg['to']} (<{_DEDUP_WINDOW:.0f}s)")
            return {"ok": True, "detail": "dedup_skipped"}

    use_tls = cfg.get("security") == "ssl"
    start_tls = cfg.get("security") == "starttls" and not cfg.get("disable_starttls")
    smtp = aiosmtplib.SMTP(
        hostname=cfg["host"],
        port=cfg["port"],
        use_tls=use_tls,
        start_tls=start_tls,
        validate_certs=not bool(cfg.get("ignore_tls_error")),
        timeout=15,
    )
    try:
        await smtp.connect()
        await smtp.ehlo()
        if cfg.get("user"):
            await smtp.login(cfg["user"], cfg.get("password") or "")
        msg = _build_message(cfg, subject, text, html)
        rcpt = list(cfg["to"]) + list(cfg.get("cc") or []) + list(cfg.get("bcc") or [])
        await smtp.send_message(msg, recipients=rcpt)
        await smtp.quit()
        if dedup:
            _last_sent[dedup] = (hashlib.md5(subject.encode()).hexdigest(), now)
        logger.info(f"Email sent to {cfg['to']} via {cfg['host']}:{cfg['port']}")
        return {"ok": True, "detail": "250 OK"}
    except Exception as e:
        try:
            await smtp.quit()
        except Exception:
            pass
        # Retry 1x utk transient (koneksi reset / timeout) — bukan auth error.
        # Guard: hanya retry bila dipanggil pertama kali (tanpa _now override).
        transient = any(k in str(e).lower() for k in ("timeout", "connection reset", "refused", "temporarily", "econnreset"))
        if transient and _now is None:
            logger.warning(f"Email transient error, retry 1x: {e}")
            return await send_email(cfg, subject, text, html, _now=now)
        logger.error(f"Email send failed via {cfg['host']}:{cfg['port']}: {e}")
        return {"ok": False, "detail": str(e)[:200]}


async def broadcast_email(
    channels: List[dict],
    subject: str,
    text: str,
    html: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Kirim ke semua channel email match (ignore telegram). Return list delivery-report."""
    from services.notification_store import extract_email_creds

    reports: List[Dict[str, Any]] = []
    seen: set = set()
    for ch in channels:
        nid = ch.get("notif_id")
        if nid and nid in seen:
            continue
        if nid:
            seen.add(nid)
        cfg = extract_email_creds(ch)
        if not cfg:
            continue  # bukan channel email — di-ignore
        try:
            result = await send_email(cfg, subject, text, html)
            reports.append({
                "notif_id": nid,
                "name": ch.get("name"),
                "channel": "email",
                "target": ", ".join(cfg.get("to") or []),
                "ok": result.get("ok", False),
                "detail": result.get("detail", ""),
            })
        except Exception as e:
            reports.append({
                "notif_id": nid,
                "name": ch.get("name"),
                "channel": "email",
                "target": ", ".join(cfg.get("to") or []) if cfg else "",
                "ok": False,
                "detail": str(e)[:200],
            })
    if not reports:
        logger.warning("Email broadcast: 0 channel email match")
    return reports


# Re-export utk notifier/markdown convenience
__all__ = ["send_email", "broadcast_email", "_require_email_creds", "markdown_to_html"]
