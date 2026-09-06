import { useWidgetData } from "@/components/overview/WidgetDataContext"

/**
 * BODY-ONLY — chrome di WidgetShell.
 * Nama alert = nama teknis (HighErrorRate) — proper noun, TIDAK diterjemahkan.
 */
export function TopAlertTypesTable() {
  const { overview } = useWidgetData()
  const stats = overview?.dashboard_stats
  if (!stats || stats.top_alert_types.length === 0) return null

  const max = stats.top_alert_types[0]?.count ?? 1

  return (
    <div className="min-h-0 space-y-2.5 p-3">
      {stats.top_alert_types.map((a) => (
        <div key={a.name}>
          <div className="mb-0.5 flex justify-between text-xs">
            <span className="truncate font-mono">{a.name}</span>
            <span className="ml-2 font-semibold">{a.count}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-blue-500"
              style={{ width: `${(a.count / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}
