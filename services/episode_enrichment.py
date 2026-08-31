"""
Episode Enrichment — Gap 2 Fase 4.

Dipicu saat ticket status → 'resolved'. Extract outcome data dari ticket
dan enrich episode yang terkait (TTR, resolution_actions, knowledge_refs).

Prinsip:
- Tidak pernah throw ke caller — semua error di-catch dan di-log.
- Read-only terhadap ticket. Update hanya ke episode.
- Idempotent via guard `enriched_at` — tidak enrich dua kali.
- Field `feedback` milik auto_feedback TIDAK disentuh.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

EPISODES_COLLECTION = "incident_episodes"

ENRICHMENT_VERSION = 1

# Auto-generated notes yang tidak pernah jadi resolution action
_AUTO_NOTE_PREFIXES = ("Status changed:", "Ticket reopened", "Severity changed:")

# Format knowledge_context dari knowledge_retrieval.format_knowledge_context:
#   [Score: 0.84] **nama_doc**
_KNOWLEDGE_REF_RE = re.compile(r"\[Score:.*?\]\s*\*\*(.+?)\*\*")


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


async def _find_episode_for_ticket(ticket: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Primary: ticket.episode_id. Fallback: service_name + timestamp ±30m dari createdAt."""
    db = get_db()
    coll = db[EPISODES_COLLECTION]

    ep_id = ticket.get("episode_id")
    if ep_id:
        ep = await coll.find_one({"episode_id": ep_id})
        if ep:
            logger.info(f"[Enrich] found episode via ticket.episode_id={ep_id}")
            return ep

    # Fallback: workspace + service + window waktu (±30 menit dari createdAt)
    created_at = _parse_iso(ticket.get("createdAt"))
    service_name = ticket.get("serviceName")
    workspace_id = ticket.get("workspaceId")
    if not created_at or not service_name:
        logger.info(f"[Enrich] no episode_id & no fallback anchor (ticket={ticket.get('_id')})")
        return None

    lo = created_at - timedelta(minutes=30)
    hi = created_at + timedelta(minutes=30)
    query: Dict[str, Any] = {
        "service_name": service_name,
        "timestamp": {"$gte": lo, "$lte": hi},
    }
    if workspace_id:
        query["workspace_id"] = workspace_id
    ep = await coll.find_one(query, sort=[("timestamp", -1)])
    if ep:
        logger.info(f"[Enrich] fallback match episode={ep.get('episode_id')} for service={service_name}")
    else:
        logger.info(f"[Enrich] no episode in ±30m window for service={service_name} (miss, bukan error)")
    return ep


def _compute_ttr_minutes(ticket: Dict[str, Any]) -> Optional[float]:
    created = _parse_iso(ticket.get("createdAt"))
    resolved = _parse_iso(ticket.get("resolvedAt")) or _parse_iso(ticket.get("updatedAt"))
    if not created or not resolved or resolved < created:
        return None
    return round((resolved - created).total_seconds() / 60.0, 1)


def _extract_resolution_actions(ticket: Dict[str, Any]) -> List[str]:
    """Ambil max 10 note terakhir sebelum resolvedAt, exclude auto-generated notes."""
    progress = ticket.get("progressLog") or []
    resolved_at = _parse_iso(ticket.get("resolvedAt"))
    entries: List[Tuple[datetime, str]] = []
    for entry in progress:
        note = (entry.get("note") or "").strip()
        if not note or note.startswith(_AUTO_NOTE_PREFIXES):
            continue
        at = _parse_iso(entry.get("at"))
        if resolved_at is not None and at is not None and at > resolved_at:
            continue
        entries.append((at or datetime.min.replace(tzinfo=timezone.utc), note))
    entries.sort(key=lambda x: x[0])
    return [note for _, note in entries[-10:]]


def _extract_knowledge_refs(episode: Dict[str, Any]) -> List[str]:
    """Best-effort: extract nama doc dari knowledge_context + doc_context_used. Deduplicate."""
    refs: List[str] = []
    kc = episode.get("knowledge_context") or ""
    if kc:
        refs += _KNOWLEDGE_REF_RE.findall(kc)
    dcu = episode.get("doc_context_used") or ""
    if dcu:
        refs += [line.strip("*- ") for line in dcu.splitlines() if line.strip() and len(line.strip()) < 120]
    seen = set()
    out = []
    for r in refs:
        r = r.strip()
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out[:20]


def _extract_what_confirmed(episode: Dict[str, Any]) -> Optional[str]:
    """Ringkas bukti yang mengonfirmasi root cause dari correlation_result."""
    cr = episode.get("correlation_result")
    root = episode.get("root_cause") or "unknown"
    if isinstance(cr, dict):
        parts = []
        for key in ("root_cause", "confidence", "remediation", "summary", "conclusion"):
            val = cr.get(key)
            if val is not None and str(val).strip() and str(val) != "None":
                parts.append(f"{key}={str(val)[:200]}")
        if parts:
            return f"root_cause={root}; " + "; ".join(parts[:3])
    return root if root != "unknown" else None


async def enrich_episode_from_ticket(ticket_id: str) -> bool:
    """Enrich episode terkait dengan outcome dari ticket. Tidak pernah throw."""
    try:
        db = get_db()
        ticket = await db["tickets"].find_one({"_id": ObjectId(ticket_id)})
        if not ticket:
            logger.warning(f"[Enrich] ticket {ticket_id} not found — skip")
            return False

        episode = await _find_episode_for_ticket(ticket)
        if not episode:
            logger.info(f"[Enrich] no episode found for ticket {ticket_id} — skip (bukan error)")
            return False

        if episode.get("enriched_at"):
            logger.info(f"[Enrich] episode {episode.get('episode_id')} already enriched — skip")
            return False

        update: Dict[str, Any] = {
            "actual_ttr_minutes": _compute_ttr_minutes(ticket),
            "resolution_actions": _extract_resolution_actions(ticket) or None,
            "knowledge_refs_used": _extract_knowledge_refs(episode) or None,
            "what_confirmed_it": _extract_what_confirmed(episode),
            "enriched_at": datetime.now(timezone.utc),
            "enrichment_version": ENRICHMENT_VERSION,
        }
        # partial update ok — field yang None tetap disimpan (explicit null)
        await db[EPISODES_COLLECTION].update_one(
            {"_id": episode["_id"]}, {"$set": update}
        )
        logger.info(
            f"[Enrich] enriched episode {episode.get('episode_id')} from ticket {ticket_id} "
            f"(ttr={update['actual_ttr_minutes']}, actions={len(update['resolution_actions'] or [])}, "
            f"refs={len(update['knowledge_refs_used'] or [])})"
        )
        return True
    except Exception as e:
        logger.warning(f"[Enrich] enrich_episode_from_ticket failed ticket={ticket_id}: {e}")
        return False


async def enrich_episode_from_ticket_async(ticket_id: str) -> None:
    """Fire-and-forget wrapper — jangan pernah letakkan exception di task."""
    try:
        await enrich_episode_from_ticket(ticket_id)
    except Exception as e:
        logger.warning(f"[Enrich] task crashed for ticket={ticket_id}: {e}")