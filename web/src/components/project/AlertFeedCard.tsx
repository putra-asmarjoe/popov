import { useTranslation } from "react-i18next"
import { BellRing } from "lucide-react"
import { timeAgo } from "@/lib/utils"
import type { OverviewAlert } from "@/types/overview"

/** Alert feed (watchdog) — scoped per project via observ_id. Severity tak
 *  disimpan terstruktur → tampilkan message + fingerprint grouping. */
export function AlertFeedCard({ alerts }: { alerts: OverviewAlert[] }) {
  const { t } = useTranslation("project")
  if (!alerts.length) {
    return (
      <div className="flex min-h-0 flex-col rounded-xl border bg-card ring-1 ring-foreground/5">
        <div className="flex items-center gap-1.5 border-b px-3 py-2">
          <BellRing className="size-3.5 text-primary" aria-hidden="true" />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("overview.alerts")}
          </span>
        </div>
        <p className="px-3 py-6 text-center text-xs text-muted-foreground">
          {t("overview.alerts_empty")}
        </p>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-col rounded-xl border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <BellRing className="size-3.5 text-primary" aria-hidden="true" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t("overview.alerts")}
        </span>
        <span className="ml-auto tabular-nums text-sm font-bold">{alerts.length}</span>
      </div>
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
    </div>
  )
}