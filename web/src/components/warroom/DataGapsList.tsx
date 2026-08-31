import { useTranslation } from "react-i18next"
import { ListChecks, Radar } from "lucide-react"

/** Data gaps + suggested next — collapsible detail teknis (bukan first-class). */
export function DataGapsList({
  dataGaps,
  suggestedNext,
}: {
  dataGaps: string[]
  suggestedNext: string[]
}) {
  const { t } = useTranslation("project")
  const hasGaps = dataGaps.length > 0
  const hasNext = suggestedNext.length > 0
  if (!hasGaps && !hasNext) return null

  return (
    <div className="rounded-xl border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <ListChecks className="size-3.5 text-primary" aria-hidden="true" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t("warroom.data_gaps_title")}
        </span>
      </div>
      <div className="space-y-2 px-3 py-2.5">
        {hasGaps && (
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {t("warroom.data_gaps")}
            </p>
            <ul className="mt-1 space-y-1">
              {dataGaps.map((g, i) => (
                <li key={i} className="flex items-start gap-1.5 text-xs text-foreground/90">
                  <Radar className="mt-0.5 size-3 shrink-0 text-amber-500" aria-hidden="true" />
                  <span>{g}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {hasNext && (
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {t("warroom.suggested_next")}
            </p>
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {suggestedNext.map((n, i) => (
                <li
                  key={i}
                  className="rounded bg-muted px-2 py-1 text-xs text-foreground/90"
                >
                  {n}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}