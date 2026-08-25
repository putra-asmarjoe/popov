import { useMemo } from "react"
import { useTranslation } from "react-i18next"
import { Radio } from "lucide-react"
import { useAuth } from "@/hooks/useAuth"
import { useObservabilityTargets, useStackProjectLinks } from "@/hooks/useManagement"

/**
 * ProjectStackSelector (Fix #45 M2M) — admin-only di ProjectPage.
 * 1 project bisa ter-link BANYAK stack (per kind), 1 stack bisa melayani
 * banyak project. Toggle per stack = link/unlink atomik.
 */
const KIND_LABEL: Record<string, string> = {
  prometheus: "Prometheus",
  tempo: "Tempo",
  alertmanager: "Alertmanager",
  loki: "Loki",
}

export function ProjectStackSelector({ workspaceId, projectId }: { workspaceId?: string; projectId?: string }) {
  const { t } = useTranslation("settings")
  const { user } = useAuth()
  const { data: targets } = useObservabilityTargets()
  const { link, unlink } = useStackProjectLinks()

  const visible = useMemo(
    () => (targets ?? []).filter((t) => !workspaceId || t.workspace_id === workspaceId),
    [targets, workspaceId],
  )

  if (!user || user.role !== "admin" || !projectId) return null

  const linked = visible.filter((t) => t.project_ids.includes(projectId))

  const toggle = async (observId: string, isLinked: boolean) => {
    if (isLinked) unlink.mutate({ observ_id: observId, project_id: projectId })
    else link.mutate({ observ_id: observId, project_id: projectId })
  }

  return (
    <div className="flex items-center gap-1.5" title="Observability stack yang melayani project ini">
      <Radio className="size-3.5 text-muted-foreground" />
      {visible.length === 0 ? (
        <span className="text-xs text-muted-foreground">{t("stack_selector_no_stack")}</span>
      ) : (
        <div className="flex flex-wrap items-center gap-1">
          {visible.map((t) => {
            const isOn = linked.some((l) => l.observ_id === t.observ_id)
            return (
              <button
                key={t.observ_id}
                type="button"
                disabled={link.isPending || unlink.isPending}
                onClick={() => toggle(t.observ_id, isOn)}
                className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
                  isOn
                    ? "border-primary bg-primary/10 font-medium text-primary"
                    : "text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                {KIND_LABEL[t.kind ?? ""] ?? t.name}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
