// ============================================================
// THEME CONTEXT — React context + hook
// ============================================================

import { createContext, useContext } from "react"
import { DEFAULT_THEME, type ThemeId, type ResolvedThemeId } from "./types"

export interface ThemeContextValue {
  /** Preferensi user (bisa "system") */
  theme: ThemeId
  /** Tema yang dipakai sekarang untuk styling (resolved dari system jika perlu) */
  resolvedTheme: ResolvedThemeId
  /** Set tema baru (persist + update DOM) */
  setTheme: (theme: ThemeId) => void
  /** True jika resolved === 'light' */
  isLight: boolean
  /** True jika resolved === 'dark' */
  isDark: boolean
  /** True jika resolved === 'fancy' */
  isFancy: boolean
  /** True jika resolved === 'calm' */
  isCalm: boolean
  /** True jika user pilih 'system' */
  isSystem: boolean
}

export const ThemeContext = createContext<ThemeContextValue>({
  theme: DEFAULT_THEME,
  resolvedTheme: DEFAULT_THEME as ResolvedThemeId,
  setTheme: () => {},
  isLight: true,
  isDark: false,
  isFancy: false,
  isCalm: false,
  isSystem: false,
})

/** Hook untuk mengakses theme context. */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) {
    throw new Error("useTheme must be used within <ThemeProvider>")
  }
  return ctx
}
