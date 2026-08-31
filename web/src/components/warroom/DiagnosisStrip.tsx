import { useState } from "react"
import { useTranslation } from "react-i18next"
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react"
import { cn, toPct } from "@/lib/utils"
import type { WarroomDiagnosis } from "@/types/warroom"

/**
 * Verdict Strip — signature War Room (frontend-design: answer-first).
 * Jawaban investigasi dalam satu baris: hypothesis + confidence + top gap,
 * lalu correlation summary (LLM text) yang bisa dibuka.
 */
export function DiagnosisStrip({ diagnosis }: { diagnosis: WarroomDiagnosis }) {
  const { t } = useTranslation("project")
  const [expanded, setExpanded] = useState(false)
  const pct = toPct(diagnosis.confidence)
  const topGap = diagnosis.data_gaps[0]
  const hasText = Boolean(diagnosis.correlation_summary?.trim())

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
      </div>

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