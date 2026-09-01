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
import { timeAgo, toPct } from "@/lib/utils"
import type { Ticket } from "@/types/ticket"
import type { WarroomDiagnosis } from "@/types/warroom"

/**
 * Hero strip — thesis ringkas (answer-first, frontend-design):
 * service_name · error rate (episode symptoms) · hypothesis · confidence · investigated ago.
 */
function HeroStrip({
  serviceName,
  errorRate,
  diagnosis,
  investigatedAt,
}: {
  serviceName: string | null
  errorRate: number | null
  diagnosis: WarroomDiagnosis
  investigatedAt: string | null
}) {
  const { t } = useTranslation("project")
  const items = [
    serviceName ? <span key="svc" className="font-mono text-xs font-bold">{serviceName}</span> : null,
    errorRate != null ? (
      <span key="err">
        {t("warroom.error_rate")}{" "}
        <span className="font-semibold tabular-nums">{errorRate}%</span>
      </span>
    ) : null,
    <span key="hypo" className="min-w-0 truncate">
      {t("warroom.hypothesis")}{" "}
      <span className="font-semibold">{diagnosis.hypothesis || t("warroom.unknown")}</span>
    </span>,
    <span key="conf">
      {t("warroom.confidence")}{" "}
      <span className="font-semibold tabular-nums">{toPct(diagnosis.confidence)}%</span>
    </span>,
    investigatedAt ? (
      <span key="inv" className="tabular-nums text-muted-foreground">
        {t("warroom.investigated_ago")} {timeAgo(investigatedAt)}
      </span>
    ) : null,
  ].filter(Boolean)

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border bg-muted/30 px-3 py-2 text-xs text-foreground/90">
      {items.map((el, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span className="text-border" aria-hidden="true">·</span>}
          {el}
        </span>
      ))}
    </div>
  )
}

/**
 * War Room — answer-first. Mode `?ticket=KEY-N&view=warroom` (full-width,
 * menggantikan split 30/70 Detail|Chat). Chat default tetap utuh via back.
 * Order: Header → Hero → RunsList → Verdict → Second Brain → Pillars → Timeline|Gaps.
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
          lanes_executed: [],
          lanes_skipped: [],
        }
      : {
          hypothesis: t("warroom.unknown"),
          confidence: 0,
          correlation_summary: "",
          data_gaps: [],
          suggested_next: [],
          lanes_executed: [],
          lanes_skipped: [],
        }

  const errorRate = data?.episode?.symptoms?.error_rate ?? null

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

        {!isLoading && data?.source !== "none" && (
          <>
            <HeroStrip
              serviceName={data?.service_name ?? null}
              errorRate={errorRate}
              diagnosis={diagnosis}
              investigatedAt={data?.meta.investigated_at ?? null}
            />

            {runs.length > 1 && (
              <RunsList
                runs={runs}
                activeIndex={clamped}
                onSelect={setActiveIndex}
                onOpenChat={onBack}
              />
            )}

            <DiagnosisStrip
              diagnosis={diagnosis}
              episode={data?.episode}
              investigatedAt={data?.meta.investigated_at}
            />

            <SecondBrainPanel items={data?.second_brain ?? []} />

            {activeRun && <EvidencePillars pillars={activeRun.pillars} />}

            {activeRun && <InvestigationTimeline steps={activeRun.timeline} />}

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