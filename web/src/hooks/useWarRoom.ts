import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { WarroomResponse } from "@/types/warroom"

/** War Room data — lazy-fetch per ticket. RCA tidak berubah setelah selesai. */
export function useWarRoom(ticketId: string | null | undefined) {
  return useQuery({
    queryKey: ["ticket-warroom", ticketId],
    queryFn: () =>
      api.get<WarroomResponse>(`/tickets/${ticketId}/warroom`).then((r) => r.data),
    enabled: Boolean(ticketId),
    staleTime: 15_000,
    refetchInterval: 30_000,
    // Jangan polling saat tab hidden / window unfocus (stop offscreen work)
    refetchIntervalInBackground: false,
  })
}