import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"
import { useTranslation } from "react-i18next"

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ApiKey {
  id: string
  workspaceId: string
  name: string
  type: "web" | "public"
  key_prefix: string
  scopes: string[]
  created_by: string
  last_used_at: string | null
  expires_at: string | null
  rate_limit: number
  is_active: boolean
  created_at: string
}

export interface ApiKeyCreateResult {
  id: string
  name: string
  type: string
  key: string // ⚠️ ONLY shown at creation
  key_prefix: string
  scopes: string[]
  rate_limit: number
  expires_at: string | null
  created_at: string
}

export interface ApiKeyScopes {
  [key: string]: {
    description: string
    public: boolean
  }
}

export interface PublicEndpoint {
  method: string
  path: string
  scopes: string[]
  rate_limit: number
  description: string
}

// ── API Keys ──────────────────────────────────────────────────────────────────

export function useApiKeys(wsId: string | null) {
  return useQuery({
    queryKey: ["api-keys", wsId],
    queryFn: async () => {
      const { data } = await api.get(`/api-keys`, { params: { ws_id: wsId } })
      return data.items as ApiKey[]
    },
    enabled: !!wsId,
  })
}

export function useCreateApiKey() {
  const { t } = useTranslation("common")
  const qc = useQueryClient()

  return useMutation({
    mutationFn: async (input: {
      ws_id: string
      name: string
      key_type: "web" | "public"
      scopes?: string[]
      expires_at?: string | null
      rate_limit?: number
    }) => {
      const { data } = await api.post(`/api-keys`, input, {
        params: { ws_id: input.ws_id },
      })
      return data as ApiKeyCreateResult
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys"] })
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, t("toasts.api_key_create_failed"))),
  })
}

export function useRevokeApiKey() {
  const { t } = useTranslation("common")
  const qc = useQueryClient()

  return useMutation({
    mutationFn: async ({ ws_id, key_id }: { ws_id: string; key_id: string }) =>
      (await api.delete(`/api-keys/${key_id}`, { params: { ws_id } })).data,
    onSuccess: () => {
      toast.success(t("toasts.api_key_revoked"))
      qc.invalidateQueries({ queryKey: ["api-keys"] })
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, t("toasts.api_key_revoke_failed"))),
  })
}

export function useRotateApiKey() {
  const { t } = useTranslation("common")
  const qc = useQueryClient()

  return useMutation({
    mutationFn: async ({ ws_id, key_id }: { ws_id: string; key_id: string }) => {
      const { data } = await api.post(`/api-keys/${key_id}/rotate`, null, {
        params: { ws_id },
      })
      return data as ApiKeyCreateResult
    },
    onSuccess: () => {
      toast.success(t("toasts.api_key_rotated"))
      qc.invalidateQueries({ queryKey: ["api-keys"] })
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, t("toasts.api_key_rotate_failed"))),
  })
}

// ── Scopes & Endpoints ───────────────────────────────────────────────────────

export function useApiKeyScopes() {
  return useQuery({
    queryKey: ["api-keys", "scopes"],
    queryFn: async () => {
      const { data } = await api.get(`/api-keys/scopes/list`)
      return data.scopes as ApiKeyScopes
    },
  })
}

export function usePublicEndpoints() {
  return useQuery({
    queryKey: ["api-keys", "public-endpoints"],
    queryFn: async () => {
      const { data } = await api.get(`/api-keys/endpoints/public`)
      return data.endpoints as PublicEndpoint[]
    },
  })
}
