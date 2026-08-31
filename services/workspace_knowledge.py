"""
Workspace knowledge context — FE-7.
Menyusun konteks markdown dari:
1. Knowledge spesifik workspace (workspace_knowledge collection)
2. Referensi workspace → library (link, tanpa salinan)
3. Grounding docs dari Management (reference via agent_doc_refs, read-only)
Dipakai knowledge_agent untuk inject ke prompt correlation. Cache TTL 30s per
workspace; invalidate saat ada mutasi (add/remove ref / delete item).
"""
import logging
import time
from typing import Dict, Optional, Tuple

from config.settings import settings

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Tuple[float, str]] = {}
CACHE_TTL_S = 30.0
MAX_ITEM_CHARS = settings.knowledge_max_item_chars
MAX_TOTAL_CHARS = settings.knowledge_max_total_chars


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
        from services.knowledge_store import list_refs_for_workspace, list_workspace_items
        from services.mongodb_client import get_db

        parts = []
        total = 0

        # 1) Knowledge spesifik workspace (CRUD di workspace settings)
        ws_items = await list_workspace_items(workspace_id)
        if ws_items:
            try:
                db = get_db()
                oid = __import__("bson").ObjectId(workspace_id)
                ws = await db["workspaces"].find_one({"_id": oid}, {"name": 1})
            except Exception:
                ws = None
            ws_name = (ws or {}).get("name", workspace_id)
            parts.append(f"## Knowledge Workspace '{ws_name}' (Spesifik)")
            parts.append("")
            for item in ws_items[:10]:
                detail = await _workspace_item_content(item["id"])
                if not detail:
                    continue
                body = detail[:MAX_ITEM_CHARS]
                parts.append(f"### {item['name']} ({item['folder']})")
                parts.append(body)
                parts.append("")
                total += len(body)
                if total >= MAX_TOTAL_CHARS:
                    parts.append("_(…knowledge lain dipotong demi token budget)_")
                    break

        # 2) Referensi dari Management library (link manual)
        refs = await list_refs_for_workspace(workspace_id)
        if refs:
            if not parts:
                try:
                    db = get_db()
                    oid = __import__("bson").ObjectId(workspace_id)
                    ws = await db["workspaces"].find_one({"_id": oid}, {"name": 1})
                except Exception:
                    ws = None
                ws_name = (ws or {}).get("name", workspace_id)
                parts.append(f"## Knowledge Workspace '{ws_name}' (Linked)")
                parts.append("")
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

        # 3) Grounding docs dari Management (reference via agent_doc_refs, read-only)
        try:
            from services.agent_doc_refs_store import list_refs_as_keys
            from services.agent_docs_store import get_doc as get_agent_doc
            doc_refs = await list_refs_as_keys(workspace_id)
            if doc_refs:
                if not parts:
                    try:
                        db = get_db()
                        oid = __import__("bson").ObjectId(workspace_id)
                        ws = await db["workspaces"].find_one({"_id": oid}, {"name": 1})
                    except Exception:
                        ws = None
                    ws_name = (ws or {}).get("name", workspace_id)
                    parts.append(f"## Knowledge Workspace '{ws_name}' (Grounding Docs)")
                    parts.append("")
                parts.append("### Grounding Documents (from Management)")
                parts.append("")
                for dref in doc_refs[:15]:
                    doc = await get_agent_doc(dref["docCategory"], dref["docKey"])
                    if not doc:
                        continue
                    body = (doc.get("body") or "")[:MAX_ITEM_CHARS]
                    parts.append(f"### [{doc['category']}] {doc['key']}")
                    parts.append(body)
                    parts.append("")
                    total += len(body)
                    if total >= MAX_TOTAL_CHARS:
                        parts.append("_(…knowledge lain dipotong demi token budget)_")
                        break
        except Exception as e:
            logger.warning(f"[KnowledgeWS] agent_doc_refs section failed ws={workspace_id}: {e}")

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


async def _workspace_item_content(item_id: str) -> str:
    from services.knowledge_store import get_workspace_item
    item = await get_workspace_item(item_id)
    return (item or {}).get("content", "").strip()
