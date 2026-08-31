import { AgentDocsManager } from "@/components/management/AgentDocsManager"

/**
 * KnowledgeManager — Grounding (Sistem) only.
 * Knowledge Service (tenant) CRUD moved: Management is the sole place for
 * knowledge_library via KnowledgeLibrary (mode=management).
 */
export function KnowledgeManager() {
  return (
    <div className="space-y-5">
      <AgentDocsManager />
    </div>
  )
}
