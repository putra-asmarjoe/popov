import axios from "axios"
import { clearToken, getToken } from "@/lib/auth"

// Dev: Vite proxy /api → http://localhost:8000 (lihat vite.config.ts)
// Prod: build diserve FastAPI (same-origin) — "/api/v1" tetap benar.
// VITE_API_BASE_URL hanya untuk deployment terpisah (opsional).
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
})

// Request: injeksi Bearer token
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response: 401 → bersihkan sesi + paksa ke /login
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      clearToken()
      if (!window.location.pathname.startsWith("/login")) {
        window.location.assign("/login")
      }
    }
    return Promise.reject(error)
  },
)

/** Ambil pesan error yang ramah dari respons axios (FastAPI {detail}). */
export function apiErrorMessage(error: unknown, fallback = "Terjadi kesalahan"): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === "string") return detail
  }
  return fallback
}
