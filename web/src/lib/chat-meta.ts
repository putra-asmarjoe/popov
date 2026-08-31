import type { ChatMessage } from "@/types/chat"

/** Meta pesan assistant TERAKHIR — sumber chips (suggestions/ticket_refs).
 *  Persist server (chat_messages.meta), refresh-safe. Dipakai chat tiket & project. */
export interface AssistantMeta {
  ticket_refs?: { ticketNumber: number; ticketId: string; projectKey?: string; title?: string | null; status?: string | null }[]
  suggestions?: string[]
  [key: string]: unknown
}

export function lastAssistantMeta(messages: ChatMessage[] | undefined): AssistantMeta | null {
  if (!messages) return null
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role === "assistant" && m.meta && typeof m.meta === "object") {
      return m.meta as AssistantMeta
    }
  }
  return null
}
