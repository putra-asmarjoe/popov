"""
Knowledge Agent — FE-7.
Node pipeline TANPA LLM: menyatukan dua sumber knowledge kontekstual menjadi
satu blok `knowledge_context` untuk correlation_agent:

1. Knowledge Universal (bawaan backend/repo — diubah via git, bukan UI):
   playbook infra umum (oom_killed, pod crash, dll) yang dicocokkan KEYWORD dari
   intent + hypothesis + nama alert. Playbook service-specific TIDAK diduplikasi
   di sini (sudah masuk grounding doc correlation via build_agent_context).
2. Knowledge Workspace (FE-7): referensi library milik workspace bila
   `workspace_id` tersedia (jalur chat/tiket web).

Fan-in dari fan-out observability → knowledge_agent → correlation_agent.
"""
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

STOPWORDS = {
    "pada", "dengan", "yang", "untuk", "error", "masalah", "kenapa", "mengapa",
    "tolong", "cek", "lihat", "ada", "apakah", "terakhir",
    # Fix #40: tanpa kata brand di stopwords — backend netral; nama brand/deployment
    # milik workspace boleh jadi token playbook matching.
    "service", "agent", "data", "bantu", "beri", "berapa", "status", "sekarang",
    "this", "that", "with", "from", "have", "has", "the", "and", "not", "what",
}
MAX_PLAYBOOKS = 3
MAX_PLAYBOOK_CHARS = 1200
MIN_TOKEN_LEN = 4


def _extract_tokens(state: Dict[str, Any]) -> List[str]:
    texts = [state.get("intent") or "", state.get("message_raw") or ""]
    hyp = (state.get("triage_result") or {}).get("hypothesis")
    if hyp:
        texts.append(str(hyp).replace("_", " "))
    # nama alert watchdog ikut dalam intent/message_raw — cukup dari situ
    blob = " ".join(texts).lower()
    tokens = set(re.findall(r"[a-z][a-z_\-]{%d,}" % (MIN_TOKEN_LEN - 1), blob))
    return sorted(t.strip("_-") for t in tokens if t not in STOPWORDS)


async def _match_universal_playbooks(tokens: List[str], service_name: str) -> List[Dict[str, str]]:
    """Cocokkan token ke docs/playbooks/*.md (universal), skip yang service-specific."""
    try:
        from services.doc_loader import load_all_docs
        docs = await load_all_docs()
    except Exception as e:
        logger.warning(f"[KnowledgeAgent] load_all_docs failed: {e}")
        return []

    matches = []
    seen_tokens: Dict[str, set] = {}
    for key, doc in docs.get("playbooks", {}).items():
        if service_name and service_name in key:
            continue  # service-specific → sudah di grounding doc correlation
        meta_blob = str(doc.get("meta", {})).lower()
        body_head = (doc.get("body") or "")[:MAX_PLAYBOOK_CHARS].lower()
        haystack = f"{key} {meta_blob} {body_head}"
        hits = [t for t in tokens if t in haystack]
        if hits:
            matches.append({
                "id": key,
                "hits": ",".join(hits[:5]),
                "body": (doc.get("body") or "").strip()[:MAX_PLAYBOOK_CHARS],
            })
            seen_tokens[key] = set(hits)

    # prioritas playbook dengan keyword terbanyak
    matches.sort(key=lambda m: -len(seen_tokens[m["id"]]))
    return matches[:MAX_PLAYBOOKS]


async def knowledge_agent(state: dict) -> dict:
    """Susun knowledge_context: universal + (per-service project ATAU workspace)."""
    from state.schema import AgentState  # noqa: F401 — dokumentasi tipe
    service_name = state.get("service_name", "") or ""
    workspace_id = state.get("workspace_id")
    project_id = state.get("project_id")  # FE-8
    agents_visited = ["knowledge_agent"]

    sections: List[str] = []
    service_matched = False

    # 1) Knowledge Universal — keyword match playbook infra umum
    try:
        tokens = _extract_tokens(state)
        matched = await _match_universal_playbooks(tokens, service_name)
        if matched:
            lines = ["## Knowledge Universal (Playbook Infra Bawaan)", ""]
            for m in matched:
                lines.append(f"### Playbook: {m['id']} (cocok: {m['hits']})")
                lines.append(m["body"])
                lines.append("")
            sections.append("\n".join(lines).strip())
            logger.info(f"[KnowledgeAgent] universal playbooks: {[m['id'] for m in matched]}")
    except Exception as e:
        logger.warning(f"[KnowledgeAgent] universal section failed: {e}")

    # 2) FE-8: knowledge spesifik service milik project (match routing service)
    if project_id:
        try:
            from services.service_store import build_service_context_for_agent
            service_matched, svc_ctx = await build_service_context_for_agent(project_id, service_name)
            if svc_ctx:
                sections.append(svc_ctx)
                logger.info(
                    f"[KnowledgeAgent] PROJECT-SERVICE knowledge injected "
                    f"project={project_id} svc={service_name} matched={service_matched}"
                )
        except Exception as e:
            logger.warning(f"[KnowledgeAgent] project-service section failed: {e}")

    # 3) Fallback workspace-level (FE-7): hanya bila routing TIDAK match service project
    if workspace_id and not service_matched:
        try:
            from services.workspace_knowledge import build_workspace_context
            ws_ctx = await build_workspace_context(workspace_id)
            if ws_ctx:
                sections.append(ws_ctx)
                logger.info(f"[KnowledgeAgent] workspace knowledge injected ws={workspace_id}")
        except Exception as e:
            logger.warning(f"[KnowledgeAgent] workspace section failed: {e}")

    knowledge_context = "\n\n---\n\n".join(sections)
    return {
        "knowledge_context": knowledge_context,
        "agents_visited": agents_visited,
    }
