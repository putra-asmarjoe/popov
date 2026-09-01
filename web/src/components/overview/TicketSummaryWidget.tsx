import { TicketSummaryCard } from "@/components/project/TicketSummaryCard"
import { useWidgetData } from "@/components/overview/WidgetDataContext"

/** Adapter: baca filter/search/selection dari page context, render TicketSummaryCard.
 *  State filter tetap di page (tak hilang saat widget di-remove). */
export function TicketSummaryWidget() {
  const {
    tickets,
    ticketsLoading,
    activeTicketId,
    filters,
    searchInput,
    onSearchInput,
    onFiltersChange,
    onSelectTicket,
  } = useWidgetData()
  return (
    <TicketSummaryCard
      tickets={tickets}
      isLoading={ticketsLoading}
      activeTicketId={activeTicketId}
      filters={filters}
      searchInput={searchInput}
      onSearchInput={onSearchInput}
      onFiltersChange={onFiltersChange}
      onSelectTicket={onSelectTicket}
    />
  )
}