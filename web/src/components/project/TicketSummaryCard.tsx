import { useTranslation } from "react-i18next"
import { Search, Ticket, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { MultiSelectPopover } from "@/components/ticket/MultiSelectPopover"
import { SeverityBadge, StatusBadge } from "@/components/ticket/Badges"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import type { TicketFilters } from "@/store/ticket.store"
import type { TicketSeverity, TicketStatus } from "@/types/ticket"
import type { Ticket as TicketType } from "@/types/ticket"

const ALL_STATUSES: TicketStatus[] = ["new", "open", "in_progress", "needs_review", "resolved", "closed"]
const ALL_SEVERITIES: TicketSeverity[] = ["critical", "high", "medium", "low"]
const SEV_ORDER: TicketSeverity[] = ["critical", "high", "medium", "low"]

/** TicketSummaryCard — presentational. State/filter/query dipegang ProjectOverview
 *  (biar klik tiket → overlay detail di warroom, mode tidak pindah ke classic). */
export function TicketSummaryCard({
  tickets,
  isLoading,
  activeTicketId,
  filters,
  searchInput,
  onSearchInput,
  onFiltersChange,
  onSelectTicket,
}: {
  tickets: TicketType[]
  isLoading: boolean
  activeTicketId: string | null
  filters: TicketFilters
  searchInput: string
  onSearchInput: (v: string) => void
  onFiltersChange: (f: TicketFilters) => void
  onSelectTicket: (t: TicketType) => void
}) {
  const { t } = useTranslation("project")

  const activeCount =
    filters.status.length + filters.severity.length + (filters.assignee ? 1 : 0) + (filters.search ? 1 : 0)

  const bySeverity = SEV_ORDER.reduce(
    (acc, sev) => {
      acc[sev] = tickets.filter((tk) => tk.severity === sev).length
      return acc
    },
    {} as Record<TicketSeverity, number>,
  )

  const toggleStatus = (s: TicketStatus) =>
    onFiltersChange({
      ...filters,
      status: filters.status.includes(s) ? filters.status.filter((v) => v !== s) : [...filters.status, s],
    })

  const toggleSeverity = (s: TicketSeverity) =>
    onFiltersChange({
      ...filters,
      severity: filters.severity.includes(s)
        ? filters.severity.filter((v) => v !== s)
        : [...filters.severity, s],
    })

  return (
    <div className="flex min-h-0 flex-col rounded-xl border bg-card ring-1 ring-foreground/5">
      {/* Header */}
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <Ticket className="size-3.5 text-primary" aria-hidden="true" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t("overview.open_tickets")}
        </span>
        <span className="ml-auto tabular-nums text-sm font-bold">
          {isLoading ? "…" : tickets.length}
        </span>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-1.5 border-b px-2 py-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchInput}
            onChange={(e) => onSearchInput(e.target.value)}
            placeholder={t("filter.search_placeholder")}
            className="h-8 w-full min-w-[140px] pl-7 text-xs"
          />
        </div>
        <MultiSelectPopover
          label="Status"
          activeCount={filters.status.length}
          items={ALL_STATUSES.map((s) => ({
            value: s,
            label: t(`ticket.status.${s}`),
            checked: filters.status.includes(s),
            onToggle: () => toggleStatus(s),
          }))}
        />
        <MultiSelectPopover
          label="Severity"
          activeCount={filters.severity.length}
          items={ALL_SEVERITIES.map((s) => ({
            value: s,
            label: t(`ticket.severity.${s}`),
            checked: filters.severity.includes(s),
            onToggle: () => toggleSeverity(s),
          }))}
        />
        {activeCount > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1 px-1.5 text-[11px]"
            onClick={() => {
              onSearchInput("")
              onFiltersChange({ status: ["open", "new"], severity: [], assignee: null, search: "" })
            }}
          >
            <X className="size-3" /> {t("filter.reset", { count: activeCount })}
          </Button>
        )}
      </div>

      {/* Severity chips (dari hasil filter) */}
      <div className="flex flex-wrap gap-1.5 px-3 py-2">
        {SEV_ORDER.map((sev) => (
          <span
            key={sev}
            className={cn(
              "flex items-center gap-1.5 rounded-full bg-muted py-0.5 pl-0.5 pr-2 text-xs",
              bySeverity[sev] === 0 && "opacity-50",
            )}
          >
            <SeverityBadge severity={sev} className="px-1.5 py-0 text-[10px]" />
            <span className="tabular-nums font-semibold">{bySeverity[sev]}</span>
          </span>
        ))}
      </div>

      {/* Rows */}
      <div className="min-h-0 flex-1 overflow-y-auto border-t">
        {isLoading && !tickets.length && (
          <div className="space-y-2 p-3">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        )}

        {!isLoading && tickets.length === 0 && (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">
            {t("overview.tickets_empty_filter")}
          </p>
        )}

        <ul className="divide-y divide-border/50">
          {tickets.map((tk) => {
            const active = tk.id === activeTicketId
            return (
              <li key={tk.id}>
                <button
                  type="button"
                  onClick={() => onSelectTicket(tk)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-muted/40",
                    active && "bg-primary/10",
                  )}
                >
                  <span className="font-mono font-semibold">{tk.ticketNumber}</span>
                  <span className="min-w-0 flex-1 truncate">{tk.title}</span>
                  <StatusBadge status={tk.status} className="px-1.5 py-0 text-[9px]" />
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}