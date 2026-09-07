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


_L = {
    "id": {
        "no_connections": "ℹ️ Tidak ada dokumen *connections* untuk service `{svc}` di Knowledge Library.",
        "from_ticket": "🧩 Dari alert tiket, `{svc}` terhubung dengan: {others}",
        "missing_docs": "   _Belum ada connection doc utk: {list}_",
        "no_conn_detail": "ℹ️ Tidak ada detail koneksi untuk service ini (hubungkan service → tambah Knowledge).",
        "escalation_line": "  - Eskalasi: primary `{p}` · slack `{slack}`",
        "learned_line": "  - ➕ Berisi *Learned Patterns* (auto-generated)",
        "no_linked": "\n🔗 *Knowledge Library:* (belum ada knowledge ter-link di project ini)",
        "no_docs": "ℹ️ Tidak ada knowledge/dokumen terdaftar untuk service `{svc}`.",
        "hint": "\n\n_Untuk isi lengkap setiap dokumen, silakan lihat halaman *Workspace → Settings → Services → Knowledge*._",
        "proj_none": "📚 *Knowledge Project*\nBelum ada service ter-link pada project ini, jadi belum ada knowledge.\n_Link service lewat Workspace → Settings → Projects._",
        "proj_empty": "Belum ada grounding docs maupun knowledge ter-link.",
        "hint_marker": "\n\n_Untuk isi lengkap",
    },
    "en": {
        "no_connections": "ℹ️ No *connections* document for service `{svc}` in the Knowledge Library.",
        "from_ticket": "🧩 From the ticket alert, `{svc}` is connected to: {others}",
        "missing_docs": "   _No connection doc yet for: {list}_",
        "no_conn_detail": "ℹ️ No connection details for this service (link the service → add Knowledge).",
        "escalation_line": "  - Escalation: primary `{p}` · slack `{slack}`",
        "learned_line": "  - ➕ Contains *Learned Patterns* (auto-generated)",
        "no_linked": "\n🔗 *Knowledge Library:* (no knowledge linked in this project yet)",
        "no_docs": "ℹ️ No knowledge/documents registered for service `{svc}`.",
        "hint": "\n\n_For the full content of each document, see *Workspace → Settings → Services → Knowledge*._",
        "proj_none": "📚 *Project Knowledge*\nNo service is linked to this project yet, so there is no knowledge.\n_Link services via Workspace → Settings → Projects._",
        "proj_empty": "No grounding docs or linked knowledge yet.",
        "hint_marker": "\n\n_For the full content",
    },
}


def is_knowledge_query(intent: str) -> bool:
    """Deteksi pertanyaan knowledge/dokumen service (bukan insiden/aksi)."""
    low = (intent or "").lower()
    return any(k in low for k in _QUERY_KEYWORDS) and any(k in low for k in _ASK_KEYWORDS)


# Fix #199: pertanyaan "X terhubung dengan service apa saja" / connections service.
# Kata kerja koneksi TIDAK termasuk "koneksi" agar "apakah ini koneksi atau error code?"
# tidak salah-route (itu klasifikasi insiden, bukan daftar connection).
_CONNECTION_VERBS = (
    "terhubung", "tersambung", "connect", "connection",
    "upstream", "downstream", "relasi service", "dependensi",
)
_CONNECTION_ASKS = (
    "service", "apa saja", "apa aja", "list", "dengan apa", "ke mana",
    "with what", "to what", "dependencies", "services",
)


def is_connection_query(intent: str) -> bool:
    """Deteksi pertanyaan daftar service yang terhubung (connection doc service)."""
    low = (intent or "").lower()
    if not any(v in low for v in _CONNECTION_VERBS):
        return False
    return any(a in low for a in _CONNECTION_ASKS)


def _render_connection_sections(content: str) -> str:
    """Render bagian upstream/downstream/third_party dari doc connections → bullet.
    Format doc: `key: value  key: value` per baris; token pertama = service peer."""
    out: list[str] = []
    current: Optional[str] = None
    for raw in (content or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in ("upstream:", "downstream:", "third_party:", "resilience:"):
            current = line.rstrip(":")
            out.append(f"*{current.title()}:*")
            continue
        if current in ("upstream", "downstream", "third_party") and line:
            parts = line.split()
            peer = parts[0] if parts else "?"
            endpoint = impact = ""
            for tok in parts[1:]:
                if tok.startswith("endpoint:"):
                    endpoint = tok[len("endpoint:"):]
                elif tok.startswith("impact_if_down:"):
                    impact = tok[len("impact_if_down:"):]
            row = f"  • `{peer}`"
            if endpoint:
                row += f" · `{endpoint}`"
            if impact:
                row += f" — {impact}"
            out.append(row)
    return "\n".join(out) if out else (content or "")[:1500]


def _services_involved(ticket_context: Optional[dict]) -> list[str]:
    """Parsing "Services involved: a, b, c" dari description tiket (alert watchdog)."""
    import re
    desc = (ticket_context or {}).get("description") or ""
    m = re.search(r"[Ss]ervices\s+involved:\s*(.+)", desc)
    if not m:
        return []
    raw = m.group(1).splitlines()[0].strip().rstrip(".,;")
    items = [s.strip().strip("*`.") for s in raw.split(",") if s.strip()]
    return [i for i in items if i and not i.startswith("⚠")]


async def _connection_doc_from_library(service_id: str) -> Optional[dict]:
    """Doc connections di knowledge_library (folder='connections').
    Match service_id (hyphen/underscore) → nama doc `{svc}_connections`."""
    import re
    from services.mongodb_client import get_db
    try:
        db = get_db()
        norm = service_id.replace("-", "_")
        cands = [f"{norm}_connections", norm, f"{service_id}_connections"]
        doc = await db["knowledge_library"].find_one(
            {"folder": "connections", "name": {"$in": cands}}
        )
        if doc:
            return doc
        # fallback: prefix normalize
        return await db["knowledge_library"].find_one(
            {"folder": "connections", "name": {"$regex": f"^{re.escape(norm)}(_connections)?$"}}
        )
    except Exception as e:
        logger.warning(f"[KnowledgeListing] connection doc lookup gagal: {e}")
        return None


async def build_service_connection_inventory(
    service_id: str,
    ticket_context: Optional[dict] = None,
    locale: str = "id",
) -> str:
    """Jawab "X terhubung dengan service apa saja" — deterministik, tanpa LLM.

    Sumber (prioritas):
    1. Connection doc service di knowledge library (upstream/downstream/third_party).
    2. Fallback: service yang terlibat dari alert tiket ("Services involved: ...").
    Sebelum Fix #199 pertanyaan ini ditolak supervisor sbg out-of-konteks.
    """
    t = _L.get(locale, _L["en"])
    svc = (service_id or "").strip()
    lines: list[str] = []
    doc = await _connection_doc_from_library(svc) if svc else None
    if doc:
        lines.append(f"🔗 *Connection `{doc.get('name') or svc}`*")
        lines.append(_render_connection_sections(doc.get("content") or ""))
    else:
        lines.append(t["no_connections"].format(svc=svc))

    involved = _services_involved(ticket_context)
    if involved:
        others = [x for x in involved if x != svc]
        if others:
            lines.append("")
            lines.append(t["from_ticket"].format(svc=svc, others=", ".join(f"`{x}`" for x in others)))
            missing = []
            for x in involved:
                if not await _connection_doc_from_library(x):
                    missing.append(x)
            if missing:
                lines.append(
                    t["missing_docs"].format(list=", ".join(f"`{x}`" for x in missing))
                )
    elif not doc:
        lines.append("")
        lines.append(t["no_conn_detail"])

    if len(lines) == 1:
        return lines[0]
    return "\n".join(lines)


async def build_service_knowledge_inventory(
    service_id: str,
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    detail: bool = False,
    locale: str = "id",
) -> str:
    """Daftar knowledge/dokumen service — RINGKAS (list nama/type saja).

    Bila detail=True, bacakan bagian penting (meta: criticality, thresholds,
    escalation) untuk service doc. Deterministik, tanpa LLM, hemat token.

    Workspace-scoped: jika workspace_id diberikan, HANYA tampilkan grounding docs
    yang linked ke workspace via agent_doc_refs.
    """
    t = _L.get(locale, _L["en"])
    lines: list[str] = []

    if workspace_id:
        # Workspace-scoped: gunakan linked docs saja
        from services.doc_loader import get_linked_docs_for_workspace, _doc_matches_service
        linked_docs = await get_linked_docs_for_workspace(workspace_id)

        svc = None
        conn = None
        schema = None
        obs = None
        playbooks = []

        for cat_key, doc in linked_docs.items():
            category = cat_key.split("/")[0]
            if not _doc_matches_service(doc, service_id):
                continue
            if category == "services" and not svc:
                svc = doc
            elif category == "connections" and not conn:
                conn = doc
            elif category == "schemas" and not schema:
                primary = (svc or {}).get("meta", {}).get("collections", {}).get("primary")
                if primary and doc.get("meta", {}).get("collection") == primary:
                    schema = doc
            elif category == "observability" and not obs:
                obs = doc
            elif category == "playbooks":
                playbooks.append(doc)

        if svc:
            meta = svc.get("meta") or {}
            body = svc.get("body") or ""
            lines.append(f"• 📄 *Service doc* `{meta.get('id') or service_id}` (criticality `{meta.get('criticality', 'N/A')}`)")
            if detail:
                esc = meta.get("escalation") or {}
                thr = meta.get("thresholds") or {}
                lines.append(f"  - Collections: {meta.get('collections') or '-'}")
                lines.append(f"  - Threshold: warning `{thr.get('error_count_warning')}` / critical `{thr.get('error_count_critical')}`")
                lines.append(t["escalation_line"].format(p=esc.get('primary', '-'), slack=esc.get('slack_channel', '-')))
                lines.append(f"  - Auto-remediation: {', '.join(meta.get('auto_remediation_allowed') or []) or '-'}")
            if "## Learned Patterns" in body:
                lines.append(t["learned_line"])

        if conn:
            lines.append(f"• 🔗 *Connection doc* `{conn.get('meta', {}).get('id') or service_id}`")

        if schema:
            lines.append(f"• 🗄️ *Schema doc* `{schema.get('meta', {}).get('collection') or service_id}`")

        if obs:
            lines.append(f"• 📊 *Observability doc* `{obs.get('meta', {}).get('id') or service_id}`")

        if playbooks:
            names = ", ".join(
                (p.get("meta") or {}).get("id") or (p.get("meta") or {}).get("title") or "?"
                for p in playbooks
            )
            lines.append(f"• 📖 *Playbooks* ({len(playbooks)}): {names}")
    else:
        # Global fallback (backward compatibility)
        from services.doc_loader import (
            get_connection_doc,
            get_observability_doc,
            get_playbooks_for_service,
            get_schema_doc,
            get_service_doc,
        )

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
                lines.append(t["escalation_line"].format(p=esc.get('primary', '-'), slack=esc.get('slack_channel', '-')))
                lines.append(f"  - Auto-remediation: {', '.join(meta.get('auto_remediation_allowed') or []) or '-'}")
            if "## Learned Patterns" in body:
                lines.append(t["learned_line"])

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
        lines.append(t["no_linked"])

    if not lines:
        return t["no_docs"].format(svc=service_id)

    header = f"📚 *Knowledge & Documents — Service `{service_id}`*\n"
    body = "\n".join(lines)
    return header + body + t["hint"]


async def _linked_knowledge_list(service_id: str, project_id: Optional[str] = None) -> list[dict]:
    """Daftar knowledge_library ter-link ke service (folder + name saja).

    Bila project_id ada → HANYA library item yang ter-link ke project
    (project_service_refs) — menghindari item duplikat/test milik library lain.
    """
    try:
        from bson import ObjectId
        from services.mongodb_client import get_db

        db = get_db()
        # Normalize: serviceId di DB pakai underscore, service_name dari ticket pakai hyphen
        norm_service_id = service_id.replace("-", "_")
        libs = await db["service_library"].find(
            {"serviceId": {"$in": [service_id, norm_service_id]}}, {"_id": 1}
        ).to_list(50)

        # filter ke item yang ter-link project (jika ada konteks project)
        if project_id:
            refs = await db["project_service_refs"].find(
                {"projectId": project_id}, {"libraryServiceId": 1}
            ).to_list(200)
            linked_ids = {str(r["libraryServiceId"]) for r in refs}
            libs = [lib for lib in libs if str(lib["_id"]) in linked_ids]
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


async def build_project_knowledge_inventory(
    project_id: str, workspace_id: Optional[str] = None, locale: str = "id"
) -> str:
    """Daftar knowledge seluruh service ter-link project (Chat by Project fase 1).
    Deterministik, tanpa LLM: per service — grounding docs + knowledge library ter-link."""
    try:
        from services.service_store import list_refs_for_project

        refs = await list_refs_for_project(project_id)
        service_ids = sorted({r.get("serviceId", "") for r in refs if r.get("serviceId")})
    except Exception as e:
        logger.warning(f"[KnowledgeListing] project refs gagal: {e}")
        service_ids = []

    t = _L.get(locale, _L["en"])
    if not service_ids:
        return t["proj_none"]

    header = f"📚 *Knowledge Project* ({len(service_ids)} service)\n"
    body_parts: list[str] = []
    total_items = 0
    for sid in service_ids:
        inv = await build_service_knowledge_inventory(sid, workspace_id, project_id, detail=False)
        # strip hint footer per-service (cukup sekali di akhir)
        inv_clean = inv.split("\n\n_")[0]  # strip hint footer (locale-agnostic)
        body_parts.append(f"\n*{sid}*\n{inv_clean}")
        total_items += inv_clean.count("•") + inv_clean.count("  - ")
    if total_items == 0:
        return header + "\n" + t["proj_empty"]
    return header + "".join(body_parts) + t["hint"]