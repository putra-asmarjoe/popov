import { AgentDocsManager } from "@/components/management/AgentDocsManager"

/**
 * KnowledgeManager — konsolidasi tab Docs + Knowledge (Fix #58).
 * Hanya menyisakan sub-view Grounding (Sistem); view tenant (Knowledge Service)
 * dihapus dari UI — dikelola per-workspace di Settings → Services.
 */
export function KnowledgeManager() {
  return (
    <div className="space-y-5">
      <AgentDocsManager />
    </div>
  )
}
