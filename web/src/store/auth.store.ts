import { create } from "zustand"
import { api } from "@/lib/api"
import { clearToken, getToken, setToken } from "@/lib/auth"
import { applyBackendLocale } from "@/lib/i18n"
import type { User } from "@/types/auth"

interface AuthStore {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  // true setelah pengecekan sesi awal selesai (hindari redirect palsu saat reload)
  sessionChecked: boolean

  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => void
  setUser: (user: User) => void
  setSessionChecked: (checked: boolean) => void
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  sessionChecked: false,

  async login(email, password) {
    const { data } = await api.post("/auth/login", { email, password })
    setToken(data.token)
    set({ user: data.user, token: data.token, isAuthenticated: true })
    void applyBackendLocale(data.user.localePreference)
  },

  async register(name, email, password) {
    const { data } = await api.post("/auth/register", { name, email, password })
    setToken(data.token)
    set({ user: data.user, token: data.token, isAuthenticated: true })
    void applyBackendLocale(data.user.localePreference)
  },

  logout() {
    clearToken()
    set({ user: null, token: null, isAuthenticated: false })
  },

  setUser(user) {
    set({ user, token: getToken(), isAuthenticated: true })
  },

  setSessionChecked(checked) {
    set({ sessionChecked: checked })
  },
}))
