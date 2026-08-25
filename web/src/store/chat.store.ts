import { create } from "zustand"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"
import { getToken } from "@/lib/auth"
import type { ChatMessage, ChatSession, TicketContext } from "@/types/chat"

// EventSource tunggal level modul — satu stream aktif (mirror backend: 1 reader/session)
let es: EventSource | null = null

function apiBase(): string {
  return (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1"
}

interface ChatStore {
  sessions: ChatSession[]
  activeSession: ChatSession | null
  messages: Record<string, ChatMessage[]>
  isStreaming: boolean
  streamingText: string
  activeAgent: string | null
  ticketContext: TicketContext | null
  // bertambah setiap kali stream selesai → pemicu refetch history
  finalizeTick: number

  setSessions: (sessions: ChatSession[]) => void
  setActiveSession: (session: ChatSession | null) => void
  setMessages: (sessionId: string, messages: ChatMessage[]) => void
  appendMessage: (sessionId: string, message: ChatMessage) => void
  setTicketContext: (ctx: TicketContext | null) => void
  clearTicketContext: () => void

  sendMessage: (sessionId: string, text: string) => Promise<void>
  stopStream: () => void
}

export const useChatStore = create<ChatStore>((set, get) => ({
  sessions: [],
  activeSession: null,
  messages: {},
  isStreaming: false,
  streamingText: "",
  activeAgent: null,
  ticketContext: null,
  finalizeTick: 0,

  setSessions(sessions) {
    set({ sessions })
  },

  setActiveSession(session) {
    set({ activeSession: session })
  },

  setMessages(sessionId, messages) {
    set((s) => ({ messages: { ...s.messages, [sessionId]: messages } }))
  },

  appendMessage(sessionId, message) {
    set((s) => ({
      messages: { ...s.messages, [sessionId]: [...(s.messages[sessionId] ?? []), message] },
    }))
  },

  setTicketContext(ctx) {
    set({ ticketContext: ctx })
  },

  clearTicketContext() {
    set({ ticketContext: null })
  },

  async sendMessage(sessionId, text) {
    const { isStreaming, appendMessage } = get()
    if (isStreaming) return

    // 1. Tampilkan pesan user lokal
    appendMessage(sessionId, {
      id: `local-${Date.now()}`,
      sessionId,
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    })

    // 2. POST send (persist + trigger pipeline background)
    // Fix #57: kirim teks ASLI user saja (tanpa prefix [context: ...]).
    // Konteks tiket di-handle backend via session.ticketId (Fix #49) — user
    // tidak perlu melihat teks yang bukan dia ketik.
    try {
      await api.post(`/chat/sessions/${sessionId}/send`, {
        message: text,
      })
    } catch (error) {
      toast.error(apiErrorMessage(error, "Gagal mengirim pesan"))
      return
    }

    // 3. Buka SSE stream
    const token = getToken()
    if (!token) return
    set({ isStreaming: true, streamingText: "", activeAgent: null })
    es = new EventSource(
      `${apiBase()}/chat/sessions/${sessionId}/stream?token=${encodeURIComponent(token)}`,
    )

    const finalize = (suffix?: string) => {
      const state = get()
      es?.close()
      es = null
      const content = (state.streamingText + (suffix ?? "")).trim()
      if (content) {
        state.appendMessage(sessionId, {
          id: `assistant-${Date.now()}`,
          sessionId,
          role: "assistant",
          content,
          createdAt: new Date().toISOString(),
        })
      }
      set({
        isStreaming: false,
        streamingText: "",
        activeAgent: null,
        finalizeTick: state.finalizeTick + 1,
      })
    }

    es.onmessage = (e) => {
      if (e.data === "[DONE]") {
        finalize()
        return
      }
      try {
        const event = JSON.parse(e.data)
        if (event.type === "token") {
          set((s) => ({ streamingText: s.streamingText + (event.data ?? "") }))
        } else if (event.type === "agent") {
          set({ activeAgent: event.data ?? null })
        } else if (event.type === "error") {
          toast.error(`Stream error: ${event.data ?? "unknown"}`)
          finalize()
        }
      } catch {
        // frame non-JSON (ping) — abaikan
      }
    }

    es.onerror = () => {
      // Koneksi putus: simpan yang sudah ada (pipeline di server tetap jalan & persist)
      if (get().isStreaming) finalize("\n\n_(koneksi stream terputus — jawaban tersimpan di server)_")
    }
  },

  stopStream() {
    if (!get().isStreaming) return
    es?.close()
    es = null
    const state = get()
    const sessionId = state.activeSession?.id
    const content = state.streamingText.trim()
    if (sessionId && content) {
      state.appendMessage(sessionId, {
        id: `assistant-${Date.now()}`,
        sessionId,
        role: "assistant",
        content: content + "\n\n_(dihentikan)_",
        createdAt: new Date().toISOString(),
      })
    }
    set({
      isStreaming: false,
      streamingText: "",
      activeAgent: null,
      finalizeTick: state.finalizeTick + 1,
    })
  },
}))
