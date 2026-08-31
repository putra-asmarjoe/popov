import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"
import type { TicketFilters } from "@/store/ticket.store"
import type { Ticket, TicketListMeta, TicketStatus } from "@/types/ticket"

// ── Queries ───────────────────────────────────────────────────────────────────

export function useTickets(projectId: string | null, filters: TicketFilters, page = 1) {
  return useQuery({
    queryKey: ["tickets", projectId, filters, page],
    queryFn: async () => {
      const { data } = await api.get(`/projects/${projectId}/tickets`, {
        params: {
          status: filters.status.length ? filters.status.join(",") : undefined,
          severity: filters.severity.length ? filters.severity.join(",") : undefined,
          assignee: filters.assignee ?? undefined,
          search: filters.search || undefined,
          page,
          limit: 20,
          sort: "updatedAt:desc",
        },
      })
      return data as { tickets: Ticket[]; meta: TicketListMeta }
    },
    enabled: !!projectId,
    placeholderData: keepPreviousData,
  })
}

export function useTicket(ticketId: string | null, initial?: Ticket | null) {
  return useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: async () => {
      const { data } = await api.get(`/tickets/${ticketId}`)
      return data as Ticket
    },
    enabled: !!ticketId,
    initialData: initial && initial.id === ticketId ? initial : undefined,
  })
}

// ── Mutations ─────────────────────────────────────────────────────────────────

/** Optimistic update tiket di SEMUA query list + query detail. */
function useOptimisticTicketUpdate() {
  const qc = useQueryClient()
  return async (ticketId: string, updater: (t: Ticket) => Ticket, apiCall: () => Promise<Ticket>) => {
    // Patch cache dulu (respons <50ms), rollback on error
    qc.setQueriesData<{ tickets: Ticket[] }>({ queryKey: ["tickets"] }, (old) =>
      old
        ? { ...old, tickets: old.tickets.map((t) => (t.id === ticketId ? updater(t) : t)) }
        : old,
    )
    qc.setQueriesData<Ticket>({ queryKey: ["ticket", ticketId] }, (old) => (old ? updater(old) : old))
    try {
      const fresh = await apiCall()
      await qc.invalidateQueries({ queryKey: ["tickets"] })
      await qc.invalidateQueries({ queryKey: ["ticket", ticketId] })
      return fresh
    } catch (error) {
      await qc.invalidateQueries({ queryKey: ["tickets"] })
      await qc.invalidateQueries({ queryKey: ["ticket", ticketId] })
      throw error
    }
  }
}

export function useCreateTicket(projectId: string | null) {
  const { t } = useTranslation("common")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      title: string
      description: string
      kind: string
      severity: string
      traceId?: string
      tags?: string[]
    }) => {
      const { data } = await api.post(`/projects/${projectId}/tickets`, input)
      return data as Ticket
    },
    onSuccess: () => {
      toast.success(t("toasts.ticket_created"))
      qc.invalidateQueries({ queryKey: ["tickets", projectId] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.ticket_create_failed"))),
  })
}

export function useUpdateTicket() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: {
      id: string
      title?: string
      description?: string
      severity?: string
      tags?: string[]
      kind?: string
      traceId?: string
    }) => {
      const { data } = await api.patch(`/tickets/${id}`, input)
      return data as Ticket
    },
    onSuccess: (ticket) => {
      toast.success("Tiket diperbarui")
      qc.invalidateQueries({ queryKey: ["tickets"] })
      qc.invalidateQueries({ queryKey: ["ticket", ticket.id] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal memperbarui tiket")),
  })
}

export function useChangeStatus() {
  const optimistic = useOptimisticTicketUpdate()
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: TicketStatus }) =>
      optimistic(
        id,
        (t) => ({ ...t, status }),
        async () => {
          const { data } = await api.post(`/tickets/${id}/status`, { status })
          return data as Ticket
        },
      ),
    onSuccess: (ticket) => toast.success(`Status → ${ticket.status}`),
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal mengubah status")),
  })
}

export function useReopenTicket() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await api.post(`/tickets/${id}/reopen`)
      return data as Ticket
    },
    onSuccess: (ticket) => {
      toast.success("Tiket dibuka kembali")
      qc.invalidateQueries({ queryKey: ["tickets"] })
      qc.invalidateQueries({ queryKey: ["ticket", ticket.id] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal membuka ulang tiket")),
  })
}

/** Status "new" → "open" saat detail tiket dibuka (silent, idempotent di backend). */
export function useOpenTicket() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.post(`/tickets/${id}/open`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tickets"] })
      qc.invalidateQueries({ queryKey: ["ticket"] })
    },
  })
}

export function useAssignTicket() {
  const optimistic = useOptimisticTicketUpdate()
  return useMutation({
    mutationFn: ({ id, userIds }: { id: string; userIds: string[] }) =>
      optimistic(
        id,
        (t) => ({ ...t, assignees: userIds }),
        async () => {
          const { data } = await api.post(`/tickets/${id}/assign`, { userIds })
          return data as Ticket
        },
      ),
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal meng-assign")),
  })
}

export function useAddProgress() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, note }: { id: string; note: string }) => {
      const { data } = await api.post(`/tickets/${id}/progress`, { note })
      return data as Ticket
    },
    onSuccess: (ticket) => {
      qc.invalidateQueries({ queryKey: ["tickets"] })
      qc.invalidateQueries({ queryKey: ["ticket", ticket.id] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menambah catatan")),
  })
}
