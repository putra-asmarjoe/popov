"""
User Profile Batch Inference — Phase 4 (USER_PROFILE_PLAN.md §3 Phase 4).

Pola Pattern Miner: loop periodik di watchdog_worker (off hot-path), 1 LLM call
per user per batch. Hanya field yang BELUM di-set manual yang disarankan (D3).
Trust model D4: saran = pending → user approve ATAU auto-apply setelah 24 jam
tanpa rejection. Reject = tidak auto-apply, trigger di-reset (tidak tanya lagi cepat).

Trigger batch (plan rev.2 #2): interaction_count - last_inferred_interaction_count >= 20.
Sumber inferensi = COUNTER SAJA (services_queried, active_hours, chips_clicked,
investigation_count, feedback keys di chips_clicked). TIDAK membaca konten percakapan
(non-goal privacy). Exception-safe: kegagalan 1 user tidak menggagalkan batch.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.mongodb_client import get_db
from services.user_profile import COLLECTION, _MANUAL_ENUMS, set_manual_fields

logger = logging.getLogger(__name__)

# Trigger: selisih interaksi sejak inferensi terakhir
MIN_INTERACTION_DELTA = 20
# TTL saran — auto-apply setelah ini tanpa rejection
SUGGESTION_TTL_HOURS = 24
# Maksimum user diproses per siklus (batasi beban LLM)
BATCH_LIMIT = 5
# Enum default_chat_depth (plan: range 1-5)
DEPTH_RANGE = (1, 2, 3, 4, 5)

# Field yang BISA disarankan batch + enum valid
INFER_FIELDS: Dict[str, tuple] = {
    **_MANUAL_ENUMS,  # verbosity, tone, format_preference
    "default_chat_depth": tuple(DEPTH_RANGE),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _eligible_candidates(doc: Dict[str, Any]) -> Dict[str, tuple]:
    """Field yang bisa disarankan utk user ini = field TIDAK di manual_overrides."""
    overridden = set(doc.get("manual_overrides") or [])
    return {f: enums for f, enums in INFER_FIELDS.items() if f not in overridden}


def _counter_summary(doc: Dict[str, Any]) -> str:
    """Ringkasan counter utk LLM — anonim, tanpa konten percakapan."""
    lines = [f"interaction_count: {doc.get('interaction_count') or 0}",
             f"investigation_count: {doc.get('investigation_count') or 0}"]
    svcs = doc.get("services_queried") or {}
    if svcs:
        top = sorted(svcs.items(), key=lambda kv: kv[1], reverse=True)[:5]
        lines.append("services_queried: " + ", ".join(f"{s}={c}" for s, c in top))
    chips = doc.get("chips_clicked") or {}
    if chips:
        lines.append("chips_clicked: " + ", ".join(f"{k}={v}" for k, v in sorted(chips.items(), key=lambda kv: kv[1], reverse=True)[:8]))
    hours = doc.get("active_hours") or []
    if isinstance(hours, list) and len(hours) == 24:
        peak = max(range(24), key=lambda h: hours[h] if isinstance(hours[h], (int, float)) else 0)
        if hours[peak]:
            lines.append(f"peak_active_hour_utc: {peak:02d} (count={hours[peak]})")
    return "\n".join(lines)


def _field_candidates_text(candidates: Dict[str, tuple]) -> str:
    out = []
    for f, enums in candidates.items():
        out.append(f"- {f}: one of {list(enums)}")
    return "\n".join(out) or "(none — all fields manually set)"


async def _llm_suggest(counter_summary: str, candidates: Dict[str, tuple]) -> List[Dict[str, Any]]:
    """1 LLM call — draft saran field dari counter summary. Return list[{field, value, reason}]."""
    from services.prompt_loader import render as render_prompt
    from services.llm_factory import get_chat_llm

    prompt = render_prompt(
        "user_profile_infer",
        counter_summary=counter_summary,
        field_candidates=_field_candidates_text(candidates),
    )
    try:
        from langchain_core.messages import HumanMessage
        import asyncio

        llm = get_chat_llm(temperature=0.2)
        resp = await asyncio.wait_for(
            llm.ainvoke([HumanMessage(content=prompt)]), timeout=25,
        )
        text = (resp.content or "").strip() if hasattr(resp, "content") else str(resp).strip()
        # Robust parse: ambil blok JSON pertama {...}
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return []
        data = json.loads(text[start:end + 1])
        return data.get("suggestions") or []
    except Exception as e:
        logger.warning(f"[UserProfileInfer] LLM suggest gagal (non-fatal): {e}")
        return []


async def _find_due_profiles(batch: int = BATCH_LIMIT) -> List[Dict[str, Any]]:
    """Profil yang memenuhi trigger inferensi & belum punya pending aktif."""
    db = get_db()
    coll = db[COLLECTION]
    now = _now()
    # pending aktif = pending_suggestion dengan status "pending" dan expires_at > now
    cursor = coll.find({
        "$expr": {
            "$gte": [
                {"$subtract": [
                    {"$ifNull": ["$interaction_count", 0]},
                    {"$ifNull": ["$last_inferred_interaction_count", 0]},
                ]},
                MIN_INTERACTION_DELTA,
            ]
        },
        "$or": [
            {"pending_suggestion": None},
            {"pending_suggestion.status": {"$ne": "pending"}},
            {"pending_suggestion.expires_at": {"$lt": now}},
        ],
    }).sort("updated_at", -1).limit(batch)
    return [d async for d in cursor]


async def _store_pending(user_id: str, workspace_id: str, suggestions: List[Dict[str, Any]],
                         run_id: str) -> bool:
    """Simpan draft sbg pending_suggestion (fields tervalidasi enum). Return True bila ada."""
    valid_fields = {f: enums for f, enums in INFER_FIELDS.items()}
    fields: Dict[str, Any] = {}
    reasons: Dict[str, str] = {}
    for s in suggestions:
        f = (s or {}).get("field")
        v = (s or {}).get("value")
        if f not in valid_fields:
            continue
        enums = valid_fields[f]
        # int untuk default_chat_depth (LLM bisa kirim str)
        if f == "default_chat_depth" and isinstance(v, str) and v.isdigit():
            v = int(v)
        if v not in enums:
            continue
        fields[f] = v
        reasons[f] = ((s or {}).get("reason") or "")[:200]
    if not fields:
        # Tidak ada saran valid → tetap catat infer sudah jalan (hindari ulang cepat)
        await coll_update(user_id, workspace_id, {
            "pending_suggestion": None,
            "last_inferred_interaction_count": None,  # di-set saat apply/reject; tanpa saran = tidak perlu
        }, set_last_inferred=True)
        return False
    now = _now()
    await coll_update(user_id, workspace_id, {
        "pending_suggestion": {
            "run_id": run_id,
            "fields": fields,
            "reasons": reasons,
            "generated_at": now,
            "expires_at": now + timedelta(hours=SUGGESTION_TTL_HOURS),
            "status": "pending",
        },
    })
    return True


async def coll_update(user_id: str, workspace_id: str, data: Dict[str, Any], *,
                      set_last_inferred: bool = False) -> None:
    """Helper update profil (exception-safe)."""
    try:
        db = get_db()
        doc = await db[COLLECTION].find_one_and_update(
            {"user_id": str(user_id), "workspace_id": str(workspace_id)},
            {"$set": {**data, "updated_at": _now()}},
            return_document=True,
        )
        if doc is not None and set_last_inferred:
            # setelah saran kosong → interaction_count jadi baseline (jangan tanya lagi cepat)
            await db[COLLECTION].update_one(
                {"user_id": str(user_id), "workspace_id": str(workspace_id)},
                {"$set": {"last_inferred_interaction_count": doc.get("interaction_count") or 0,
                          "updated_at": _now()}},
            )
    except Exception as e:
        logger.warning(f"[UserProfileInfer] update gagal (non-fatal): {e}")


async def infer_once(batch: int = BATCH_LIMIT) -> Dict[str, Any]:
    """Satu siklus batch inferensi. Return stats."""
    stats = {"scanned": 0, "suggested": 0, "empty": 0, "skipped_manual": 0, "failed": 0}
    try:
        docs = await _find_due_profiles(batch)
        stats["scanned"] = len(docs)
        for doc in docs:
            try:
                if not _eligible_candidates(doc):
                    stats["skipped_manual"] += 1
                    await coll_update(str(doc["user_id"]), str(doc["workspace_id"]), {},
                                      set_last_inferred=True)
                    continue
                summary = _counter_summary(doc)
                suggestions = await _llm_suggest(summary, _eligible_candidates(doc))
                run_id = uuid.uuid4().hex[:12]
                stored = await _store_pending(str(doc["user_id"]), str(doc["workspace_id"]),
                                              suggestions, run_id)
                stats["suggested" if stored else "empty"] += 1
            except Exception as e:
                logger.warning(f"[UserProfileInfer] infer satu profil gagal: {e}")
                stats["failed"] += 1
        if stats["suggested"] or stats["empty"]:
            logger.info(f"[UserProfileInfer] cycle done {stats}")
        return stats
    except Exception as e:
        logger.error(f"[UserProfileInfer] batch gagal: {e}", exc_info=True)
        return stats


async def reject_pending(user_id: str, workspace_id: str) -> bool:
    """User menolak saran → pending dibuang + baseline di-reset (tidak auto-apply)."""
    try:
        db = get_db()
        doc = await db[COLLECTION].find_one(
            {"user_id": str(user_id), "workspace_id": str(workspace_id)}
        )
        if not doc or not (doc.get("pending_suggestion") or {}).get("fields"):
            return False
        await db[COLLECTION].update_one(
            {"user_id": str(user_id), "workspace_id": str(workspace_id)},
            {"$set": {
                "pending_suggestion": {
                    "run_id": (doc.get("pending_suggestion") or {}).get("run_id"),
                    "fields": (doc.get("pending_suggestion") or {}).get("fields"),
                    "reasons": (doc.get("pending_suggestion") or {}).get("reasons"),
                    "generated_at": (doc.get("pending_suggestion") or {}).get("generated_at"),
                    "expires_at": (doc.get("pending_suggestion") or {}).get("expires_at"),
                    "status": "rejected",
                },
                "last_inferred_interaction_count": doc.get("interaction_count") or 0,
                "updated_at": _now(),
            }},
        )
        logger.info(f"[UserProfileInfer] saran ditolak user {user_id}/{workspace_id}")
        return True
    except Exception as e:
        logger.warning(f"[UserProfileInfer] reject gagal (non-fatal): {e}")
        return False


async def apply_pending(user_id: str, workspace_id: str) -> Dict[str, Any]:
    """User approve → set manual fields (D3: batch kini jadi manual) + clear pending.
    Return profil terbaru (public shape)."""
    db = get_db()
    doc = await db[COLLECTION].find_one(
        {"user_id": str(user_id), "workspace_id": str(workspace_id)}
    )
    if not doc:
        raise ValueError("Profile not found")
    pending = doc.get("pending_suggestion") or {}
    fields = pending.get("fields") or {}
    if not fields:
        raise ValueError("No pending suggestion to apply")
    # set manual fields (addToSet manual_overrides) — field kini jadi manual (D3)
    await set_manual_fields(user_id, workspace_id, fields)
    # tandai pending applied + baseline baru
    await db[COLLECTION].update_one(
        {"user_id": str(user_id), "workspace_id": str(workspace_id)},
        {"$set": {
            "pending_suggestion": {**pending, "status": "applied"},
            "last_inferred_interaction_count": doc.get("interaction_count") or 0,
            "updated_at": _now(),
        }},
    )
    logger.info(f"[UserProfileInfer] saran di-apply user {user_id}/{workspace_id}: {list(fields)}")
    from services.user_profile import get_profile
    return await get_profile(user_id, workspace_id)


async def auto_apply_expired() -> Dict[str, Any]:
    """Auto-apply saran pending yang expired (>TTL, tanpa rejection) — D4.
    Return stats {applied, skipped_rejected, none}."""
    stats = {"applied": 0, "expired_no_fields": 0}
    try:
        db = get_db()
        now = _now()
        cursor = db[COLLECTION].find({
            "pending_suggestion.status": "pending",
            "pending_suggestion.expires_at": {"$lt": now},
            "pending_suggestion.fields": {"$ne": None},
        })
        docs = [d async for d in cursor]
        for doc in docs:
            fields = ((doc.get("pending_suggestion") or {}).get("fields") or {})
            if not fields:
                continue
            try:
                await set_manual_fields(str(doc["user_id"]), str(doc["workspace_id"]), fields)
                pending = doc.get("pending_suggestion") or {}
                await db[COLLECTION].update_one(
                    {"user_id": str(doc["user_id"]), "workspace_id": str(doc["workspace_id"])},
                    {"$set": {
                        "pending_suggestion": {**pending, "status": "applied"},
                        "last_inferred_interaction_count": doc.get("interaction_count") or 0,
                        "updated_at": now,
                    }},
                )
                stats["applied"] += 1
                logger.info(f"[UserProfileInfer] auto-apply {doc['user_id']}/{doc['workspace_id']}: {list(fields)}")
            except Exception as e:
                logger.warning(f"[UserProfileInfer] auto-apply gagal (non-fatal): {e}")
        if stats["applied"]:
            logger.info(f"[UserProfileInfer] auto-apply cycle {stats}")
        return stats
    except Exception as e:
        logger.error(f"[UserProfileInfer] auto_apply gagal: {e}", exc_info=True)
        return stats


async def start_infer_loop(interval_sec: int = 3600) -> None:
    """Loop periodik watchdog: infer batch + auto-apply expired."""
    logger.info(f"[UserProfileInfer] loop started interval={interval_sec}s")
    while True:
        try:
            await auto_apply_expired()
            await infer_once()
        except asyncio.CancelledError:
            logger.info("[UserProfileInfer] cancelled")
            break
        except Exception as e:
            logger.error(f"[UserProfileInfer] loop error: {e}")
        await asyncio.sleep(interval_sec)
