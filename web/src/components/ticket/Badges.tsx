import { useTranslation } from "react-i18next"
import { cn, severityColor, statusColor } from "@/lib/utils"
import type { TicketSeverity, TicketStatus } from "@/types/ticket"

export function SeverityBadge({ severity, className }: { severity: TicketSeverity; className?: string }) {
  const { t } = useTranslation("project")
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold leading-4",
        severityColor[severity],
        className,
      )}
    >
      {t(`ticket.severity.${severity}`)}
    </span>
  )
}

export function StatusBadge({ status, className }: { status: TicketStatus; className?: string }) {
  const { t } = useTranslation("project")
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium leading-4",
        statusColor[status],
        className,
      )}
    >
      {t(`ticket.status.${status}`)}
    </span>
  )
}
