import { useTranslation } from "react-i18next"
import { useWidgetData } from "@/components/overview/WidgetDataContext"
import { SEVERITY_COLOR } from "@/lib/dashboard-utils"

/**
 * BODY-ONLY — chrome di WidgetShell. Severity label via t("ticket.severity.X").
 */
export function TopServicesTable() {
  const { t } = useTranslation("project")
  const { overview } = useWidgetData()
  const stats = overview?.dashboard_stats
  if (!stats || stats.top_services.length === 0) return null

  return (
    <div className="min-h-0 space-y-2 p-3">
      {stats.top_services.map((s, i) => {
        const color = SEVERITY_COLOR[s.worst_severity] ?? "#6b7280"
        return (
          <div key={s.service} className="flex items-center gap-2">
            <span className="w-4 text-xs text-muted-foreground">{i + 1}</span>
            <span className="flex-1 truncate font-mono text-sm">{s.service}</span>
            <span
              className="rounded px-1.5 py-0.5 text-xs font-medium"
              style={{ color, backgroundColor: color + "20" }}
            >
              {t(`ticket.severity.${s.worst_severity}`)}
            </span>
            <span className="w-6 text-right text-sm font-semibold">{s.count}</span>
          </div>
        )
      })}
    </div>
  )
}
