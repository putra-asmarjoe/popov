"""
Diagnostic Session — Fase 6C (multi-turn, TTL 30m, per chat_id)
State machine minimal: downstream (2 stage) → service-fault (1) → unknown (2)
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

COLLECTION = "diagnostic_sessions"
TTL_MINUTES = 30

# State machine definisi (Fase 6C Plan)
STATE_MACHINE = {
    "downstream": [
        {
            "stage": "awaiting_timeframe",
            "question": "Apakah ini insiden baru atau sudah terjadi sejak sebelumnya?",
            "buttons": [
                {"text": "🆕 Baru terjadi", "callback_data": "diag:timeframe:new"},
                {"text": "🔄 Sudah dari tadi", "callback_data": "diag:timeframe:existing"},
                {"text": "❓ Tidak tahu", "callback_data": "diag:timeframe:unknown"},
            ],
            "next": {"new": None, "existing": "awaiting_escalation", "unknown": "awaiting_escalation"},
        },
        {
            "stage": "awaiting_escalation",
            "question": "Mau saya eskalasi ke tim payment sekarang?",
            "buttons": [
                {"text": "📣 Ya, eskalasi", "callback_data": "diag:escalation:yes"},
                {"text": "⏳ Tunggu dulu", "callback_data": "diag:escalation:no"},
            ],
            "next": {"yes": None, "no": None},
        },
    ],
    "service-fault": [
        {
            "stage": "awaiting_deploy_info",
            "question": "Ada deploy baru untuk service ini dalam 2 jam terakhir?",
            "buttons": [
                {"text": "✅ Ada deploy", "callback_data": "diag:deploy:yes"},
                {"text": "❌ Tidak ada", "callback_data": "diag:deploy:no"},
                {"text": "❓ Tidak tahu", "callback_data": "diag:deploy:unknown"},
            ],
            "next": {"yes": None, "no": None, "unknown": None},
        }
    ],
    "unknown": [
        {
            "stage": "awaiting_scope",
            "question": "Apakah semua endpoint terpengaruh atau hanya endpoint tertentu?",
            "buttons": [
                {"text": "🌐 Semua endpoint", "callback_data": "diag:scope:all"},
                {"text": "🎯 Endpoint tertentu", "callback_data": "diag:scope:single"},
            ],
            "next": {"all": None, "single": "awaiting_endpoint_detail"},
        },
        {
            "stage": "awaiting_endpoint_detail",
            "question": "Sebutkan endpoint yang terpengaruh (contoh: /api/v1/orders)",
            "buttons": None,  # text input
            "next": {"*": None},
        },
    ],
}

def _get_flow(root_cause: str) -> list[dict]:
    return STATE_MACHINE.get(root_cause, STATE_MACHINE["unknown"])


def _get_first_question(root_cause: str) -> tuple[str, Optional[list]]:
    flow = _get_flow(root_cause)
    first = flow[0]
    return first["question"], first["buttons"]


async def create_session(
    episode_id: str,
    service_name: str,
    root_cause: str,
    chat_id: str,
    notif_id: Optional[str] = None,
) -> Optional[str]:
    """Buat sesi diagnostik baru setelah laporan. Return session_id atau None.

    Fix #40: sesi terikat (chat_id, notif_id) — anti tabrakan antar-bot dengan chat sama.
    """
    if not episode_id or not chat_id:
        return None
    if root_cause not in ("downstream", "service-fault", "unknown"):
        root_cause = "unknown"
    session_id = f"DS-{episode_id}"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=TTL_MINUTES)
    doc = {
        "session_id": session_id,
        "service_name": service_name,
        "root_cause": root_cause,
        "stage": _get_flow(root_cause)[0]["stage"],
        "context": {
            "original_episode_id": episode_id,
            "answers": [],
            "last_question": _get_flow(root_cause)[0]["question"],
        },
        "chat_id": str(chat_id),
        "notif_id": str(notif_id) if notif_id else None,
        "status": "active",
        "created_at": now,
        "expires_at": expires,
    }
    try:
        db = get_db()
        # upsert: jika sudah ada active session untuk chat+episode, replace
        await db[COLLECTION].update_one(
            {"session_id": session_id},
            {"$set": doc},
            upsert=True,
        )
        logger.info(f"[Diagnostic] session created {session_id} root={root_cause} chat={chat_id}")
        return session_id
    except Exception as e:
        logger.error(f"[Diagnostic] create_session failed: {e}")
        return None


async def get_active_session(chat_id: str, notif_id: Optional[str] = None) -> Optional[dict]:
    """Cek sesi aktif untuk chat_id (TTL di Mongo akan auto hapus, tapi cek expires_at juga).

    Fix #40: bila notif_id diberikan, prioritaskan sesi milik bot/channel itu —
    dua bot berbeda di chat sama tidak saling mencuri sesi.
    """
    if not chat_id:
        return None
    try:
        db = get_db()
        now = datetime.now(timezone.utc)
        base = {"chat_id": str(chat_id), "status": "active", "expires_at": {"$gt": now}}
        doc = None
        if notif_id:
            doc = await db[COLLECTION].find_one(
                {**base, "notif_id": str(notif_id)}, sort=[("created_at", -1)]
            )
            if doc is None:
                # fallback sesi legacy (sebelum Fix #40) yang belum punya notif_id
                doc = await db[COLLECTION].find_one(
                    {**base, "notif_id": None}, sort=[("created_at", -1)]
                )
        else:
            doc = await db[COLLECTION].find_one(base, sort=[("created_at", -1)])
        if doc:
            doc["_id"] = str(doc["_id"])
            return doc
        return None
    except Exception as e:
        logger.warning(f"[Diagnostic] get_active_session failed: {e}")
        return None


async def advance_session(session_id: str, user_answer: str) -> dict:
    """
    Proses jawaban user, update stage, return:
    {next_question, next_buttons, trigger_pipeline, completed}
    """
    try:
        db = get_db()
        sess = await db[COLLECTION].find_one({"session_id": session_id, "status": "active"})
        if not sess:
            return {"next_question": None, "next_buttons": None, "trigger_pipeline": None, "completed": True}

        root_cause = sess.get("root_cause", "unknown")
        flow = _get_flow(root_cause)
        current_stage = sess.get("stage")
        # Cari current stage index
        idx = next((i for i, s in enumerate(flow) if s["stage"] == current_stage), 0)
        current = flow[idx]

        # Simpan jawaban
        answers = sess.get("context", {}).get("answers", [])
        answers.append({"stage": current_stage, "answer": user_answer, "at": datetime.now(timezone.utc).isoformat()})

        # Tentukan next stage berdasarkan answer
        # callback_data format diag:<key>:<value> → value adalah answer
        # Untuk text input (single endpoint), answer adalah free text
        answer_key = user_answer.strip().lower()
        # Map callback value
        # Untuk downstream timeframe: new/existing/unknown
        # Untuk escalation: yes/no
        # Untuk deploy: yes/no/unknown
        # Untuk scope: all/single
        next_stage = None
        trigger_pipeline = None

        # Cari mapping next di current
        nxt_map = current.get("next", {})
        # Normalisasi answer_key
        # Jika answer_key mengandung diag: ambil bagian terakhir
        if ":" in answer_key:
            answer_key = answer_key.split(":")[-1].strip()
        # Untuk wildcard
        if answer_key in nxt_map:
            next_stage = nxt_map[answer_key]
        elif "*" in nxt_map:
            next_stage = nxt_map["*"]
        else:
            # Fallback: coba cari key yang substring
            for k, v in nxt_map.items():
                if k in answer_key or answer_key in k:
                    next_stage = v
                    break

        # Trigger pipeline logic per root_cause
        if root_cause == "downstream" and current_stage == "awaiting_timeframe" and answer_key in ("existing", "unknown"):
            # Trigger pipeline window 24 jam
            trigger_pipeline = {
                "intent": f"cek error pada {sess.get('service_name')} window 24 jam",
                "service_name": sess.get("service_name"),
            }
        elif root_cause == "service-fault" and current_stage == "awaiting_deploy_info" and answer_key == "yes":
            trigger_pipeline = {
                "intent": f"cek deploy {sess.get('service_name')} dalam 2 jam terakhir",
                "service_name": sess.get("service_name"),
            }
        elif root_cause == "unknown" and current_stage == "awaiting_scope" and answer_key == "all":
            trigger_pipeline = {
                "intent": f"cek error pada {sess.get('service_name')} broad scan",
                "service_name": sess.get("service_name"),
            }
        elif root_cause == "unknown" and current_stage == "awaiting_endpoint_detail":
            # free text endpoint
            trigger_pipeline = {
                "intent": f"cek error pada {sess.get('service_name')} endpoint {user_answer}",
                "service_name": sess.get("service_name"),
            }

        # Update session
        if next_stage:
            # Lanjut ke next question
            next_q = flow[idx + 1] if idx + 1 < len(flow) else None
            # Tapi next_stage harus match dengan flow[idx+1].stage jika ada next stage
            # Sederhananya: cari flow dengan stage == next_stage
            next_flow = next((s for s in flow if s["stage"] == next_stage), None)
            if next_flow:
                await db[COLLECTION].update_one(
                    {"session_id": session_id},
                    {"$set": {"stage": next_stage, "context.answers": answers, "context.last_question": next_flow["question"]}},
                )
                return {
                    "next_question": next_flow["question"],
                    "next_buttons": next_flow["buttons"],
                    "trigger_pipeline": trigger_pipeline,
                    "completed": False,
                }
            else:
                # next_stage None → completed
                await db[COLLECTION].update_one(
                    {"session_id": session_id},
                    {"$set": {"status": "completed", "context.answers": answers}},
                )
                return {"next_question": None, "next_buttons": None, "trigger_pipeline": trigger_pipeline, "completed": True}
        else:
            # Sesi selesai
            await db[COLLECTION].update_one(
                {"session_id": session_id},
                {"$set": {"status": "completed", "context.answers": answers}},
            )
            return {"next_question": None, "next_buttons": None, "trigger_pipeline": trigger_pipeline, "completed": True}

    except Exception as e:
        logger.error(f"[Diagnostic] advance_session failed: {e}", exc_info=True)
        return {"next_question": None, "next_buttons": None, "trigger_pipeline": None, "completed": True}


async def expire_old_sessions():
    """Cleanup manual jika TTL tidak jalan (fallback)."""
    try:
        db = get_db()
        res = await db[COLLECTION].delete_many({"expires_at": {"$lt": datetime.now(timezone.utc)}})
        if res.deleted_count:
            logger.info(f"[Diagnostic] expired {res.deleted_count} sessions")
    except Exception as e:
        logger.warning(f"[Diagnostic] expire failed: {e}")
