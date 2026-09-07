"""
User Profile — Phase 1 (USER_PROFILE_PLAN.md §3 Phase 1).

Counter pasif + manual fields per (user_id, workspace_id). Enrichment layer —
BUKAN agent baru, TIDAK menyentuh hot path routing. Semua fungsi exception-safe
(counter gagal tidak boleh pernah merusak pipeline/chat).

Sumber kebenaran (plan §2):
- Manual fields (verbosity/tone/format_preference/default_chat_depth) — di-set
  user via PATCH /profile; tercatat di manual_overrides (batch inferensi Phase 4
  TIDAK boleh menimpa).
- Counter pasif: services_queried, active_hours, chips_clicked,
  investigation_count, interaction_count — di-update dari hook chat pipeline.
- Lazy decay: interaksi > DECAY_DAYS sejak last_active_at → counter ×0.5
  SEBELUM increment (decay jalan sejak Phase 1, tidak menunggu loop Phase 4).

Locale: TIDAK disimpan di sini — sumber tunggal = user_store.locale_preference
(lihat comment di user_store.py & USER_PROFILE_PLAN.md §1 risiko Q5).
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

COLLECTION = "user_profiles"
DECAY_DAYS = 90
DECAY_FACTOR = 0.5
# Threshold render blok prompt (D5) — dipakai Phase 3, didefinisikan di sini
# supaya satu sumber: render bila ≥1 manual field ATAU interaction_count >= 10.
MIN_INTERACTIONS_FOR_RENDER = 10
COUNTER_KEYS = ("services_queried", "active_hours", "chips_clicked")

_MANUAL_ENUMS = {
    "verbosity": ("concise", "standard", "detailed"),
    "tone": ("formal", "casual"),
    "format_preference": ("list", "paragraph", "mixed"),
}


async def ensure_indexes() -> None:
    """Index profil: unique (user_id, workspace_id) + last_active_at (decay scan)."""
    try:
        db = get_db()
        await db[COLLECTION].create_index(
            [("user_id", 1), ("workspace_id", 1)], unique=True
        )
        await db[COLLECTION].create_index([("last_active_at", 1)])
    except Exception as e:
        logger.warning(f"[UserProfile] ensure_indexes failed (non-fatal): {e}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _needs_decay(doc: Dict[str, Any]) -> bool:
    last = _as_aware_utc(doc.get("last_active_at"))
    return last is not None and (_now() - last > timedelta(days=DECAY_DAYS))


def _as_aware_utc(value: Any) -> Optional[datetime]:
    """BSON Date balik naive (tzinfo hilang) — anggap UTC. None/invalid → None."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _apply_lazy_decay(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy decay (plan rev.2 #4): interaksi >90 hari → counter ×0.5 sebelum
    increment. Dipanggil dari update_profile_counters — tanpa loop terpisah."""
    last = _as_aware_utc(doc.get("last_active_at"))
    if last is None or (_now() - last <= timedelta(days=DECAY_DAYS)):
        return doc
    scaled = dict(doc)
    for key in COUNTER_KEYS:
        mapping = scaled.get(key) or {}
        if isinstance(mapping, dict):
            scaled[key] = {k: int(v * DECAY_FACTOR) for k, v in mapping.items()}
    scaled["interaction_count"] = int((scaled.get("interaction_count") or 0) * DECAY_FACTOR)
    scaled["investigation_count"] = int((scaled.get("investigation_count") or 0) * DECAY_FACTOR)
    return scaled


def _new_doc(user_id: str, workspace_id: str) -> Dict[str, Any]:
    now = _now()
    return {
        "user_id": str(user_id),
        "workspace_id": str(workspace_id),
        "verbosity": None,
        "tone": None,
        "format_preference": None,
        "default_chat_depth": None,
        "manual_overrides": [],
        "services_queried": {},
        "active_hours": [0] * 24,
        "chips_clicked": {},
        "investigation_count": 0,
        "interaction_count": 0,
        "pending_suggestion": None,
        "last_inferred_interaction_count": None,
        "created_at": now,
        "updated_at": now,
        "last_active_at": now,
    }


async def update_profile_counters(
    user_id: str,
    workspace_id: str,
    *,
    service_name: Optional[str] = None,
    intent: str = "",
    routing_strategy: Optional[str] = None,
    agents: Optional[list] = None,
    chip_key: Optional[str] = None,
) -> None:
    """Update counter pasif — fire-and-forget dari hook chat pipeline.

    NEVER raises: kegagalan DB dicatat warning, pipeline chat tidak boleh terganggu.
    """
    try:
        if not user_id or not workspace_id:
            return
        db = get_db()
        now = _now()
        selector = {"user_id": str(user_id), "workspace_id": str(workspace_id)}
        existing = await db[COLLECTION].find_one(selector)
        # Decay lazy: bila idle >90 hari → set counter scaled DULU (update terpisah
        # — $set & $inc path sama = Mongo conflict 40), baru increment.
        if existing and _needs_decay(existing):
            scaled = _apply_lazy_decay(existing)
            await db[COLLECTION].update_one(selector, {"$set": {
                k: scaled.get(k) or {} for k in COUNTER_KEYS
            } | {
                "interaction_count": int(scaled.get("interaction_count") or 0),
                "investigation_count": int(scaled.get("investigation_count") or 0),
            }})

        inc: Dict[str, Any] = {
            "interaction_count": 1,
            f"active_hours.{now.hour}": 1,
        }
        svc = (service_name or "").strip()
        if svc:
            inc[f"services_queried.{svc}"] = 1
        if chip_key:
            inc[f"chips_clicked.{chip_key}"] = 1
        agents = agents or []
        if "triage_agent" in agents or (routing_strategy or "").startswith("ticket_investigate"):
            inc["investigation_count"] = 1

        # $setOnInsert MINIMAL — jangan bentrok dgn $set/$inc paths (conflict 40)
        update: Dict[str, Any] = {
            "$set": {"updated_at": now, "last_active_at": now},
            "$inc": inc,
            "$setOnInsert": {
                "user_id": str(user_id), "workspace_id": str(workspace_id),
                "verbosity": None, "tone": None, "format_preference": None,
                "default_chat_depth": None, "manual_overrides": [],
                "pending_suggestion": None, "last_inferred_interaction_count": None,
                "created_at": now,
            },
        }
        await db[COLLECTION].update_one(selector, update, upsert=True)
    except Exception as e:
        logger.warning(f"[UserProfile] update_profile_counters failed (non-fatal): {e}")


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "workspace_id": doc.get("workspace_id"),
        "verbosity": doc.get("verbosity"),
        "tone": doc.get("tone"),
        "format_preference": doc.get("format_preference"),
        "default_chat_depth": doc.get("default_chat_depth"),
        "manual_overrides": doc.get("manual_overrides") or [],
        "services_queried": doc.get("services_queried") or {},
        "active_hours": doc.get("active_hours") or [0] * 24,
        "chips_clicked": doc.get("chips_clicked") or {},
        "investigation_count": doc.get("investigation_count") or 0,
        "interaction_count": doc.get("interaction_count") or 0,
        "pending_suggestion": doc.get("pending_suggestion"),
        "last_active_at": doc.get("last_active_at"),
        "updated_at": doc.get("updated_at"),
    }


async def get_profile(user_id: str, workspace_id: str) -> Dict[str, Any]:
    """Profil user (get-or-init). Tidak pernah raise untuk DB kosong."""
    try:
        db = get_db()
        doc = await db[COLLECTION].find_one(
            {"user_id": str(user_id), "workspace_id": str(workspace_id)}
        ) or _new_doc(user_id, workspace_id)
        return _public(doc)
    except Exception as e:
        logger.warning(f"[UserProfile] get_profile failed (non-fatal): {e}")
        return _public(_new_doc(user_id, workspace_id))


async def set_manual_fields(user_id: str, workspace_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Set manual fields + catat manual_overrides (D3: batch Phase 4 tak boleh menimpa).
    Raise ValueError untuk nilai di luar enum — API layer yang menerjemahkan ke 422."""
    updates: Dict[str, Any] = {}
    for key, value in fields.items():
        if key not in _MANUAL_ENUMS and key != "default_chat_depth":
            raise ValueError(f"Unknown profile field: {key}")
        if key in _MANUAL_ENUMS and value is not None and value not in _MANUAL_ENUMS[key]:
            raise ValueError(f"Invalid value for {key}: {value!r}")
        if key == "default_chat_depth":
            if value is not None and not (isinstance(value, int) and 1 <= value <= 5):
                raise ValueError("default_chat_depth must be int 1–5")
        updates[key] = value
    if not updates:
        return await get_profile(user_id, workspace_id)

    db = get_db()
    now = _now()
    await db[COLLECTION].update_one(
        {"user_id": str(user_id), "workspace_id": str(workspace_id)},
        {
            "$set": {**updates, "updated_at": now},
            "$addToSet": {"manual_overrides": {"$each": list(updates.keys())}},
            "$setOnInsert": {
                "user_id": str(user_id), "workspace_id": str(workspace_id),
                "created_at": now,
            },
        },
        upsert=True,
    )
    return await get_profile(user_id, workspace_id)


async def reset_counters(user_id: str, workspace_id: str) -> Dict[str, Any]:
    """Zero counter pasif — manual fields & manual_overrides TIDAK tersentuh."""
    db = get_db()
    now = _now()
    await db[COLLECTION].update_one(
        {"user_id": str(user_id), "workspace_id": str(workspace_id)},
        {
            "$set": {
                "services_queried": {}, "active_hours": [0] * 24, "chips_clicked": {},
                "investigation_count": 0, "interaction_count": 0, "updated_at": now,
            },
            "$setOnInsert": {
                "user_id": str(user_id), "workspace_id": str(workspace_id),
                "verbosity": None, "tone": None, "format_preference": None,
                "default_chat_depth": None, "manual_overrides": [],
                "pending_suggestion": None, "last_inferred_interaction_count": None,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return await get_profile(user_id, workspace_id)


# ── Phase 3: render blok User Context untuk prompt agent ──────────────────────

def _field_label(field: str, value: Any) -> str:
    """Label manusia utk satu field manual — dipakai blok User Context."""
    if field == "verbosity":
        return {"concise": "concise", "standard": "standard", "detailed": "detailed"}.get(value, str(value))
    if field == "tone":
        return {"formal": "formal", "casual": "casual"}.get(value, str(value))
    if field == "format_preference":
        return {"list": "bullet lists", "paragraph": "paragraphs", "mixed": "mixed lists & paragraphs"}.get(value, str(value))
    if field == "default_chat_depth":
        return f"chat depth {value}/5"
    return str(value)


async def render_user_context_block(user_id: str, workspace_id: str) -> str:
    """Blok `### USER CONTEXT` utk prompt agent (Phase 3, threshold D5).

    Render HANYA bila: ≥1 manual field di-set ATAU interaction_count ≥ 10.
    Di bawah threshold → return "" (tanpa blok — 2 interaksi bukan sinyal).

    Sumber:
    - Manual fields (D3 — selalu menang): verbosity/tone/format_preference/default_chat_depth
    - Counter pasif: services_queried top-3 ("frequently monitors"),
      active_hours dominan ("typically active around").

    Exception-safe — gagal baca profil → "" (agent tetap jalan, tanpa konteks).
    """
    try:
        if not user_id or not workspace_id:
            return ""
        db = get_db()
        doc = await db[COLLECTION].find_one(
            {"user_id": str(user_id), "workspace_id": str(workspace_id)}
        )
        if not doc:
            return ""

        # Threshold D5 (plan rev.2): manual field ATAU interaksi cukup
        manual = [f for f in ("verbosity", "tone", "format_preference", "default_chat_depth")
                  if doc.get(f) is not None]
        interaction_count = int(doc.get("interaction_count") or 0)
        if not manual and interaction_count < MIN_INTERACTIONS_FOR_RENDER:
            return ""

        lines: list[str] = []
        if manual:
            pref_parts = [f"{_field_label(f, doc[f])}" for f in manual]
            lines.append(f"- Communication: {', '.join(pref_parts)}")
        # Frequently monitors — top-3 service paling sering ditanya
        svcs = (doc.get("services_queried") or {})
        if svcs:
            top_svcs = [s for s, _ in sorted(svcs.items(), key=lambda kv: kv[1], reverse=True)[:3]]
            if top_svcs:
                lines.append(f"- Frequently monitors: {', '.join(top_svcs)}")
        # Jam aktif dominan (histogram UTC 24 jam)
        hours = doc.get("active_hours") or []
        if isinstance(hours, list) and len(hours) == 24:
            peak = max(range(24), key=lambda h: hours[h] if isinstance(hours[h], (int, float)) else 0)
            if hours[peak]:
                lines.append(f"- Typically active around: {peak:02d}:00 UTC")

        if not lines:
            return ""
        return "### USER CONTEXT\n" + "\n".join(lines) + "\n"
    except Exception as e:
        logger.warning(f"[UserProfile] render_user_context_block failed (non-fatal): {e}")
        return ""
