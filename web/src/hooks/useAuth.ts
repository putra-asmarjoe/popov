import { useEffect } from "react"
import { api } from "@/lib/api"
import { getToken } from "@/lib/auth"
import { applyBackendLocale } from "@/lib/i18n"
import { useAuthStore } from "@/store/auth.store"
import type { User } from "@/types/auth"

/**
 * useAuth — login/logout/session-check.
 * Session check: bila ada token tapi user belum ada di store (mis. setelah reload),
 * ambil profil via GET /auth/me sekali saja.
 */
export function useAuth() {
  const {
    user,
    token,
    isAuthenticated,
    sessionChecked,
    login,
    register,
    logout,
    setUser,
    setSessionChecked,
  } = useAuthStore()

  useEffect(() => {
    if (sessionChecked) return
    const existing = getToken()
    if (!existing) {
      setSessionChecked(true)
      return
    }
    let cancelled = false
    api
      .get("/auth/me")
      .then((res) => {
        const user = res.data.user as User
        if (!cancelled) setUser(user)
        void applyBackendLocale(user.localePreference)
      })
      .catch(() => {
        // 401 sudah ditangani interceptor (clearToken + redirect)
      })
      .finally(() => {
        if (!cancelled) setSessionChecked(true)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionChecked])

  return { user, token, isAuthenticated, sessionChecked, login, register, logout }
}
