import { useTranslation } from "react-i18next"
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts"
import { useWidgetData } from "@/components/overview/WidgetDataContext"
import { fillTrendGaps } from "@/lib/dashboard-utils"

/**
 * BODY-ONLY — chrome di WidgetShell. Nama seri via t("...").
 */
export function TicketTrendChart() {
  const { t } = useTranslation("project")
  const { overview } = useWidgetData()
  const stats = overview?.dashboard_stats
  if (!stats) return null

  const created = fillTrendGaps(stats.tickets_created_trend, stats.days)
  const resolved = fillTrendGaps(stats.tickets_resolved_trend, stats.days)

  const data = created.map((c, i) => ({
    date: c.date,
    [t("dashboard.series_created")]: c.count,
    [t("dashboard.series_resolved")]: resolved[i]?.count ?? 0,
  }))

  return (
    <div className="min-h-0 p-3">
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey={t("dashboard.series_created")} stroke="#3b82f6" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey={t("dashboard.series_resolved")} stroke="#22c55e" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
