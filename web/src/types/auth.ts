export type UserRole = "admin" | "member"

export interface User {
  id: string
  name: string
  email: string
  role: UserRole
  localePreference?: string // "en" | "id" — dari backend (public_user)
  createdAt?: string
}

export interface AuthResponse {
  token: string
  user: User
}
