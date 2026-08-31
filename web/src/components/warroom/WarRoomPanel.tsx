import { useState } from "react"
import { useTranslation } from "react-i18next"
import { ArrowLeft, Radar } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { SeverityBadge, StatusBadge } from "@/components/ticket/Badges"
import { DiagnosisStrip } from "@/components/warroom/DiagnosisStrip"
import { EvidencePillars } from "@/components/warroom/EvidencePillars"
import { SecondBrainPanel } from "@/components/warroom/SecondBrainPanel"
import { InvestigationTimeline } from "@/components/warroom/InvestigationTimeline"
import { DataGapsList } from "@/components/warroom/DataGapsList"
import { RunsList } from "@/components/warroom/RunsList"
import { useWarRoom } from "@/hooks/useWarRoom"
import { timeAgo } from "@/lib/utils"
import type { Ticket } from "@/types/ticket"
import type { WarroomDiagnosis } from "@/types/warroom"

/**
 * War Room — answer-first. Mode `?ticket=KEY-N&view=warroom` (full-width,
 * menggantikan split 30/70 Detail|Chat). Chat default tetap utuh via back.
 */
export function WarRoomPanel({
  ticket,
  onBack,
}: {
  ticket: Ticket
  onBack: () => void
}) {
  const { t } = useTranslation("project")
  const { data, isLoading } = useWarRoom(ticket.id)
  const [activeIndex, setActiveIndex] = useState(0)

  const runs = data?.runs ?? []
  const clamped = Math.min(activeIndex, Math.max(0, runs.length - 1))
  const activeRun = runs[clamped] ?? null

  const diagnosis: WarroomDiagnosis = activeRun
    ? activeRun.diagnosis
    : data?.episode
      ? {
          hypothesis: data.episode.root_cause ?? t("warroom.unknown"),
          confidence: data.episode.confidence,
          correlation_summary: data.episode.correlation_result ?? "",
          data_gaps: [],
          suggested_next: [],
        }
      : { hypothesis: t("warroom.unknown"), confidence: 0, correlation_summary: "", data_gaps: [], suggested_next: [] }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="flex min-w-0 items-center gap-2 border-b px-4 py-2.5">
        <Button variant="ghost" size="icon-sm" onClick={onBack} aria-label={t("warroom.back")}>
          <ArrowLeft className="size-4" />
        </Button>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {t("warroom.warroom")}
            </span>
            <span className="font-mono text-sm font-bold">#{ticket.ticketNumber}</span>
            <SeverityBadge severity={ticket.severity} />
            <StatusBadge status={ticket.status} />
          </div>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {ticket.title}
            <span className="ml-2 tabular-nums">
              {data ? `${t("warroom.updated")} ${timeAgo(data.meta.generated_at)}` : "…"}
              {data?.meta.channel ? ` · ${data.meta.channel}` : ""}
            </span>
          </p>
        </div>
      </div>

      {/* Body */}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {isLoading && (
          <div className="space-y-3">
            <Skeleton className="h-24 w-full" />
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          </div>
        )}

        {!isLoading && data?.source === "none" && (
          <div className="flex h-full flex-col items-center justify-center gap-2 py-16 text-center">
            <Radar className="size-10 text-muted-foreground/50" aria-hidden="true" />
            <p className="text-sm font-semibold">{t("warroom.empty_title")}</p>
            <p className="max-w-sm text-xs text-muted-foreground">{t("warroom.empty_body")}</p>
            <Button size="sm" variant="outline" onClick={onBack} className="mt-2">
              {t("warroom.empty_action")}
            </Button>
          </div>
        )}

        {!isLoading && data?.source === "incident_episodes" && runs.length === 0 && (
          <div className="flex items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            <Radar className="size-3.5 shrink-0" aria-hidden="true" />
            {t("warroom.partial_banner")}
          </div>
        )}

        {!isLoading && runs.length > 1 && (
          <RunsList
            runs={runs}
            activeIndex={clamped}
            onSelect={setActiveIndex}
            onOpenChat={onBack}
          />
        )}

        {!isLoading && data?.source !== "none" && (
          <>
            <DiagnosisStrip diagnosis={diagnosis} />
            {activeRun && <EvidencePillars pillars={activeRun.pillars} />}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {activeRun && <InvestigationTimeline steps={activeRun.timeline} />}
              <SecondBrainPanel items={data?.second_brain ?? []} />
            </div>
            {activeRun && (
              <DataGapsList
                dataGaps={diagnosis.data_gaps}
                suggestedNext={diagnosis.suggested_next}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}