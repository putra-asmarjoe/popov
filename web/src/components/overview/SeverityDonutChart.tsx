import { useTranslation } from "react-i18next"
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts"
import { useWidgetData } from "@/components/overview/WidgetDataContext"
import { SEVERITY_COLOR } from "@/lib/dashboard-utils"

/**
 * BODY-ONLY — chrome di WidgetShell. Severity label via t("ticket.severity.X").
 */
export function SeverityDonutChart() {
  const { t } = useTranslation("project")
  const { overview } = useWidgetData()
  const stats = overview?.dashboard_stats
  if (!stats) return null

  const data = Object.entries(stats.ticket_counts_by_severity)
    .filter(([, v]) => v > 0)
    .map(([key, value]) => ({
      key,
      name: t(`ticket.severity.${key}`, { defaultValue: key }),
      value,
    }))
    .sort((a, b) => {
      const order: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
      return (order[a.key] ?? 99) - (order[b.key] ?? 99)
    })

  if (data.length === 0) return null

  return (
    <div className="min-h-0 p-3">
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={80}
            paddingAngle={3}
            dataKey="value"
            nameKey="name"
          >
            {data.map((entry) => (
              <Cell
                key={entry.key}
                fill={SEVERITY_COLOR[entry.key] ?? "#6b7280"}
              />
            ))}
          </Pie>
          <Tooltip />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
      {/* Summary list */}
      <div className="mt-2 space-y-1.5">
        {data.map((d) => (
          <div key={d.key} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <span
                className="size-2.5 rounded-full"
                style={{ backgroundColor: SEVERITY_COLOR[d.key] ?? "#6b7280" }}
              />
              <span className="text-muted-foreground">{d.name}</span>
            </div>
            <span className="font-semibold tabular-nums">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
