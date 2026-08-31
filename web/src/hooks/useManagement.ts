import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"
import { useTranslation } from "react-i18next"

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ManagedService {
  service_id: string
  collection: string
  type: string | null
  uri: string | null
  db: string | null
  error_filter: Record<string, unknown> | null
  has_doc: boolean
}

export interface LlmConfig {
  provider: string
  model: string
  models: Record<string, string> // Fix #56: model PER provider
  baseUrls: Record<string, string>
  keys: Record<string, "set" | "unset">
  keysMasked: Record<string, string>
  embedding: { mode: "local" | "provider"; provider?: string | null; model?: string; maxChars?: number }
  restart_required?: boolean
}

export interface ObservabilityConfig {
  prometheus_url: string
  alertmanager_url: string
  tempo_url: string
  loki_url: string
  watchdog_interval_min: number
  observability_enabled: boolean
  restart_required?: boolean
}

// ── Services ──────────────────────────────────────────────────────────────────

export function useConfigServices() {
  return useQuery({
    queryKey: ["config", "services"],
    queryFn: async () => {
      const { data } = await api.get("/config/services")
      return data.services as ManagedService[]
    },
  })
}

export function useServiceMutations() {
  const qc = useQueryClient()
  const { t } = useTranslation("common")
  const invalidate = () => qc.invalidateQueries({ queryKey: ["config", "services"] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, t("toasts.svc_failed")))

  const create = useMutation({
    mutationFn: async (input: Partial<ManagedService>) =>
      (await api.post("/config/services", input)).data,
    onSuccess: () => { toast.success(t("toasts.svc_created")); invalidate() },
    onError,
  })
  const update = useMutation({
    mutationFn: async ({ service_id, ...input }: Partial<ManagedService> & { service_id: string }) =>
      (await api.patch(`/config/services/${service_id}`, input)).data,
    onSuccess: () => { toast.success(t("toasts.svc_updated")); invalidate() },
    onError,
  })
  const remove = useMutation({
    mutationFn: async (service_id: string) =>
      (await api.delete(`/config/services/${service_id}`)).data,
    onSuccess: () => { toast.success(t("toasts.svc_deleted")); invalidate() },
    onError,
  })
  return { create, update, remove }
}

// ── LLM ───────────────────────────────────────────────────────────────────────

export function useLlmConfig(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["config", "llm"],
    queryFn: async () => (await api.get("/config/llm")).data as LlmConfig,
    enabled: options?.enabled,
  })
}

export function useUpdateLlm() {
  const { t } = useTranslation("common")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      provider?: string
      model?: string
      models?: Record<string, string> // Fix #56
      baseUrls?: Record<string, string>
      apiKey?: Record<string, string>
      embedding?: { mode: string; provider?: string; model?: string; maxChars?: number }
    }) => (await api.put("/config/llm", input)).data as LlmConfig,
    onSuccess: (data) => {
      toast.success(t("toasts.llm_saved"))
      qc.setQueryData(["config", "llm"], data)
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.llm_save_failed"))),
  })
}

// ── Observability ─────────────────────────────────────────────────────────────

// ── Memory (Second Brain episodes) ────────────────────────────────────────────

export interface Episode {
  episode_id: string
  service_name?: string
  feedback?: string | null
  timestamp?: string
  symptoms_summary?: string
  root_cause?: string
  [key: string]: unknown
}

export function useEpisodes(service: string, status: string) {
  return useQuery({
    queryKey: ["brain", "episodes", service, status],
    queryFn: async () => {
      const { data } = await api.get("/brain/episodes", {
        params: { service: service || undefined, status, limit: 50 },
      })
      return data.episodes as Episode[]
    },
  })
}

export function useDeleteEpisode() {
  const { t } = useTranslation("common")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (episodeId: string) =>
      (await api.delete(`/brain/episodes/${episodeId}`)).data,
    onSuccess: () => {
      toast.success(t("toasts.episode_deleted"))
      qc.invalidateQueries({ queryKey: ["brain", "episodes"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.episode_delete_failed"))),
  })
}

// ── Observability Targets (SCALE Layer 2: multi-stack + webhook per-tenant) ──

export type ObsStackKind = "prometheus" | "tempo" | "alertmanager" | "loki" | "otel"

export interface ObservabilityTarget {
  observ_id: string
  name: string
  kind?: ObsStackKind | null   // Fix #45 typed stacks; "otel" = Central Log
  workspace_id: string | null
  project_ids: string[]
  alertmanager_url: string
  prometheus_url: string
  tempo_url: string
  loki_url?: string
  webhook_mode: boolean
  poll_interval_seconds: number
  enabled: boolean
  health_status: string | null
  last_health_check_at: string | null
  // kind="otel" (Central Log OTel) — URI hanya tersamar dari API (write-only)
  log_db_type?: "mongodb"
  log_db_uri_masked?: string
  log_db_name?: string
  span_collection?: string
  http_collection?: string
}

export interface ObservabilityTargetCreateInput {
  name: string
  kind?: ObsStackKind | null
  workspace_id?: string | null
  project_ids?: string[]
  alertmanager_url?: string
  prometheus_url?: string
  tempo_url?: string
  loki_url?: string
  webhook_mode?: boolean
  poll_interval_seconds?: number
  // kind="otel"
  log_db_type?: string
  log_db_uri?: string
  log_db_name?: string
  span_collection?: string
  http_collection?: string
}

export function useObservabilityTargets(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["config", "observability-targets"],
    queryFn: async () => {
      const { data } = await api.get("/config/observability-targets")
      return data.targets as ObservabilityTarget[]
    },
    enabled: options?.enabled,
  })
}

export function useObservabilityTargetMutations() {
  const qc = useQueryClient()
  const { t } = useTranslation("common")
  const invalidate = () => qc.invalidateQueries({ queryKey: ["config", "observability-targets"] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, t("toasts.obs_failed")))

  const create = useMutation({
    mutationFn: async (input: ObservabilityTargetCreateInput) =>
      (await api.post("/config/observability-targets", input)).data as {
        target: ObservabilityTarget
        webhook_token: string
        alertmanager_snippet: string
      },
    onSuccess: (data) => {
      toast.success(t("toasts.obs_created"))
      invalidate()
      return data
    },
    onError,
  })

  const update = useMutation({
    mutationFn: async ({ observ_id, ...input }: Partial<ObservabilityTargetCreateInput> & { observ_id: string }) =>
      (await api.patch(`/config/observability-targets/${observ_id}`, input)).data,
    onSuccess: () => { toast.success(t("toasts.obs_updated")); invalidate() },
    onError,
  })

  const remove = useMutation({
    mutationFn: async (observ_id: string) => (await api.delete(`/config/observability-targets/${observ_id}`)).data,
    onSuccess: () => { toast.success(t("toasts.obs_deleted")); invalidate() },
    onError,
  })

  const rotateToken = useMutation({
    mutationFn: async (observ_id: string) =>
      (await api.post(`/config/observability-targets/${observ_id}/rotate-token`)).data as {
        webhook_token: string
        alertmanager_snippet: string
      },
    onSuccess: () => toast.success(t("toasts.token_rotated")),
    onError,
  })

  return { create, update, remove, rotateToken }
}

/** Probe satu endpoint observability sebelum stack disimpan (create dialog). */
export function useTestTargetUrl() {
  return useMutation({
    mutationFn: async (input: { kind: string; url: string }) =>
      (await api.post("/config/observability-targets/test-url", input)).data as {
        status: string
        url?: string
      },
  })
}

/** Probe koneksi Central Log (kind=otel) sebelum stack disimpan — ping + cek db. */
export function useTestCentralLog() {
  return useMutation({
    mutationFn: async (input: { log_db_uri: string; log_db_name: string }) =>
      (await api.post("/config/observability-targets/test-central-log", input)).data as {
        overall: "ok" | "degraded" | "not_configured" | "error"
        sources: Record<string, { status: string; db_exists?: boolean | null }>
      },
  })
}

export function useTestConnection() {
  const { t } = useTranslation("common")
  return useMutation({
    mutationFn: async (observ_id: string) =>
      (await api.post(`/config/observability-targets/${observ_id}/test-connection`)).data as {
        overall: "ok" | "degraded" | "not_configured"
        sources: Record<string, { status: string }>
      },
    onSuccess: (d) => {
      if (d.overall === "ok") toast.success(t("toasts.all_sources_ok"))
      else if (d.overall === "not_configured") toast.info(t("toasts.no_url_configured"))
      else toast.warning(t("toasts.some_sources_degraded", { status: d.overall }))
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.test_failed"))),
  })
}

export function useTestTargetConnection() {
  const { t } = useTranslation("common")
  return useMutation({
    mutationFn: async (observ_id: string) =>
      (await api.post(`/config/observability-targets/${observ_id}/test-connection`)).data as {
        overall: "ok" | "degraded" | "not_configured"
        sources: Record<string, { status: string }>
      },
    onSuccess: (d) => {
      if (d.overall === "ok") toast.success(t("toasts.all_sources_ok"))
      else toast.warning(t("toasts.status_is", { status: d.overall }))
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.test_failed"))),
  })
}

// ── Workspace Service Registry (Fix #41: migrasi ⚙️ Monitoring Global) ──────

export interface WsRegistryItem {
  registry_id: string
  workspace_id: string
  service_id: string
  label: string
  db_config: { type: string; uri?: string; db?: string; collection?: string } | null
  enabled: boolean
}

export function useWsServiceRegistry(wsId?: string) {
  return useQuery({
    queryKey: ["config", "ws-registry", wsId],
    queryFn: async () => {
      const { data } = await api.get(`/config/workspaces/${wsId}/service-registry`)
      return data.items as WsRegistryItem[]
    },
    enabled: !!wsId,
  })
}

export interface RegistryInput {
  service_id?: string
  label?: string
  db_type?: string
  db_uri?: string
  db_name?: string
  db_collection?: string
  enabled?: boolean
  project_ids?: string[]
}

export function useWsRegistryMutations(wsId?: string) {
  const { t } = useTranslation("common")
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: ["config", "ws-registry", wsId] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, t("toasts.registry_failed")))

  const create = useMutation({
    mutationFn: async (input: RegistryInput) =>
      (await api.post(`/config/workspaces/${wsId}/service-registry`, input)).data as { item: WsRegistryItem },
    onSuccess: () => { toast.success(t("toasts.registry_created")); invalidate() },
    onError,
  })

  const update = useMutation({
    mutationFn: async ({ registry_id, ...input }: RegistryInput & { registry_id: string }) =>
      (await api.patch(`/config/workspaces/${wsId}/service-registry/${registry_id}`, input)).data,
    onSuccess: () => { toast.success(t("toasts.registry_updated")); invalidate() },
    onError,
  })

  const remove = useMutation({
    mutationFn: async (registry_id: string) =>
      (await api.delete(`/config/workspaces/${wsId}/service-registry/${registry_id}`)).data,
    onSuccess: () => { toast.success(t("toasts.registry_deleted")); invalidate() },
    onError,
  })

  const testConnection = useMutation({
    mutationFn: async (registry_id: string) =>
      (await api.post(`/config/workspaces/${wsId}/service-registry/${registry_id}/test-connection`)).data as {
        overall: string
      },
    onSuccess: (d) => {
      if (d.overall === "ok") toast.success(t("toasts.db_log_ok"))
      else if (d.overall === "not_configured") toast.info(t("toasts.db_log_not_set"))
      else toast.warning(t("toasts.conn_status", { status: d.overall }))
    },
    onError,
  })

  return { create, update, remove, testConnection }
}

// ── FE-8.7: daftar service registry workspace (untuk picker Projects) ────────

export function useWsRegistryList(workspaceId: string | null) {
  return useQuery({
    queryKey: ["config", "ws-registry", workspaceId],
    queryFn: async () => {
      const { data } = await api.get(`/config/workspaces/${workspaceId}/service-registry`)
      return data.items as WsRegistryItem[]
    },
    enabled: !!workspaceId,
  })
}

export function useStackProjectLinks() {
  const { t } = useTranslation("common")
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: ["config", "observability-targets"] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, t("toasts.link_failed")))

  const link = useMutation({
    mutationFn: async ({ observ_id, project_id }: { observ_id: string; project_id: string }) =>
      (await api.post(`/config/observability-targets/${observ_id}/link-project`, { project_id })).data as {
        ok: boolean; replaced?: string[]
      },
    onSuccess: (d) => {
      if (d.replaced?.length) toast.info(t("toasts.link_replaced", { count: d.replaced.length }))
      else toast.success(t("toasts.link_ok"))
      invalidate()
    },
    onError,
  })

  const unlink = useMutation({
    mutationFn: async ({ observ_id, project_id }: { observ_id: string; project_id: string }) =>
      (await api.post(`/config/observability-targets/${observ_id}/unlink-project`, { project_id })).data,
    onSuccess: () => { toast.success(t("toasts.unlink_ok")); invalidate() },
    onError,
  })

  return { link, unlink }
}


// ── Fix #47: link/unlink project ↔ notification channel (atomik) ─────────────

export function useNtfProjectLinks() {
  const { t } = useTranslation("common")
  const qc = useQueryClient()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["workspaces"] })
    qc.invalidateQueries({ queryKey: ["project-notification-channels"] })
  }
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, t("toasts.ntf_link_failed")))

  const link = useMutation({
    mutationFn: async ({ notif_id, project_id }: { notif_id: string; project_id: string }) =>
      (await api.post(`/config/notification-targets/${notif_id}/link-project`, { project_id })).data,
    onSuccess: () => { toast.success(t("toasts.ntf_link_ok")); invalidate() },
    onError,
  })

  const unlink = useMutation({
    mutationFn: async ({ notif_id, project_id }: { notif_id: string; project_id: string }) =>
      (await api.post(`/config/notification-targets/${notif_id}/unlink-project`, { project_id })).data,
    onSuccess: () => { toast.success(t("toasts.ntf_unlink_ok")); invalidate() },
    onError,
  })

  return { link, unlink }
}
