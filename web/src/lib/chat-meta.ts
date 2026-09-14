import type { ChatMessage } from "@/types/chat"

/** Meta pesan assistant TERAKHIR — sumber chips (suggestions/ticket_refs).
 *  Persist server (chat_messages.meta), refresh-safe. Dipakai chat tiket & project. */
export interface SuggestionChip {
  label: string
  action?: string
  /** CHAT3 §4A.7 (Rev 7): kontrak target = "action" | "offer".
   *  Legacy "investigation" | "general" masih dikirim producer lama (offer_planner)
   *  dan dipetakan ke action via chipKind(). Type hilang → action (safe default). */
  type?: "action" | "offer" | "investigation" | "general"
  /** CHAT3 §4A.7: target navigasi utk OFFER (mis. "/tickets/TKT-0042").
   *  OFFER tanpa target → fallback ke onPick (giliran percakapan yang aman). */
  target?: string
  /** USER_PROFILE_PLAN Phase 2: identifier stabil chip utk counter chips_clicked.
   *  Backend boleh mengirim key topik (mis. "status", "reopen"); bila tidak ada,
   *  FE fallback ke `action` (investigate:<node>) — label TIDAK dipakai (bilingual). */
  key?: string
}

export type Suggestion = string | SuggestionChip

/** Jenis chip final (§4A.7): semantic carrier = field `type` dari backend;
 *  ikon/warna hanya styling FE. Legacy investigation/general → action;
 *  type hilang / plain string → action (safe default, additive non-breaking). */
export function chipKind(sug: Suggestion): "action" | "offer" {
  if (typeof sug === "object" && sug !== null && sug.type === "offer") return "offer"
  return "action"
}

/** ContextPill response metadata (CHAT3 §4A.5) — proyeksi FE dari conversation_state.
 *  Nilai payload (service, ticket_id) identifier locale-neutral, tidak diterjemahkan. */
export interface ContextPillData {
  type?: "context" | "anaphora"
  service?: string | null
  ticket_id?: string | null
  resolved_ref?: { original: string; resolved: string } | null
}

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
  /** CHAT3 §4A.5: konteks aktif / resolusi anaphora di atas reply. */
  context_pill?: ContextPillData
  [key: string]: unknown
}

/** Ambil context_pill dari meta pesan (message.meta bertipe Record<string,unknown>). */
export function contextPillOf(meta: unknown): ContextPillData | null {
  if (!meta || typeof meta !== "object") return null
  const pill = (meta as AssistantMeta).context_pill
  return pill && typeof pill === "object" ? pill : null
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
