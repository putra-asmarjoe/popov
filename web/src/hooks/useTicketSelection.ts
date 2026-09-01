import { useEffect, useRef } from "react"
import { useSearchParams } from "react-router-dom"
import { useTicket, useOpenTicket } from "@/hooks/useTickets"
import { useTicketStore } from "@/store/ticket.store"
import type { Ticket } from "@/types/ticket"

/**
 * useTicketSelection — SATU sumber seleksi tiket utk classic (ProjectPage) &
 * warroom (ProjectOverview). DRY penuh:
 *   - URL `?ticket=KEY-N` = single source of truth (shareable, refresh-safe).
 *   - Detail selalu fresh via `useTicket(id)` + realtime invalidate ["ticket"]
 *     → panel auto-update saat status tiket berubah (mis. close via chat).
 *     (Fix: warroom sebelumnya pakai snapshot list yang tak pernah refresh in-place.)
 *   - open/close/warroom navigation + auto-open new→open + sync zustand store.
 */
export function useTicketSelection({
  tickets,
  projectKey,
}: {
  tickets: Ticket[]
  projectKey: string
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const ticketParam = searchParams.get("ticket")
  const viewParam = searchParams.get("view")
  const { activeTicket, setActiveTicket } = useTicketStore()

  // URL → activeTicket (guard: hanya saat pindah ke tiket BEDA, bukan saat data
  // refresh — refresh ditangani useTicket di bawah).
  useEffect(() => {
    if (!ticketParam) {
      if (activeTicket) setActiveTicket(null)
      return
    }
    const num = parseInt(ticketParam.split("-").pop() ?? "", 10)
    if (Number.isNaN(num)) return
    const found = tickets.find((tk) => tk.ticketNumber === num)
    if (found && found.id !== activeTicket?.id) setActiveTicket(found)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketParam, tickets])

  // Fresh detail — reuse useTicket (SAMA utk classic & warroom). Realtime
  // invalidate ["ticket"] → refetch → detailTicket ikut segar.
  const { data: freshTicket } = useTicket(activeTicket?.id ?? null, activeTicket)
  const detailTicket = freshTicket ?? activeTicket

  const setTicketParam = (tk: Ticket | null, extra?: Record<string, string>) => {
    if (tk) {
      setSearchParams({ ticket: `${projectKey}-${tk.ticketNumber}`, ...extra }, { replace: true })
    } else {
      setSearchParams({}, { replace: true })
    }
  }

  const openTicket = (tk: Ticket | null) => {
    setActiveTicket(tk)
    setTicketParam(tk)
  }
  const closeTicket = () => openTicket(null)
  const openWarroom = (tk: Ticket) => {
    setActiveTicket(tk)
    setSearchParams(
      { ticket: `${projectKey}-${tk.ticketNumber}`, view: "warroom" },
      { replace: true },
    )
  }
  const exitWarroom = () => {
    if (detailTicket) setTicketParam(detailTicket) // buang view, ticket tetap
  }

  const isWarroom = viewParam === "warroom" && Boolean(detailTicket)

  // Status "new" → "open" saat detail dibuka (silent, idempotent di backend).
  const openedRef = useRef<Set<string>>(new Set())
  const openTicketMut = useOpenTicket()
  useEffect(() => {
    if (!detailTicket || detailTicket.status !== "new") return
    if (openedRef.current.has(detailTicket.id)) return
    openedRef.current.add(detailTicket.id)
    openTicketMut.mutate(detailTicket.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailTicket?.id, detailTicket?.status])

  return {
    activeTicket,
    detailTicket,
    activeTicketId: activeTicket?.id ?? null,
    isWarroom,
    hasTicketParam: Boolean(ticketParam),
    openTicket,
    closeTicket,
    openWarroom,
    exitWarroom,
  }
}