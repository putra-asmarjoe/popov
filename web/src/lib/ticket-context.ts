import type { TicketContext } from "@/types/chat"
import type { Ticket } from "@/types/ticket"

/** Konteks tiket untuk chat (1 sesi = 1 tiket) — dipakai classic & warroom (DRY). */
export function buildTicketContext(ticket: Ticket, projectKey: string): TicketContext {
  return {
    ticketId: ticket.id,
    ticketNumber: `${projectKey}-${ticket.ticketNumber}`,
    title: ticket.title,
    traceId: ticket.traceId,
    serviceName: ticket.serviceName ?? null,
  }
}