"""
Knowledge listing — jawab pertanyaan "dokumen/knowledge apa saja pada service X".

Deterministik (tanpa LLM): enumerate grounding docs (docs/), Learned Patterns,
knowledge library yang ter-link, dan knowledge workspace. Akurat & hemat token.

Dipicu dari supervisor saat is_knowledge_query(intent) & service terdeteksi.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_QUERY_KEYWORDS = ("dokumen", "knowledge", "pengetahuan", "grounding", "playbook", "panduan")
_ASK_KEYWORDS = ("apa", "daftar", "list", "ada", "apa saja", "yang tersedia")


def is_knowledge_query(intent: str) -> bool:
    """Deteksi pertanyaan knowledge/dokumen service (bukan insiden/aksi)."""
    low = (intent or "").lower()
    return any(k in low for k in _QUERY_KEYWORDS) and any(k in low for k in _ASK_KEYWORDS)


async def build_service_knowledge_inventory(
    service_id: str,
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    detail: bool = False,
) -> str:
    """Daftar knowledge/dokumen service — RINGKAS (list nama/type saja).

    Bila detail=True, bacakan bagian penting (meta: criticality, thresholds,
    escalation) untuk service doc. Deterministik, tanpa LLM, hemat token.
    """
    from services.doc_loader import (
        get_connection_doc,
        get_observability_doc,
        get_playbooks_for_service,
        get_schema_doc,
        get_service_doc,
    )

    lines: list[str] = []

    # 1) Grounding docs (agent_docs DB)
    svc = await get_service_doc(service_id)
    if svc:
        meta = svc.get("meta") or {}
        body = svc.get("body") or ""
        lines.append(f"• 📄 *Service doc* `{meta.get('id') or service_id}` (criticality `{meta.get('criticality', 'N/A')}`)")
        if detail:
            esc = meta.get("escalation") or {}
            thr = meta.get("thresholds") or {}
            lines.append(f"  - Collections: {meta.get('collections') or '-'}")
            lines.append(f"  - Threshold: warning `{thr.get('error_count_warning')}` / critical `{thr.get('error_count_critical')}`")
            lines.append(f"  - Eskalasi: primary `{esc.get('primary', '-')}` · slack `{esc.get('slack_channel', '-')}`")
            lines.append(f"  - Auto-remediation: {', '.join(meta.get('auto_remediation_allowed') or []) or '-'}")
        if "## Learned Patterns" in body:
            lines.append("  - ➕ Berisi *Learned Patterns* (auto-generated)")

    conn = await get_connection_doc(service_id)
    if conn:
        lines.append(f"• 🔗 *Connection doc* `{conn.get('meta', {}).get('id') or service_id}`")

    primary_collection = (svc.get("meta") or {}).get("collections", {}).get("primary") if svc else None
    if primary_collection:
        schema = await get_schema_doc(primary_collection)
        if schema:
            lines.append(f"• 🗄️ *Schema doc* `{schema.get('meta', {}).get('collection') or primary_collection}`")

    obs = await get_observability_doc(service_id)
    if obs:
        lines.append(f"• 📊 *Observability doc* `{obs.get('meta', {}).get('id') or service_id}`")

    playbooks = await get_playbooks_for_service(service_id)
    if playbooks:
        names = ", ".join(
            (p.get("meta") or {}).get("id") or (p.get("meta") or {}).get("title") or "?"
            for p in playbooks
        )
        lines.append(f"• 📖 *Playbooks* ({len(playbooks)}): {names}")

    # 2) Knowledge library ter-link (via service_library → service_knowledge_refs)
    linked = await _linked_knowledge_list(service_id, project_id)
    if linked:
        lines.append("")
        lines.append("🔗 *Knowledge Library (ter-link):*")
        for k in linked:
            lines.append(f"  - {k['folder']} / `{k['name']}`")
    elif project_id:
        lines.append("\n🔗 *Knowledge Library:* (belum ada knowledge ter-link di project ini)")

    if not lines:
        return f"ℹ️ Tidak ada knowledge/dokumen terdaftar untuk service `{service_id}`."

    header = f"📚 *Knowledge & Dokumen Service `{service_id}`*\n"
    body = "\n".join(lines)
    hint = (
        "\n\n_Untuk isi lengkap setiap dokumen, silakan lihat halaman "
        "*Workspace → Settings → Services → Knowledge*._"
    )
    return header + body + hint


async def _linked_knowledge_list(service_id: str, project_id: Optional[str] = None) -> list[dict]:
    """Daftar knowledge_library ter-link ke service (folder + name saja).

    Bila project_id ada → HANYA library item yang ter-link ke project
    (project_service_refs) — menghindari item duplikat/test milik library lain.
    """
    try:
        from bson import ObjectId
        from services.mongodb_client import get_db

        db = get_db()
        libs = await db["service_library"].find({"serviceId": service_id}, {"_id": 1}).to_list(50)

        # filter ke item yang ter-link project (jika ada konteks project)
        if project_id:
            refs = await db["project_service_refs"].find(
                {"projectId": project_id}, {"libraryServiceId": 1}
            ).to_list(200)
            linked_ids = {str(r["libraryServiceId"]) for r in refs}
            libs = [l for l in libs if str(l["_id"]) in linked_ids]
            if not libs:
                # tidak ada library item ter-link → tidak ada knowledge project
                return []

        lib_ids = [str(x["_id"]) for x in libs]
        if not lib_ids:
            return []
        refs = await db["service_knowledge_refs"].find(
            {"serviceLibraryId": {"$in": lib_ids}}, {"knowledgeLibraryId": 1}
        ).to_list(100)
        oids = [ObjectId(r["knowledgeLibraryId"]) for r in refs if ObjectId.is_valid(str(r["knowledgeLibraryId"]))]
        if not oids:
            return []
        kbs = await db["knowledge_library"].find(
            {"_id": {"$in": oids}}, {"name": 1, "folder": 1}
        ).to_list(len(oids))
        seen = set()
        out = []
        for k in kbs:
            key = (k.get("folder", "?"), k.get("name", "?"))
            if key not in seen:
                seen.add(key)
                out.append({"folder": key[0], "name": key[1]})
        return out
    except Exception as e:
        logger.warning(f"[KnowledgeListing] linked list gagal: {e}")
        return []