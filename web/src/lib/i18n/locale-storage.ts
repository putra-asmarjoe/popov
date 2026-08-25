import type { Locale } from "./types"
import { VALID_LOCALES } from "./types"

const STORAGE_KEY = "popov-agent-locale" as const

export function getStoredLocale(): Locale | null {
  if (typeof window === "undefined") return null
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && VALID_LOCALES.includes(stored as Locale)) {
      return stored as Locale
    }
    return null
  } catch {
    return null
  }
}

export function setStoredLocale(locale: Locale): void {
  if (typeof window === "undefined") return
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // Silent fail (private browsing, storage penuh)
  }
}
