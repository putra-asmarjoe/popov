import { useState } from "react"
import { useTranslation } from "react-i18next"
import { AlertTriangle, ChevronDown, ChevronUp, Clock } from "lucide-react"
import { cn, formatMs, timeAgo, toPct } from "@/lib/utils"
import type { WarroomDiagnosis, WarroomEpisode } from "@/types/warroom"

/** Label lane agent → i18n key (reuse pillar_*, +health). Fallback: nama agent. */
const LANE_LABEL_KEYS: Record<string, string> = {
  mongo_agent: "warroom.pillar_mongo",
  metrics_agent: "warroom.pillar_metrics",
  trace_agent: "warroom.pillar_trace",
  span_agent: "warroom.pillar_span",
  health_agent: "warroom.pillar_health",
}

/**
 * Verdict Strip — signature War Room (frontend-design: answer-first).
 * Jawaban investigasi: hypothesis + confidence + top gap + lane badges,
 * TTR & investigated ago, remediasi bernomor, lalu correlation summary (collapsible).
 */
export function DiagnosisStrip({
  diagnosis,
  episode,
  investigatedAt,
}: {
  diagnosis: WarroomDiagnosis
  episode?: WarroomEpisode | null
  investigatedAt?: string | null
}) {
  const { t } = useTranslation("project")
  const [expanded, setExpanded] = useState(false)
  const pct = toPct(diagnosis.confidence)
  const topGap = diagnosis.data_gaps[0]
  const hasText = Boolean(diagnosis.correlation_summary?.trim())
  const executed = diagnosis.lanes_executed ?? []
  const skipped = diagnosis.lanes_skipped ?? []
  const hasLanes = executed.length + skipped.length > 0
  const ttr = episode?.actual_ttr_minutes
  const remediations = episode?.resolution_actions ?? []
  const hasRemediation = remediations.length > 0

  return (
    <div className="rounded-xl border bg-card ring-1 ring-foreground/5">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3.5">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("warroom.hypothesis")}
          </p>
          <p className="mt-0.5 font-mono text-sm font-bold leading-tight">
            {diagnosis.hypothesis || t("warroom.unknown")}
          </p>
        </div>

        <div className="min-w-[160px] flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("warroom.confidence")}
          </p>
          <div className="mt-1 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full",
                  pct >= 70 ? "bg-green-600" : pct >= 40 ? "bg-amber-500" : "bg-red-500",
                )}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="tabular-nums text-sm font-semibold">{pct}%</span>
          </div>
        </div>

        {topGap && (
          <div className="min-w-[140px]">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {t("warroom.top_gap")}
            </p>
            <p className="mt-0.5 flex items-center gap-1.5 text-sm font-medium">
              <AlertTriangle className="size-3.5 shrink-0 text-amber-500" aria-hidden="true" />
              <span className="truncate">{topGap}</span>
            </p>
          </div>
        )}

        {(investigatedAt || ttr != null) && (
          <div className="ml-auto flex min-w-0 flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            {investigatedAt && (
              <span className="tabular-nums">
                {t("warroom.investigated_ago")} {timeAgo(investigatedAt)}
              </span>
            )}
            {ttr != null && (
              <span className="flex items-center gap-1 tabular-nums">
                <Clock className="size-3" aria-hidden="true" />
                {formatMs(ttr * 60_000)} {t("warroom.ttr")}
              </span>
            )}
          </div>
        )}
      </div>

      {hasLanes && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t px-4 py-2.5">
          {executed.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {t("warroom.lanes_executed")}
              </span>
              {executed.map((lane) => (
                <span
                  key={lane}
                  className="rounded bg-teal-600/15 px-1.5 py-0.5 text-[10px] font-medium text-teal-700 dark:text-teal-400"
                >
                  {t(LANE_LABEL_KEYS[lane] ?? lane)}
                </span>
              ))}
            </div>
          )}
          {skipped.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {t("warroom.lanes_skipped")}
              </span>
              {skipped.map((lane) => (
                <span
                  key={lane}
                  className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {t(LANE_LABEL_KEYS[lane] ?? lane)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {hasRemediation && (
        <div className="border-t px-4 py-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("warroom.remediation")}
          </p>
          <ol className="mt-1.5 space-y-1.5">
            {remediations.map((action, i) => (
              <li key={i} className="flex items-start gap-2 text-xs leading-snug text-foreground/90">
                <span
                  className="mt-px flex size-4 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold tabular-nums text-primary"
                  aria-hidden="true"
                >
                  {i + 1}
                </span>
                <span className="min-w-0">{action}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {hasText && (
        <div className="border-t px-4 py-2.5">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="flex w-full items-center gap-1.5 text-left text-xs text-muted-foreground hover:text-foreground"
          >
            <span className="font-medium">{t("warroom.correlation_summary")}</span>
            {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
          <p
            className={cn(
              "mt-1 whitespace-pre-wrap text-xs leading-relaxed text-foreground/90",
              !expanded && "line-clamp-2",
            )}
          >
            {diagnosis.correlation_summary}
          </p>
        </div>
      )}
    </div>
  )
}