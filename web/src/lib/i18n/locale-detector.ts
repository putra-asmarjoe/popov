import type { Locale } from "./types"
import { VALID_LOCALES, DEFAULT_LOCALE } from "./types"
import { getStoredLocale } from "./locale-storage"

/**
 * Fallback chain (pre-login):
 * 1. localStorage (user pernah pilih manual)
 * 2. Browser language (navigator.language)
 * 3. Default 'en'
 */
export function detectLocale(): Locale {
  const stored = getStoredLocale()
  if (stored) return stored

  if (typeof navigator !== "undefined") {
    const browserLang = navigator.language.split("-")[0].toLowerCase()
    if (VALID_LOCALES.includes(browserLang as Locale)) {
      return browserLang as Locale
    }
  }

  return DEFAULT_LOCALE
}
