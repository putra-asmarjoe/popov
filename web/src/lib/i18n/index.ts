import i18n from "i18next"
import { initReactI18next } from "react-i18next"
import HttpBackend from "i18next-http-backend"
import { detectLocale } from "./locale-detector"
import type { Locale } from "./types"
import { VALID_LOCALES } from "./types"
import { setStoredLocale } from "./locale-storage"

i18n
  .use(HttpBackend)
  .use(initReactI18next)
  .init({
    lng: detectLocale(),
    fallbackLng: "en",
    defaultNS: "common",
    ns: ["common"],

    backend: {
      loadPath: "/locales/{{lng}}/{{ns}}.json",
    },

    interpolation: {
      escapeValue: false, // React sudah handle XSS
    },

    react: {
      // Fase 1: false — migrasi bertahap, tanpa Suspense boundary per-page.
      // Setelah Fase 2 selesai → true + Suspense boundary.
      useSuspense: false,
    },

    debug: import.meta.env.DEV,
  })

export default i18n

export { getStoredLocale, setStoredLocale } from "./locale-storage"
export { detectLocale } from "./locale-detector"
export { LOCALES, VALID_LOCALES, DEFAULT_LOCALE, NAMESPACES } from "./types"
export type { Locale, LocaleConfig, Namespace } from "./types"

/**
 * Dipanggil di auth flow setelah login/register DAN session restore /auth/me.
 * Sync locale dari DB preference → i18next → localStorage.
 */
export async function applyBackendLocale(
  preference: string | null | undefined,
): Promise<void> {
  if (!preference) return
  if (!VALID_LOCALES.includes(preference as Locale)) return

  const locale = preference as Locale
  await i18n.changeLanguage(locale)
  setStoredLocale(locale)
}
