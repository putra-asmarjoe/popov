import { createContext, useContext } from "react"
import type { ProjectOverviewData } from "@/types/overview"
import type { Ticket } from "@/types/ticket"
import type { TicketFilters } from "@/store/ticket.store"
import type { WorkspaceMember } from "@/types/workspace"

/**
 * Data context widget Overview — page tetap pegang data fetch (overview + useTickets),
 * widget cuma konsumen. Nilai di-provide ProjectOverview.
 */
export interface WidgetDataContextValue {
  projectId: string | null
  overview?: ProjectOverviewData
  tickets: Ticket[]
  ticketsLoading: boolean
  members: WorkspaceMember[]
  activeTicketId: string | null
  filters: TicketFilters
  searchInput: string
  onSearchInput: (v: string) => void
  onFiltersChange: (f: TicketFilters) => void
  onSelectTicket: (t: Ticket) => void
}

const WidgetDataContext = createContext<WidgetDataContextValue | null>(null)

export function WidgetDataProvider({
  value,
  children,
}: {
  value: WidgetDataContextValue
  children: React.ReactNode
}) {
  return <WidgetDataContext.Provider value={value}>{children}</WidgetDataContext.Provider>
}

export function useWidgetData(): WidgetDataContextValue {
  const ctx = useContext(WidgetDataContext)
  if (!ctx) throw new Error("useWidgetData must be used within WidgetDataProvider")
  return ctx
}