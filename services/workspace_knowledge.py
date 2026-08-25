"""
Workspace knowledge context — FE-7.
Menyusun konteks markdown dari referensi workspace → library (link, tanpa salinan).
Dipakai knowledge_agent untuk inject ke prompt correlation. Cache TTL 30s per
workspace; invalidate saat ada mutasi (add/remove ref / delete item).
"""
import logging
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Tuple[float, str]] = {}
CACHE_TTL_S = 30.0
MAX_ITEM_CHARS = 2000
MAX_TOTAL_CHARS = 8000


def invalidate_cache(workspace_id: Optional[str] = None) -> None:
    """Panggil setelah mutasi refs/library agar agent langsung baca versi baru."""
    if workspace_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(workspace_id, None)


async def build_workspace_context(workspace_id: Optional[str]) -> str:
    """Return seksi markdown '## Knowledge Workspace' atau '' bila kosong/error."""
    if not workspace_id:
        return ""
    now = time.monotonic()
    cached = _CACHE.get(workspace_id)
    if cached and now - cached[0] < CACHE_TTL_S:
        return cached[1]

    text = ""
    try:
        from services.knowledge_store import list_refs_for_workspace
        from services.mongodb_client import get_db

        refs = await list_refs_for_workspace(workspace_id)
        if refs:
            db = get_db()
            try:
                oid = __import__("bson").ObjectId(workspace_id)
                ws = await db["workspaces"].find_one({"_id": oid}, {"name": 1})
            except Exception:
                ws = None
            ws_name = (ws or {}).get("name", workspace_id)

            parts = [f"## Knowledge Workspace '{ws_name}'", ""]
            total = 0
            for ref in refs[:10]:
                detail = await _item_content(ref["libraryId"])
                if not detail:
                    continue
                body = detail[:MAX_ITEM_CHARS]
                parts.append(f"### {ref['name']} ({ref['folder']})")
                parts.append(body)
                parts.append("")
                total += len(body)
                if total >= MAX_TOTAL_CHARS:
                    parts.append("_(…knowledge lain dipotong demi token budget)_")
                    break
            text = "\n".join(parts).strip()
    except Exception as e:
        logger.warning(f"[KnowledgeWS] build context failed ws={workspace_id}: {e}")
        text = ""

    _CACHE[workspace_id] = (now, text)
    return text


async def _item_content(library_id: str) -> str:
    from services.knowledge_store import get_item
    item = await get_item(library_id)
    return (item or {}).get("content", "").strip()
