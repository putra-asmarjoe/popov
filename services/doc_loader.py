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

_docs_cache: Optional[dict] = None
_docs_source: str = "none"  # "db" | "none" (folder TIDAK pernah dibaca runtime)


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


async def build_agent_context(service_id: str) -> str:
    """Bangun string konteks lengkap untuk LLM (service + connectivity + schema + observability + playbook)."""
    parts = []

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
