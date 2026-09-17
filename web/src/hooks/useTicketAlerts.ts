import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"
import type { TicketAlert } from "@/types/ticket"

/** Daftar alert ter-link ke tiket (terbaru dulu) — Fix #86. */
export function useTicketAlerts(ticketId: string | null) {
  const { t } = useTranslation("project")
  return useQuery({
    queryKey: ["ticketAlerts", ticketId],
    queryFn: async () => {
      try {
        const { data } = await api.get(`/tickets/${ticketId}/alerts`)
        return data as { alerts: TicketAlert[]; total: number }
      } catch (error) {
        throw new Error(apiErrorMessage(error, t("toasts.alerts_load_failed")))
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
