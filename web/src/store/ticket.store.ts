import { create } from "zustand"
import type { Ticket, TicketStatus } from "@/types/ticket"

export interface TicketFilters {
  status: TicketStatus[]
  severity: string[]
  environment: string | null
  assignee: string | null
  search: string
}

interface TicketStore {
  activeTicket: Ticket | null
  filters: TicketFilters

  setActiveTicket: (ticket: Ticket | null) => void
  setFilters: (filters: Partial<TicketFilters>) => void
  resetFilters: () => void
}

const DEFAULT_FILTERS: TicketFilters = {
  status: [],
  severity: [],
  environment: null,
  assignee: null,
  search: "",
}

export const useTicketStore = create<TicketStore>((set) => ({
  activeTicket: null,
  filters: DEFAULT_FILTERS,

  setActiveTicket(ticket) {
    set({ activeTicket: ticket })
  },

  setFilters(partial) {
    set((state) => ({ filters: { ...state.filters, ...partial } }))
  },

  resetFilters() {
    set({ filters: DEFAULT_FILTERS })
  },
}))
