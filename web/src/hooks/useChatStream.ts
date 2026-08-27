import { useEffect } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"
import { useChatStore } from "@/store/chat.store"
import type { ChatSession } from "@/types/chat"

// ── Queries ───────────────────────────────────────────────────────────────────

export function useChatSessions(projectId: string | null, limit = 20) {
  const setSessions = useChatStore((s) => s.setSessions)
  const query = useQuery({
    queryKey: ["chat", "sessions", projectId, limit],
    queryFn: async () => {
      const { data } = await api.get("/chat/sessions", {
        params: { ...(projectId ? { projectId } : {}), limit },
      })
      return data.sessions as ChatSession[]
    },
  })
  useEffect(() => {
    if (query.data) setSessions(query.data)
  }, [query.data, setSessions])
  return query
}

export function useChatMessages(sessionId: string | null) {
  const setMessages = useChatStore((s) => s.setMessages)
  const finalizeTick = useChatStore((s) => s.finalizeTick)
  const query = useQuery({
    queryKey: ["chat", "messages", sessionId],
    queryFn: async () => {
      const { data } = await api.get(`/chat/sessions/${sessionId}/messages`)
      return data.messages
    },
    enabled: !!sessionId,
  })
  // Refetch setelah stream selesai (jawaban asli server punya meta lengkap)
  useEffect(() => {
    if (sessionId && finalizeTick > 0) {
      query.refetch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finalizeTick])
  useEffect(() => {
    if (query.data && sessionId) setMessages(sessionId, query.data)
  }, [query.data, sessionId, setMessages])
  return query
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useCreateChatSession(projectId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vars?: {
      title?: string
      ticketId?: string | null
      projectId?: string // Chat by Project: override project tujuan (sidebar [+ baru])
    }) => {
      const { data } = await api.post("/chat/sessions", {
        projectId: vars?.projectId ?? projectId,
        ticketId: vars?.ticketId ?? null,
        title: vars?.title ?? "Chat baru",
      })
      return data as ChatSession
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chat", "sessions"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal membuat sesi chat")),
  })
}

/**
 * useChatStream — wrapper store (sendMessage/stopStream) sesuai spec plan FE-5.
 * Logika EventSource hidup di chat.store.ts agar tidak dobel saat pindah tab.
 */
export function useChatStream() {
  const sendMessage = useChatStore((s) => s.sendMessage)
  const stopStream = useChatStore((s) => s.stopStream)
  return { sendMessage, stopStream }
}

/** Fix #118: soft-delete sesi chat (hanya sesi project, bukan tiket). */
export function useDeleteChatSession() {
  const { t } = useTranslation("pchat")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) => {
      const { data } = await api.delete(`/chat/sessions/${sessionId}`)
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chat", "sessions"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("delete_failed"))),
  })
}
