import { useTranslation } from "react-i18next"
import { AlertTriangle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { formatDate } from "@/lib/utils"
import type { TicketAlert } from "@/types/ticket"

/** Timeline alert ter-link ke tiket (1 tiket : N alert, Fix #86).
 *  Struktur identik dgn ProgressLog — dot warna amber = sinyal sistem, bukan catatan manusia. */
export function LinkedAlerts({ alerts }: { alerts: TicketAlert[] }) {
  const { t } = useTranslation("project")
  if (alerts.length === 0) {
    return <p className="text-xs text-muted-foreground">{t("alerts.empty")}</p>
  }

  return (
    <ol className="relative space-y-3 border-l pl-4">
      {alerts.map((alert) => (
        <li key={alert.id} className="relative">
          <span className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-amber-500/70" />
          <div className="flex flex-wrap items-center gap-1.5">
            <AlertTriangle className="size-3.5 shrink-0 text-amber-500" />
            <p className="text-sm leading-snug font-medium">{alert.name}</p>
            <Badge
              variant="outline"
              className="h-4 px-1.5 text-[9px] uppercase tracking-wide text-muted-foreground"
            >
              {alert.severity}
            </Badge>
            {alert.serviceName && (
              <Badge variant="outline" className="h-4 px-1.5 font-mono text-[9px] text-muted-foreground">
                {alert.serviceName}
              </Badge>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Popov Watchdog · {formatDate(alert.occurredAt ?? alert.createdAt)}
          </p>
        </li>
      ))}
    </ol>
  )
}
