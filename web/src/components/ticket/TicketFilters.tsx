import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Search, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { WorkspaceMember } from "@/types/workspace"
import { useTicketStore } from "@/store/ticket.store"
import type { TicketSeverity, TicketStatus } from "@/types/ticket"

// Enumerasi literal (nilai tampilan kini via i18n — bukan konstanta label)
const ALL_STATUSES: TicketStatus[] = ["new", "open", "in_progress", "needs_review", "resolved", "closed"]
const ALL_SEVERITIES: TicketSeverity[] = ["critical", "high", "medium", "low"]

/** Filter bar tiket: status & severity multi, assignee select, search debounce. */
export function TicketFilters({ members }: { members: WorkspaceMember[] }) {
  const { t } = useTranslation("project")
  const { filters, setFilters, resetFilters } = useTicketStore()
  const [searchInput, setSearchInput] = useState(filters.search)

  // Debounce 300ms untuk search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== filters.search) setFilters({ search: searchInput })
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  const activeCount =
    filters.status.length +
    filters.severity.length +
    (filters.assignee ? 1 : 0) +
    (filters.search ? 1 : 0)

  const toggleStatus = (s: TicketStatus) =>
    setFilters({
      status: filters.status.includes(s)
        ? filters.status.filter((v) => v !== s)
        : [...filters.status, s],
    })
  const toggleSeverity = (s: TicketSeverity) =>
    setFilters({
      severity: filters.severity.includes(s)
        ? filters.severity.filter((v) => v !== s)
        : [...filters.severity, s],
    })

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder={t("filter.search_placeholder")}
          className="h-8 w-52 pl-8 text-sm"
        />
      </div>

      {/* Status multi */}
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

      {/* Severity multi */}
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

      {/* Assignee */}
      <Select
        value={filters.assignee ?? "all"}
        onValueChange={(v) => setFilters({ assignee: v === "all" ? null : v })}
      >
        <SelectTrigger className="h-8 w-40 text-sm">
          <SelectValue placeholder="Assignee" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("filter.all_assignees")}</SelectItem>
          {members.map((m) => (
            <SelectItem key={m.userId} value={m.userId}>
              {m.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {activeCount > 0 && (
        <Button variant="ghost" size="sm" className="h-8 gap-1 text-xs" onClick={resetFilters}>
          <X className="size-3" /> {t("filter.reset", { count: activeCount })}
        </Button>
      )}
    </div>
  )
}

function MultiSelectPopover({
  label,
  activeCount,
  items,
}: {
  label: string
  activeCount: number
  items: { value: string; label: string; checked: boolean; onToggle: () => void }[]
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-sm">
          {label}
          {activeCount > 0 && (
            <span className="rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">
              {activeCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-44 p-2">
        {items.map((item) => (
          <Label
            key={item.value}
            className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm font-normal hover:bg-muted"
          >
            <Checkbox checked={item.checked} onCheckedChange={item.onToggle} />
            {item.label}
          </Label>
        ))}
      </PopoverContent>
    </Popover>
  )
}
