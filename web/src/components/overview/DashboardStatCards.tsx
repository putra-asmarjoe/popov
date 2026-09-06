import { useTranslation } from "react-i18next"
import { useWidgetData } from "@/components/overview/WidgetDataContext"
import { formatMttr } from "@/lib/dashboard-utils"
import { AlertTriangle, Bot, Clock, RotateCcw, UserX } from "lucide-react"

/**
 * BODY-ONLY — chrome card (border/header/remove) di-render WidgetShell.
 * Semua label via t("...") project.json en/id.
 */
export function DashboardStatCards() {
  const { t } = useTranslation("project")
  const { overview } = useWidgetData()
  const stats = overview?.dashboard_stats

  if (!stats) return null

  const newCount = stats.ticket_counts_by_status["new"] ?? 0
  const openCount =
    (stats.ticket_counts_by_status["new"] ?? 0) +
    (stats.ticket_counts_by_status["open"] ?? 0) +
    (stats.ticket_counts_by_status["in_progress"] ?? 0) +
    (stats.ticket_counts_by_status["needs_review"] ?? 0)

  const criticalHigh =
    (stats.ticket_counts_by_severity["critical"] ?? 0) +
    (stats.ticket_counts_by_severity["high"] ?? 0)

  const cards = [
    { key: "open", label: t("dashboard.stat_open"), value: openCount, icon: <AlertTriangle className="size-4" />, color: "text-blue-500" },
    { key: "crit_high", label: t("dashboard.stat_critical_high"), value: criticalHigh, icon: <AlertTriangle className="size-4" />, color: "text-red-500" },
    { key: "mttr", label: t("dashboard.stat_mttr"), value: formatMttr(stats.mttr_seconds), icon: <Clock className="size-4" />, color: "text-amber-500" },
    { key: "ai", label: t("dashboard.stat_ai_investigated"), value: stats.ai_investigated_count, icon: <Bot className="size-4" />, color: "text-violet-500" },
    { key: "unassigned", label: t("dashboard.stat_unassigned"), value: stats.unassigned_open_count, icon: <UserX className="size-4" />, color: "text-orange-500" },
    { key: "recurring", label: t("dashboard.stat_recurring"), value: stats.recurring_alerts_count, icon: <RotateCcw className="size-4" />, color: "text-yellow-500" },
  ]

  return (
    <div className="grid min-h-0 grid-cols-2 gap-3 p-3 sm:grid-cols-3 lg:grid-cols-6">
      {cards.map((c) => (
        <div key={c.key} className="flex flex-col gap-1 rounded-lg border bg-card p-3">
          <div className={`flex items-center gap-1.5 text-xs text-muted-foreground ${c.color}`}>
            {c.icon}
            {c.label}
          </div>
          {c.key === "open" ? (
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold tracking-tight">{c.value}</span>
              {newCount > 0 && (
                <span className="inline-flex items-center rounded-full bg-status-new px-1.5 py-0.5 text-[10px] font-semibold text-status-new-fg">
                  {newCount} {t("dashboard.stat_new")}
                </span>
              )}
            </div>
          ) : (
            <div className="text-2xl font-bold tracking-tight">{c.value}</div>
          )}
        </div>
      ))}
    </div>
  )
}
