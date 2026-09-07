import type { ChatMessage } from "@/types/chat"

/** Meta pesan assistant TERAKHIR — sumber chips (suggestions/ticket_refs).
 *  Persist server (chat_messages.meta), refresh-safe. Dipakai chat tiket & project. */
export interface SuggestionChip {
  label: string
  action?: string
  type?: "investigation" | "general"
  /** USER_PROFILE_PLAN Phase 2: identifier stabil chip utk counter chips_clicked.
   *  Backend boleh mengirim key topik (mis. "status", "reopen"); bila tidak ada,
   *  FE fallback ke `action` (investigate:<node>) — label TIDAK dipakai (bilingual). */
  key?: string
}

export type Suggestion = string | SuggestionChip

/** Identifier chip utk tracking counter profil — stabil & bahasa-netral.
 *  Prioritas: key eksplisit > action (investigate:<node>) > undefined (label saja
 *  tidak cukup — bilingual, tak bisa jadi key). */
export function chipKeyOf(sug: Suggestion): string | undefined {
  if (typeof sug === "object" && sug !== null) {
    if (sug.key) return sug.key
    if (sug.action) return sug.action
  }
  return undefined
}

export interface AssistantMeta {
  ticket_refs?: { ticketNumber: number; ticketId: string; projectKey?: string; title?: string | null; status?: string | null }[]
  suggestions?: Suggestion[]
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
