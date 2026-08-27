import { create } from "zustand"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"
import { getToken } from "@/lib/auth"
import i18n from "@/lib/i18n"
import type { ChatMessage, ChatSession, TicketContext } from "@/types/chat"

// EventSource tunggal level modul — satu stream aktif (mirror backend: 1 reader/session)
let es: EventSource | null = null
// sessionId yang sedang di-stream (supaya handler tahu milik sesi mana)
let esSessionId: string | null = null
// Timestamp finalize terakhir (non-reaktif) — pemicu guard auto-attach (Fix #114)
let lastFinalizedAt = 0
/** True bila stream baru saja selesai (< 3s) — cegah auto-attach ke stream mati. */
export function recentlyFinalized(): boolean {
  return Date.now() - lastFinalizedAt < 3000
}

function apiBase(): string {
  return (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1"
}

interface ChatStore {
  sessions: ChatSession[]
  activeSession: ChatSession | null
  messages: Record<string, ChatMessage[]>
  // State streaming di-scope PER SESSION — bukan global, agar perpindahan halaman
  // chat (tiket ↔ project) tidak bocor menampilkan progress dari sesi lain.
  streaming: Record<
    string,
    { isStreaming: boolean; streamingText: string; activeAgent: string | null }
  >
  ticketContext: TicketContext | null
  // bertambah setiap kali stream selesai → pemicu refetch history
  finalizeTick: number

  setSessions: (sessions: ChatSession[]) => void
  setActiveSession: (session: ChatSession | null) => void
  setMessages: (sessionId: string, messages: ChatMessage[]) => void
  appendMessage: (sessionId: string, message: ChatMessage) => void
  setTicketContext: (ctx: TicketContext | null) => void
  clearTicketContext: () => void

  sendMessage: (sessionId: string, text: string, mode?: string) => Promise<void>
  /** Ikut stream yang SUDAH berjalan di server (mis. setelah refresh) — Fix #114 */
  attachStream: (sessionId: string) => void
  stopStream: () => void
}

function emptyStream() {
  return { isStreaming: false, streamingText: "", activeAgent: null }
}

export const useChatStore = create<ChatStore>((set, get) => ({
  sessions: [],
  activeSession: null,
  messages: {},
  streaming: {},
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

  async sendMessage(sessionId, text, mode) {
    const { streaming, appendMessage } = get()
    if (streaming[sessionId]?.isStreaming) return

    // 1. Tampilkan pesan user lokal
    appendMessage(sessionId, {
      id: `local-${Date.now()}`,
      sessionId,
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    })

    // 2. POST send (persist + trigger pipeline background)
    // Fix #57: kirim teks ASGI user saja (tanpa prefix [context: ...]).
    // Konteks tiket di-handle backend via session.ticketId (Fix #49) — user
    // tidak perlu melihat teks yang bukan dia ketik.
    // Chat by Project: mode depth opsional (low/medium/thinking).
    try {
      await api.post(`/chat/sessions/${sessionId}/send`, {
        message: text,
        ...(mode ? { mode } : {}),
      })
    } catch (error) {
      toast.error(apiErrorMessage(error, i18n.t("project:chat.send_failed")))
      return
    }

    // 3. Buka SSE stream untuk sesi INI saja
    get().attachStream(sessionId)
  },

  attachStream(sessionId) {
    // Fix #114: ikut stream berjalan di server (setelah refresh / 409 slot busy).
    // Idempotent: bila sudah streaming utk SESI LAIN, tutup dulu.
    if (es) {
      es.close()
      es = null
      esSessionId = null
    }
    const token = getToken()
    if (!token) return
    set((s) => ({
      streaming: { ...s.streaming, [sessionId]: { isStreaming: true, streamingText: "", activeAgent: null } },
    }))

    es = new EventSource(
      `${apiBase()}/chat/sessions/${sessionId}/stream?token=${encodeURIComponent(token)}`,
    )
    esSessionId = sessionId

    const finalize = (suffix?: string) => {
      const state = get()
      // Hanya finalisasi bila event dari SSE milik sesi ini
      if (esSessionId !== sessionId) {
        es?.close()
        es = null
        return
      }
      es?.close()
      es = null
      esSessionId = null
      const stream = state.streaming[sessionId] ?? emptyStream()
      const content = (stream.streamingText + (suffix ?? "")).trim()
      if (content && state.activeSession?.id === sessionId) {
        state.appendMessage(sessionId, {
          id: `assistant-${Date.now()}`,
          sessionId,
          role: "assistant",
          content,
          createdAt: new Date().toISOString(),
        })
      }
      lastFinalizedAt = Date.now()
      set((s) => ({
        streaming: { ...s.streaming, [sessionId]: emptyStream() },
        finalizeTick: s.finalizeTick + 1,
      }))
    }

    es.onmessage = (e) => {
      // Abaikan event dari SSE lama bila stream sudah di-replace
      if (esSessionId !== sessionId) return
      if (e.data === "[DONE]") {
        finalize()
        return
      }
      try {
        const event = JSON.parse(e.data)
        if (event.type === "token") {
          set((st) => {
            const cur = st.streaming[sessionId] ?? emptyStream()
            return {
              streaming: {
                ...st.streaming,
                [sessionId]: { ...cur, streamingText: cur.streamingText + (event.data ?? "") },
              },
            }
          })
        } else if (event.type === "agent") {
          set((st) => {
            const cur = st.streaming[sessionId] ?? emptyStream()
            return {
              streaming: {
                ...st.streaming,
                [sessionId]: { ...cur, activeAgent: event.data ?? null },
              },
            }
          })
        } else if (event.type === "error") {
          toast.error(`${i18n.t("project:chat.stream_error")}: ${event.data ?? "unknown"}`)
          finalize()
        }
      } catch {
        // frame non-JSON (ping) — abaikan
      }
    }

    es.onerror = () => {
      if (esSessionId !== sessionId) return
      // Koneksi putus: simpan yang sudah ada (pipeline di server tetap jalan & persist)
      if (get().streaming[sessionId]?.isStreaming)
        finalize(`\n\n_(${i18n.t("project:chat.stream_disconnected")})_`)
    }
  },

  stopStream() {
    const state = get()
    const sessionId = esSessionId ?? state.activeSession?.id
    if (!sessionId) return
    if (!state.streaming[sessionId]?.isStreaming) return
    es?.close()
    es = null
    esSessionId = null
    const content = state.streaming[sessionId]?.streamingText.trim()
    if (sessionId && content) {
      state.appendMessage(sessionId, {
        id: `assistant-${Date.now()}`,
        sessionId,
        role: "assistant",
        content: `${content}\n\n_(${i18n.t("project:chat.stream_stopped")})_`,
        createdAt: new Date().toISOString(),
      })
    }
    lastFinalizedAt = Date.now()
    set((s) => ({
      streaming: { ...s.streaming, [sessionId]: emptyStream() },
      finalizeTick: s.finalizeTick + 1,
    }))
  },
}))
