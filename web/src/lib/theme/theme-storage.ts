// ============================================================
// THEME STORAGE — isolated localStorage access
// Semua akses localStorage untuk tema harus melalui file ini.
// ============================================================

import { DEFAULT_THEME, type ThemeId } from "./types"

const STORAGE_KEY = "popov-agent-theme" as const
const VALID_THEMES: readonly ThemeId[] = ["light", "dark", "fancy", "calm", "system"]

function isValidTheme(value: unknown): value is ThemeId {
  return typeof value === "string" && (VALID_THEMES as readonly string[]).includes(value)
}

export function getStoredTheme(): ThemeId {
  if (typeof window === "undefined") return DEFAULT_THEME
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return isValidTheme(stored) ? stored : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function setStoredTheme(theme: ThemeId): void {
  if (typeof window === "undefined") return
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // private browsing / storage full — diam
  }
}

export function clearStoredTheme(): void {
  if (typeof window === "undefined") return
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // diam
  }
}
