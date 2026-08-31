"""
Document loader untuk menyediakan konteks AI agent.

Sumber SATU-SATUNYA: DB (collection `agent_docs`, via agent_docs_store) — editable via UI.
TIDAK ada fallback ke folder `docs/` (Fix: knowledge murni UI-DB).

Semua fungsi ASYNC (DB adalah Motor async). Cache in-memory; `reload_docs()` invalidate.
Semua pemanggil wajib `await`.
"""
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# DOCS_ROOT & CATEGORIES dipertahankan utk scripts import (bukan pembacaan runtime).
DOCS_ROOT = Path(__file__).parent.parent / "docs"
CATEGORIES = ["services", "playbooks", "schemas", "connections", "observability", "general"]

_docs_cache = None  # type: Optional[dict]
_docs_source = "none"  # "db" | "none" (folder TIDAK pernah dibaca runtime)


def _split_frontmatter(text: str):
    """Parser YAML frontmatter — dipakai scripts import (bukan pembacaan runtime)."""
    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    match = pattern.match(text)
    if not match:
        return {}, text
    try:
        import yaml
        meta = yaml.safe_load(match.group(1)) or {}
    except Exception:
        meta = {}
    body = text[match.end():]
    return meta, body


async def _load_from_db() -> dict:
    from services.agent_docs_store import load_all_docs_db
    return await load_all_docs_db()


async def load_all_docs() -> dict:
    """DB-only (agent_docs). TANPA fallback folder. Cache + reload_docs() invalidate."""
    global _docs_cache, _docs_source
    if _docs_cache is not None:
        return _docs_cache
    try:
        _docs_cache = await _load_from_db()
        _docs_source = "db"
    except Exception as e:
        logger.error(f"[DocLoader] DB docs load FAILED (tanpa fallback folder): {e}")
        _docs_cache = {}
        _docs_source = "none"
    return _docs_cache


async def reload_docs() -> dict:
    """Invalidate cache lalu reload dari DB (satu-satunya sumber)."""
    global _docs_cache
    _docs_cache = None
    try:
        from services.agent_docs_store import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
    return await load_all_docs()


async def docs_source() -> str:
    """'db' bila membaca dari DB, 'none' bila DB gagal. Folder TIDAK pernah dipakai."""
    await load_all_docs()
    return _docs_source


# ── Accessor (semua async) ────────────────────────────────────────────────────

async def list_all_services() -> Dict[str, str]:
    """service_id -> collection_name dari dokumen service (DB atau file)."""
    docs = await load_all_docs()
    services_map = {}
    for key, doc in docs.get("services", {}).items():
        meta = doc.get("meta", {})
        service_id = meta.get("id") or key
        collection = meta.get("collections", {}).get("primary") or f"logs_{service_id}"
        services_map[service_id] = collection
    return services_map


async def get_service_doc(service_id: str) -> Optional[dict]:
    docs = await load_all_docs()
    for key, doc in docs.get("services", {}).items():
        if doc["meta"].get("id") == service_id or key == service_id:
            return doc
    return None


async def get_connection_doc(service_id: str) -> Optional[dict]:
    docs = await load_all_docs()
    for key, doc in docs.get("connections", {}).items():
        doc_service = doc["meta"].get("service_id") or doc["meta"].get("id")
        if doc_service == service_id or service_id in key or key.startswith(service_id):
            return doc
    return None


async def get_playbook(playbook_id: str) -> Optional[dict]:
    docs = await load_all_docs()
    for key, doc in docs.get("playbooks", {}).items():
        if doc["meta"].get("id") == playbook_id or key == playbook_id:
            return doc
    return None


async def get_playbooks_for_service(service_id: str) -> list:
    docs = await load_all_docs()
    playbooks = []
    for key, doc in docs.get("playbooks", {}).items():
        meta = doc.get("meta", {})
        applies = meta.get("applies_to_services") or []
        if service_id in applies or key.startswith(service_id) or service_id in key:
            playbooks.append(doc)
    return playbooks


async def get_schema_doc(collection_name: str) -> Optional[dict]:
    docs = await load_all_docs()
    for key, doc in docs.get("schemas", {}).items():
        if doc["meta"].get("collection") == collection_name or key == collection_name:
            return doc
    return None


async def get_observability_doc(service_id: str) -> Optional[dict]:
    docs = await load_all_docs()
    for key, doc in docs.get("observability", {}).items():
        doc_service = doc["meta"].get("service_id") or doc["meta"].get("id")
        if doc_service == service_id or key.startswith(service_id) or service_id in key:
            return doc
    return None


async def get_linked_docs_for_workspace(workspace_id: str) -> Dict[str, Any]:
    """Ambil semua agent_docs yang linked ke workspace via agent_doc_refs.

    Return dict {category_key: doc} — digunakan untuk filtering workspace-scoped.
    category_key format: "{category}/{key}".
    """
    from services.agent_doc_refs_store import list_refs_as_keys
    from services.agent_docs_store import get_doc

    refs = await list_refs_as_keys(workspace_id)
    if not refs:
        return {}

    linked = {}
    for ref in refs:
        cat = ref.get("docCategory", "")
        key = ref.get("docKey", "")
        doc = await get_doc(cat, key)
        if doc:
            linked[f"{cat}/{key}"] = doc
    return linked


def _doc_matches_service(doc: dict, service_id: str) -> bool:
    """Cek apakah doc cocok dengan service_id (logic yang sama dengan getters global)."""
    meta = doc.get("meta") or {}
    key = doc.get("key", "")
    doc_service = meta.get("service_id") or meta.get("id")
    return (
        doc_service == service_id
        or key == service_id
        or key.startswith(service_id)
        or service_id in key
    )


async def build_agent_context(service_id: str, workspace_id: Optional[str] = None) -> str:
    """Bangun string konteks lengkap untuk LLM (service + connectivity + schema + observability + playbook).

    Workspace-scoped: jika workspace_id diberikan, HANYA gunakan agent_docs
    yang linked ke workspace via agent_doc_refs (linked-only, tanpa fallback global).
    Jika workspace_id None, gunakan semua docs (backward compatibility).
    """
    parts = []

    if workspace_id:
        # Workspace-scoped: hanya linked docs
        linked = await get_linked_docs_for_workspace(workspace_id)
        if not linked:
            logger.info(f"[DocLoader] No linked docs for workspace={workspace_id}, context empty")
            return ""

        # Filter linked docs yang match service_id
        svc = None
        conn = None
        schema = None
        obs = None
        playbooks = []

        for cat_key, doc in linked.items():
            category = cat_key.split("/")[0]
            if not _doc_matches_service(doc, service_id):
                continue
            if category == "services" and not svc:
                svc = doc
            elif category == "connections" and not conn:
                conn = doc
            elif category == "schemas" and not schema:
                # Schema match by collection name
                primary = (svc or {}).get("meta", {}).get("collections", {}).get("primary")
                if primary and doc.get("meta", {}).get("collection") == primary:
                    schema = doc
            elif category == "observability" and not obs:
                obs = doc
            elif category == "playbooks":
                playbooks.append(doc)

        # Build context dari filtered docs
        if svc:
            meta = svc.get("meta") or {}
            parts.append("## Informasi Service")
            parts.append(f"**Criticality:** {meta.get('criticality', 'unknown')}")
            parts.append(f"**Owner team:** {meta.get('owner_team', 'unknown')}")
            esc = meta.get('escalation', {})
            parts.append(f"**Eskalasi primary:** {esc.get('primary', '-')}")
            parts.append(f"**Slack channel:** {esc.get('slack_channel', '-')}")
            thresholds = meta.get('thresholds', {})
            parts.append(f"**Threshold warning:** {thresholds.get('error_count_warning')} error")
            parts.append(f"**Threshold critical:** {thresholds.get('error_count_critical')} error")
            auto_ok = meta.get('auto_remediation_allowed', [])
            needs_approval = meta.get('requires_human_approval', [])
            parts.append(f"**Auto-remediation diizinkan:** {', '.join(auto_ok) or 'tidak ada'}")
            parts.append(f"**Perlu approval manusia:** {', '.join(needs_approval)}")
            parts.append("")
            parts.append(svc.get('body', ''))

        if conn:
            parts.append("\n---\n## Arsitektur Konektivitas & Dependencies")
            parts.append(conn.get('body', ''))

        if schema:
            parts.append("\n---\n## Struktur Data (Schema)")
            parts.append(schema.get('body', ''))

        if obs:
            parts.append("\n---\n## Observability (PromQL & OTel)")
            parts.append(obs.get('body', ''))

        if not playbooks:
            # Fallback: coba generic playbook jika ada di linked docs
            for cat_key, doc in linked.items():
                if doc.get("key") == "high_error_rate":
                    playbooks = [doc]
                    break

        for i, playbook in enumerate(playbooks, 1):
            parts.append(f"\n---\n## Panduan Respons (Playbook {i})")
            parts.append(playbook.get('body', ''))

    else:
        # Global fallback (backward compatibility)
        svc = await get_service_doc(service_id)
        if svc:
            parts.append("## Informasi Service")
            parts.append(f"**Criticality:** {svc['meta'].get('criticality', 'unknown')}")
            parts.append(f"**Owner team:** {svc['meta'].get('owner_team', 'unknown')}")
            esc = svc['meta'].get('escalation', {})
            parts.append(f"**Eskalasi primary:** {esc.get('primary', '-')}")
            parts.append(f"**Slack channel:** {esc.get('slack_channel', '-')}")
            thresholds = svc['meta'].get('thresholds', {})
            parts.append(f"**Threshold warning:** {thresholds.get('error_count_warning')} error")
            parts.append(f"**Threshold critical:** {thresholds.get('error_count_critical')} error")
            auto_ok = svc['meta'].get('auto_remediation_allowed', [])
            needs_approval = svc['meta'].get('requires_human_approval', [])
            parts.append(f"**Auto-remediation diizinkan:** {', '.join(auto_ok) or 'tidak ada'}")
            parts.append(f"**Perlu approval manusia:** {', '.join(needs_approval)}")
            parts.append("")
            parts.append(svc['body'])

        conn = await get_connection_doc(service_id)
        if conn:
            parts.append("\n---\n## Arsitektur Konektivitas & Dependencies")
            parts.append(conn['body'])

        if svc:
            primary_collection = svc['meta'].get('collections', {}).get('primary')
            if primary_collection:
                schema = await get_schema_doc(primary_collection)
                if schema:
                    parts.append("\n---\n## Struktur Data (Schema)")
                    parts.append(schema['body'])

        obs = await get_observability_doc(service_id)
        if obs:
            parts.append("\n---\n## Observability (PromQL & OTel)")
            parts.append(obs['body'])

        playbooks = await get_playbooks_for_service(service_id)
        if not playbooks:
            generic = await get_playbook("high_error_rate")
            if generic:
                playbooks = [generic]
        for i, playbook in enumerate(playbooks, 1):
            parts.append(f"\n---\n## Panduan Respons (Playbook {i})")
            parts.append(playbook['body'])

    return "\n".join(parts)
