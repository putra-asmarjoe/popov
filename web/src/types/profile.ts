/** User Profile — USER_PROFILE_PLAN (Phase 1 backend selesai, Phase 2 UI).
 *  GET/PATCH /api/v1/profile?workspace_id=... · DELETE /profile/counters.
 *  Scope: per (user, workspace) — BUKAN global (plan D6/D7). */

export type Verbosity = "concise" | "standard" | "detailed"
export type Tone = "formal" | "casual"
export type FormatPreference = "list" | "paragraph" | "mixed"

export interface UserProfile {
  workspace_id: string
  // Manual fields (nullable = belum di-set → default agent)
  verbosity: Verbosity | null
  tone: Tone | null
  format_preference: FormatPreference | null
  default_chat_depth: number | null
  /** Field yang di-set manual — batch inferensi Phase 4 TIDAK menimpa (D3). */
  manual_overrides: string[]
  // Counter pasif (zero-effort)
  services_queried: Record<string, number>
  active_hours: number[]
  chips_clicked: Record<string, number>
  investigation_count: number
  interaction_count: number
  pending_suggestion: PendingSuggestion | null
  last_active_at: string | null
  updated_at: string | null
}

/** Field yang bisa di-set user via UI (PATCH /profile). */
export interface ProfilePatch {
  verbosity?: Verbosity | null
  tone?: Tone | null
  format_preference?: FormatPreference | null
  default_chat_depth?: number | null
}

/** Saran batch inferensi (Phase 4) — menunggu approve/auto-apply 24 jam. */
export interface PendingSuggestion {
  run_id: string
  fields: ProfilePatch
  reasons?: Record<string, string>
  generated_at: string | null
  expires_at: string | null
  status: "pending" | "applied" | "rejected"
}
