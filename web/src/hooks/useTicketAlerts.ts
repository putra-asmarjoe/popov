import { useQuery, useQueryClient } from "@tanstack/react-query"
import { api, apiErrorMessage } from "@/lib/api"
import type { TicketAlert } from "@/types/ticket"

/** Daftar alert ter-link ke tiket (terbaru dulu) — Fix #86. */
export function useTicketAlerts(ticketId: string | null) {
  return useQuery({
    queryKey: ["ticketAlerts", ticketId],
    queryFn: async () => {
      try {
        const { data } = await api.get(`/tickets/${ticketId}/alerts`)
        return data as { alerts: TicketAlert[]; total: number }
      } catch (error) {
        throw new Error(apiErrorMessage(error, "Gagal memuat alert ter-link"))
      }
    },
    enabled: !!ticketId,
  })
}

/** Invalidate semua query alerts (dipakai WS handler). */
export function useInvalidateTicketAlerts() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ["ticketAlerts"] })
}
