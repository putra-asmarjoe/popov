// ============================================================
// THEME PROVIDER — wraps app, manages state + DOM sync + system pref
// ============================================================

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { ThemeContext, type ThemeContextValue } from "./theme-context"
import { getStoredTheme, setStoredTheme } from "./theme-storage"
import { type ResolvedThemeId, type ThemeId } from "./types"

interface ThemeProviderProps {
  children: ReactNode
  /** Override default theme (untuk testing/Storybook) */
  defaultTheme?: ThemeId
}

function getSystemPref(): boolean {
  if (typeof window === "undefined") return false
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false
  } catch {
    return false
  }
}

function resolveTheme(theme: ThemeId, systemDark: boolean): ResolvedThemeId {
  if (theme === "system") return systemDark ? "dark" : "light"
  return theme
}

export function ThemeProvider({ children, defaultTheme }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<ThemeId>(
    () => defaultTheme ?? getStoredTheme(),
  )
  const [systemDark, setSystemDark] = useState<boolean>(getSystemPref)

  // Listen ke perubahan prefers-color-scheme hanya bila theme === 'system'
  useEffect(() => {
    if (theme !== "system") return
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [theme])

  const resolvedTheme = resolveTheme(theme, systemDark)

  // Sync resolvedTheme → data-theme attribute di <html>
  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = resolvedTheme
    root.style.colorScheme = resolvedTheme === "light" ? "light" : "dark"
  }, [resolvedTheme])

  const setTheme = useCallback((newTheme: ThemeId) => {
    setThemeState(newTheme)
    setStoredTheme(newTheme)
  }, [])

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      resolvedTheme,
      setTheme,
      isLight: resolvedTheme === "light",
      isDark: resolvedTheme === "dark",
      isFancy: resolvedTheme === "fancy",
      isCalm: resolvedTheme === "calm",
      isSystem: theme === "system",
    }),
    [theme, resolvedTheme, setTheme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
