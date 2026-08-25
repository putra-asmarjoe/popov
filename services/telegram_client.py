import httpx
import logging
import re
from typing import List, Optional

from config.settings import settings

logger = logging.getLogger(__name__)

# Dedup outgoing: cegah kirim pesan identik 2x dalam 60 detik (bug graph double telegram)
import time as _time
import hashlib as _hashlib

_last_sent: dict[str, tuple[str, float]] = {}  # "{token_hash}:{chat_id}" -> (hash, timestamp)

# Telegram legacy Markdown TIDAK mendukung **bold** (double asterisk) — hanya *bold*.
# LLM sering mengeluarkan **...** → parse 400 → fallback plain text (asterisk tampil mentah).
_DOUBLE_ASTERISK_RE = re.compile(r"\*\*([^*]+)\*\*")


def normalize_telegram_markdown(text: str) -> str:
    """Normalisasi Markdown agar kompatibel dengan parse_mode='Markdown' Telegram:
    ubah **bold** menjadi *bold*. Hanya boleh dipakai utk text yg gagal 400, sebelum fallback plain.
    """
    return _DOUBLE_ASTERISK_RE.sub(r"*\1*", text)


def _api_url(bot_token: str, method: str) -> str:
    return f"{settings.telegram_api_base}/bot{bot_token}/{method}"


def _require_creds(bot_token: Optional[str], chat_id: Optional[str]) -> tuple[str, str]:
    """Fix #40: tidak ada lagi fallback .env — kredensial WAJIB eksplisit
    (dari dokumen notification_targets). Tanpa env global, kirim tanpa kredensial
    jelas bug, bukan fallback yang valid."""
    token = (bot_token or "").strip()
    target = (chat_id or "").strip()
    if not token or not target:
        raise ValueError("Telegram bot_token & chat_id wajib (dari channel notifikasi DB)")
    return token, target


def _dedup_key(token: str, chat_id: str) -> str:
    """Dedup PER BOT+chat (Fix #40) — dua channel beda bot ke chat sama tak saling menekan."""
    return f"{_hashlib.sha1(token.encode()).hexdigest()[:10]}:{chat_id}"


async def send_message(
    text: str,
    chat_id: str,
    reply_markup: Optional[dict] = None,
    bot_token: str = "",
) -> bool:
    """Send a message to Telegram. Automatically falls back to plain text if Markdown fails.

    Fix #40 multi-bot: bot_token & chat_id eksplisit dari channel notifikasi (wajib).
    """
    token, target_chat = _require_creds(bot_token, chat_id)

    # Outgoing dedup: skip duplicate text+markup within 60s (graph double-invoke guard)
    try:
        h = _hashlib.md5(f"{text}|{reply_markup}".encode()).hexdigest()
        now = _time.time()
        key = _dedup_key(token, target_chat)
        last = _last_sent.get(key)
        if last and last[0] == h and (now - last[1]) < 60:
            logger.warning(f"Dedup: skip duplicate telegram send to {target_chat} (<60s)")
            return True
        _last_sent[key] = (h, now)
    except Exception:
        pass

    url = _api_url(token, "sendMessage")
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            logger.info(f"Telegram message sent to {target_chat}")
            return True

        # Fallback jika parse_mode Markdown gagal (HTTP 400 Bad Request)
        logger.warning(f"Telegram Markdown send failed ({resp.status_code}): {resp.text}. Retrying plain text...")
        # Coba normalisasi **bold** -> *bold* (sering jadi penyebab 400 di LLM output)
        normalized = normalize_telegram_markdown(text)
        normalized_payload = {
            "chat_id": target_chat,
            "text": normalized,
            "parse_mode": "Markdown",
        }
        resp_norm = await client.post(url, json=normalized_payload)
        if resp_norm.status_code == 200:
            logger.info(f"Telegram message sent (normalized markdown) to {target_chat}")
            return True

        fallback_payload = {
            "chat_id": target_chat,
            "text": text,
        }
        resp_fallback = await client.post(url, json=fallback_payload)
        resp_fallback.raise_for_status()
        result = resp_fallback.json()

    if result.get("ok"):
        logger.info(f"Telegram fallback message sent to {target_chat}")
        return True

    logger.error(f"Telegram API error: {result}")
    return False


def build_alert_buttons(
    service_name: Optional[str],
    callback_ref: Optional[str] = None,
) -> dict:
    """Inline keyboard standar laporan alert (Cek Detail / Skip)."""
    svc = service_name or "general"
    detail_data = f"detail:{svc}" if not callback_ref else f"detail:{svc}:{callback_ref}"
    return {
        "inline_keyboard": [
            [
                {"text": "🔍 Cek Detail", "callback_data": detail_data},
                {"text": "⏭️ Skip", "callback_data": f"skip:{svc}"},
            ]
        ]
    }


async def send_interactive_message(
    text: str,
    service_name: Optional[str] = None,
    chat_id: str = "",
    show_buttons: bool = True,
    callback_ref: Optional[str] = None,
    bot_token: str = "",
) -> bool:
    """
    Kirim pesan langsung ke Telegram dengan tombol Inline Keyboard (Cek Detail & Skip) tanpa LLM agent.
    callback_ref: id referensi (mis. alert_id dari watchdog_alerts) yang dibawa tombol
    "Cek Detail" agar pipeline bisa menelusuri konteks sebelumnya di MongoDB.
    Fix #40 multi-bot: bot_token & chat_id eksplisit (wajib).
    """
    token, target_chat = _require_creds(bot_token, chat_id)

    url = _api_url(token, "sendMessage")
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "Markdown",
    }

    if show_buttons:
        payload["reply_markup"] = build_alert_buttons(service_name, callback_ref)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            logger.info(f"Interactive Telegram message sent to {target_chat}")
            return True

        # Fallback jika parse_mode Markdown gagal
        logger.warning(f"Telegram Markdown send failed ({resp.status_code}): {resp.text}. Retrying plain text...")
        # Coba normalisasi **bold** -> *bold* dulu (penyebab umum 400 pada LLM output)
        norm_payload = dict(payload)
        norm_payload["text"] = normalize_telegram_markdown(text)
        resp_norm = await client.post(url, json=norm_payload)
        if resp_norm.status_code == 200:
            logger.info(f"Interactive Telegram message sent (normalized) to {target_chat}")
            return True

        payload.pop("parse_mode", None)
        resp_fallback = await client.post(url, json=payload)
        resp_fallback.raise_for_status()
        result = resp_fallback.json()
        return bool(result.get("ok"))


async def broadcast(channels: List[dict], text: str, reply_markup: Optional[dict] = None) -> int:
    """Kirim teks yang sama ke SEMUA channel match (plan Fix #40).

    channels: list dokumen notification_targets LENGKAP (config included).
    Return jumlah pengiriman sukses. Kegagalan satu channel tidak menghentikan yang lain.
    """
    from services.notification_store import extract_telegram_creds

    sent = 0
    seen: set = set()
    for ch in channels:
        nid = ch.get("notif_id")
        if nid and nid in seen:
            continue
        if nid:
            seen.add(nid)
        token, chat = extract_telegram_creds(ch)
        try:
            if await send_message(text, chat_id=chat or "", bot_token=token or "", reply_markup=reply_markup):
                sent += 1
        except Exception as e:
            logger.warning(f"Broadcast ke '{ch.get('name')}' ({nid}) gagal: {e}")
    if not channels:
        logger.warning("Broadcast: 0 channel match — pesan tidak terkirim")
    return sent


async def answer_callback_query(callback_query_id: str, text: str = "", bot_token: str = "") -> bool:
    """Beri respons pop-up saat tombol Inline Keyboard diklik di Telegram.

    Fix #40: pakai token bot PEMILIK pesan (channel asal), bukan lagi hardcode .env —
    tombol pada pesan dari bot DB-channel kini bisa dijawab.
    """
    token = (bot_token or "").strip()
    if not token or not callback_query_id:
        return False

    url = _api_url(token, "answerCallbackQuery")
    payload = {"callback_query_id": callback_query_id, "text": text}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to answer callback query: {e}")
        return False


async def edit_message_reply_markup(
    chat_id: str,
    message_id: int,
    reply_markup: Optional[dict] = None,
    bot_token: str = "",
) -> bool:
    """Edit inline keyboard pada pesan yang sudah terkirim (untuk feedback UX)."""
    token = (bot_token or "").strip()
    if not token or not chat_id or not message_id:
        return False

    url = _api_url(token, "editMessageReplyMarkup")
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
    }
    # Telegram: untuk menghapus keyboard kirim inline_keyboard kosong
    payload["reply_markup"] = reply_markup if reply_markup is not None else {"inline_keyboard": []}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info(f"Edited reply_markup for message {message_id} in {chat_id}")
                return True
            logger.warning(f"editMessageReplyMarkup failed {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to edit message reply markup: {e}")
        return False
