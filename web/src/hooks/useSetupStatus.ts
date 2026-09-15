import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

/** Shape GET /setup/status — stabil, dipakai SetupGate + SetupWizard (Fix #294). */
export interface SetupStatus {
  status: "ok" | "degraded"
  needs_setup: boolean
  needs_configuration: boolean
  configured: boolean
  mongodb: { connected: boolean; db: string; error: string | null }
  encryption_key: { set: boolean; valid: boolean }
  jwt_secret: { set: boolean; strong: boolean; is_default: boolean }
  first_user_registered: boolean
}

/**
 * useSetupStatus — status env + first-launch untuk setup gate.
 * Tidak refetch di window focus: ini setup time, bukan live data.
 * Recheck manual/polling via `refetch()`.
 */
export function useSetupStatus() {
  return useQuery<SetupStatus>({
    queryKey: ["setup-status"],
    queryFn: async () => (await api.get<SetupStatus>("/setup/status")).data,
    staleTime: 30_000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
    refetchOnWindowFocus: false,
  })
}
