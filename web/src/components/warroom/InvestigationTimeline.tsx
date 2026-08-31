import { useState } from "react"
import { useTranslation } from "react-i18next"
import { GitBranch, ListOrdered } from "lucide-react"
import { AgentGraphSVG } from "@/components/chat/AgentGraphSVG"
import { formatMs } from "@/lib/utils"
import type { AgentTrace } from "@/types/chat"
import type { WarroomTimelineStep } from "@/types/warroom"

/**
 * Timeline investigasi per run — reuse AgentGraphSVG (sequential caveat) +
 * list step dengan durasi. Timing TIDAK tersedia utk channel non-chat (kosong).
 */
export function InvestigationTimeline({ steps }: { steps: WarroomTimelineStep[] }) {
  const { t } = useTranslation("project")
  const [selected, setSelected] = useState<string | null>(null)
  if (!steps.length) return null

  const traces: AgentTrace[] = steps.map((s) => ({
    agent: s.agent,
    order: s.order ?? 0,
    duration_ms: s.duration_ms,
    summary: {},
  }))

  return (
    <div className="rounded-xl border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <GitBranch className="size-3.5 text-primary" aria-hidden="true" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t("warroom.timeline")}
        </span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {steps.length} {t("warroom.timeline_steps")}
        </span>
      </div>

      <div className="p-3">
        <AgentGraphSVG traces={traces} selectedAgent={selected} onSelect={setSelected} />

        <ol className="mt-3 divide-y divide-border/50">
          {steps.map((s, i) => (
            <li
              key={`${s.agent}-${i}`}
              className="flex items-center gap-2 py-1.5 text-xs"
            >
              <ListOrdered className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span className="tabular-nums text-[10px] text-muted-foreground">{i + 1}</span>
              <span className="font-mono font-medium">{s.agent.replace("_agent", "")}</span>
              <span className="ml-auto tabular-nums text-muted-foreground">
                {formatMs(s.duration_ms)}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}