export type Locale = "en" | "id"

export interface LocaleConfig {
  id: Locale
  label: string
  flag: string
  dir: "ltr" | "rtl"
}

/** Tambah bahasa baru di sini — otomatis muncul di LocaleSwitcher */
export const LOCALES: LocaleConfig[] = [
  { id: "en", label: "English", flag: "🇺🇸", dir: "ltr" },
  { id: "id", label: "Indonesia", flag: "🇮🇩", dir: "ltr" },
]

export const VALID_LOCALES: Locale[] = LOCALES.map((l) => l.id)
export const DEFAULT_LOCALE: Locale = "en"

/**
 * Namespace list — update saat tambah file JSON baru.
 * 'common' eager load, sisanya lazy (Fase 2).
 */
export const NAMESPACES = [
  "common",
  "auth",
  "workspace",
  "project",
  "management",
  "settings",
  "onboarding",
] as const
export type Namespace = (typeof NAMESPACES)[number]
