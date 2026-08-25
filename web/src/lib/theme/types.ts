// ============================================================
// THEME TYPES & CONSTANTS
// ============================================================

export type ThemeId = "light" | "dark" | "fancy" | "calm" | "system"

export type ThemeIconName = "Sun" | "Moon" | "Sparkles" | "CloudMoon" | "Monitor"

export interface Theme {
  id: ThemeId
  label: string
  /** Nama icon dari lucide-react */
  icon: ThemeIconName
  description: string
}

/** Tambah tema baru di sini — otomatis muncul di ThemeSwitcher */
export const THEMES: Theme[] = [
  { id: "light",  label: "Light",  icon: "Sun",       description: "Cerah, bersih" },
  { id: "dark",   label: "Dark",   icon: "Moon",      description: "Standar gelap" },
  { id: "fancy",  label: "Nova",   icon: "Sparkles",  description: "Premium, eye-friendly" },
  { id: "calm",   label: "Calm",   icon: "CloudMoon", description: "On-call panjang" },
  { id: "system", label: "System", icon: "Monitor",   description: "Ikuti OS" },
] as const

export const DEFAULT_THEME: ThemeId = "light"

/** Tema yang boleh di-resolve ke data-theme attribute (system tidak di sini) */
export type ResolvedThemeId = "light" | "dark" | "fancy" | "calm"
