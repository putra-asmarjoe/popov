import { useTranslation } from "react-i18next"
import { AlertTriangle, TrendingDown, TrendingUp } from "lucide-react"
import { cn } from "@/lib/utils"
import { useWidgetData } from "@/components/overview/WidgetDataContext"

/**
 * ErrorRateCard — contoh widget OPTIONAL (default OFF, registry).
 * Mini stat error rate dari `episode.symptoms.error_rate` (terbaru) + alert count.
 * Body-only; chrome di WidgetShell.
 */
export function ErrorRateCard() {
  const { t } = useTranslation("project")
  const { overview } = useWidgetData()
  const episodes = overview?.episode_timeline ?? []
  const alerts = overview?.alert_feed ?? []

  const withRate = episodes.filter((ep) => ep.symptoms?.error_rate != null)
  const latestRate = withRate[0]?.symptoms?.error_rate ?? null
  const prevRate = withRate[1]?.symptoms?.error_rate ?? null

  const trend =
    latestRate == null || prevRate == null
      ? null
      : latestRate > prevRate
        ? "up"
        : latestRate < prevRate
          ? "down"
          : "flat"

  return (
    <div className="flex min-h-0 flex-col gap-2 p-3">
      <div className="flex items-end justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("overview.widgets.error_rate")}
          </p>
          <p className="mt-0.5 text-2xl font-bold tabular-nums">
            {latestRate != null ? `${latestRate}%` : "—"}
          </p>
        </div>
        {trend && (
          <span
            className={cn(
              "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold",
              trend === "up" && "bg-red-500/15 text-red-700 dark:text-red-400",
              trend === "down" && "bg-green-600/15 text-green-700 dark:text-green-400",
              trend === "flat" && "bg-muted text-muted-foreground",
            )}
            aria-label={t("overview.widgets.error_rate_trend", { trend })}
          >
            {trend === "up" && <TrendingUp className="size-3" aria-hidden="true" />}
            {trend === "down" && <TrendingDown className="size-3" aria-hidden="true" />}
            {trend === "flat" && <span className="size-2 rounded-full bg-muted-foreground" aria-hidden="true" />}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <AlertTriangle className="size-3 shrink-0 text-amber-500" aria-hidden="true" />
        <span>
          {t("overview.widgets.alert_count", { count: alerts.length })}
        </span>
      </div>
    </div>
  )
}