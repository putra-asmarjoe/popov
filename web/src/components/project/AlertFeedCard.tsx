import { useTranslation } from "react-i18next"
import { timeAgo } from "@/lib/utils"
import { useWidgetData } from "@/components/overview/WidgetDataContext"

/** Alert feed (watchdog) — body-only (chrome di WidgetShell). Data via WidgetDataContext.
 *  Severity tak disimpan terstruktur → tampilkan message + fingerprint grouping. */
export function AlertFeedCard() {
  const { t } = useTranslation("project")
  const { overview } = useWidgetData()
  const alerts = overview?.alert_feed ?? []
  if (!alerts.length) {
    return (
      <p className="px-3 py-6 text-center text-xs text-muted-foreground">
        {t("overview.alerts_empty")}
      </p>
    )
  }
  return (
    <ul className="min-h-0 flex-1 divide-y divide-border/50 overflow-y-auto">
      {alerts.map((a) => (
        <li key={a.id} className="px-3 py-2">
          <div className="flex items-center gap-1.5">
            <span className="size-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden="true" />
            <p className="min-w-0 flex-1 truncate text-xs font-medium">{a.message}</p>
            <span className="shrink-0 text-[10px] text-muted-foreground">
              {timeAgo(a.sent_at)}
            </span>
          </div>
          {a.fingerprint && (
            <p className="mt-0.5 pl-3 font-mono text-[10px] text-muted-foreground/70">
              {a.fingerprint}
            </p>
          )}
        </li>
      ))}
    </ul>
  )
}