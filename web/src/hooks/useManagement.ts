import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"

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
  embedding: { mode: "local" | "provider"; provider?: string | null; model?: string }
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
  const invalidate = () => qc.invalidateQueries({ queryKey: ["config", "services"] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, "Operasi service gagal"))

  const create = useMutation({
    mutationFn: async (input: Partial<ManagedService>) =>
      (await api.post("/config/services", input)).data,
    onSuccess: () => { toast.success("Service ditambahkan"); invalidate() },
    onError,
  })
  const update = useMutation({
    mutationFn: async ({ service_id, ...input }: Partial<ManagedService> & { service_id: string }) =>
      (await api.patch(`/config/services/${service_id}`, input)).data,
    onSuccess: () => { toast.success("Service diperbarui"); invalidate() },
    onError,
  })
  const remove = useMutation({
    mutationFn: async (service_id: string) =>
      (await api.delete(`/config/services/${service_id}`)).data,
    onSuccess: () => { toast.success("Service dihapus"); invalidate() },
    onError,
  })
  return { create, update, remove }
}

// ── LLM ───────────────────────────────────────────────────────────────────────

export function useLlmConfig() {
  return useQuery({
    queryKey: ["config", "llm"],
    queryFn: async () => (await api.get("/config/llm")).data as LlmConfig,
  })
}

export function useUpdateLlm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      provider?: string
      model?: string
      models?: Record<string, string> // Fix #56
      baseUrls?: Record<string, string>
      apiKey?: Record<string, string>
      embedding?: { mode: string; provider?: string; model?: string }
    }) => (await api.put("/config/llm", input)).data as LlmConfig,
    onSuccess: (data) => {
      toast.success("Konfigurasi LLM tersimpan — berlaku langsung")
      qc.setQueryData(["config", "llm"], data)
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menyimpan konfigurasi LLM")),
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
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (episodeId: string) =>
      (await api.delete(`/brain/episodes/${episodeId}`)).data,
    onSuccess: () => {
      toast.success("Episode dihapus")
      qc.invalidateQueries({ queryKey: ["brain", "episodes"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menghapus episode")),
  })
}

// ── Observability Targets (SCALE Layer 2: multi-stack + webhook per-tenant) ──

export interface ObservabilityTarget {
  observ_id: string
  name: string
  kind?: "prometheus" | "tempo" | "alertmanager" | "loki" | null   // Fix #45 typed stacks
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
}

export interface ObservabilityTargetCreateInput {
  name: string
  kind?: "prometheus" | "tempo" | "alertmanager" | "loki" | null
  workspace_id?: string | null
  project_ids?: string[]
  alertmanager_url?: string
  prometheus_url?: string
  tempo_url?: string
  loki_url?: string
  webhook_mode?: boolean
  poll_interval_seconds?: number
}

export function useObservabilityTargets() {
  return useQuery({
    queryKey: ["config", "observability-targets"],
    queryFn: async () => {
      const { data } = await api.get("/config/observability-targets")
      return data.targets as ObservabilityTarget[]
    },
  })
}

export function useObservabilityTargetMutations() {
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: ["config", "observability-targets"] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, "Operasi observability target gagal"))

  const create = useMutation({
    mutationFn: async (input: ObservabilityTargetCreateInput) =>
      (await api.post("/config/observability-targets", input)).data as {
        target: ObservabilityTarget
        webhook_token: string
        alertmanager_snippet: string
      },
    onSuccess: (data) => {
      toast.success("Observability stack ditambahkan — copy snippet Alertmanager sekarang (token hanya tampil sekali)")
      invalidate()
      return data
    },
    onError,
  })

  const update = useMutation({
    mutationFn: async ({ observ_id, ...input }: Partial<ObservabilityTargetCreateInput> & { observ_id: string }) =>
      (await api.patch(`/config/observability-targets/${observ_id}`, input)).data,
    onSuccess: () => { toast.success("Stack diperbarui"); invalidate() },
    onError,
  })

  const remove = useMutation({
    mutationFn: async (observ_id: string) => (await api.delete(`/config/observability-targets/${observ_id}`)).data,
    onSuccess: () => { toast.success("Stack dihapus"); invalidate() },
    onError,
  })

  const rotateToken = useMutation({
    mutationFn: async (observ_id: string) =>
      (await api.post(`/config/observability-targets/${observ_id}/rotate-token`)).data as {
        webhook_token: string
        alertmanager_snippet: string
      },
    onSuccess: () => toast.success("Token baru dibuat — token lama tidak berlaku"),
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

export function useTestConnection() {
  return useMutation({
    mutationFn: async (observ_id: string) =>
      (await api.post(`/config/observability-targets/${observ_id}/test-connection`)).data as {
        overall: "ok" | "degraded" | "not_configured"
        sources: Record<string, { status: string }>
      },
    onSuccess: (d) => {
      if (d.overall === "ok") toast.success("Semua sumber terhubung")
      else if (d.overall === "not_configured") toast.info("Belum ada URL yang dikonfigurasi")
      else toast.warning(`Sebagian sumber bermasalah (${d.overall})`)
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Test koneksi gagal")),
  })
}

export function useTestTargetConnection() {
  return useMutation({
    mutationFn: async (observ_id: string) =>
      (await api.post(`/config/observability-targets/${observ_id}/test-connection`)).data as {
        overall: "ok" | "degraded" | "not_configured"
        sources: Record<string, { status: string }>
      },
    onSuccess: (d) => {
      if (d.overall === "ok") toast.success("Semua sumber terhubung")
      else toast.warning(`Status: ${d.overall}`)
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Test koneksi gagal")),
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
}

export function useWsRegistryMutations(wsId?: string) {
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: ["config", "ws-registry", wsId] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, "Operasi registry gagal"))

  const create = useMutation({
    mutationFn: async (input: RegistryInput) =>
      (await api.post(`/config/workspaces/${wsId}/service-registry`, input)).data as { item: WsRegistryItem },
    onSuccess: () => { toast.success("Service terdaftar di workspace"); invalidate() },
    onError,
  })

  const update = useMutation({
    mutationFn: async ({ registry_id, ...input }: RegistryInput & { registry_id: string }) =>
      (await api.patch(`/config/workspaces/${wsId}/service-registry/${registry_id}`, input)).data,
    onSuccess: () => { toast.success("Registry diperbarui"); invalidate() },
    onError,
  })

  const remove = useMutation({
    mutationFn: async (registry_id: string) =>
      (await api.delete(`/config/workspaces/${wsId}/service-registry/${registry_id}`)).data,
    onSuccess: () => { toast.success("Registry dihapus"); invalidate() },
    onError,
  })

  const testConnection = useMutation({
    mutationFn: async (registry_id: string) =>
      (await api.post(`/config/workspaces/${wsId}/service-registry/${registry_id}/test-connection`)).data as {
        overall: string
      },
    onSuccess: (d) => {
      if (d.overall === "ok") toast.success("Koneksi DB log OK")
      else if (d.overall === "not_configured") toast.info("Koneksi log belum diisi")
      else toast.warning(`Status koneksi: ${d.overall}`)
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
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: ["config", "observability-targets"] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, "Operasi link stack-project gagal"))

  const link = useMutation({
    mutationFn: async ({ observ_id, project_id }: { observ_id: string; project_id: string }) =>
      (await api.post(`/config/observability-targets/${observ_id}/link-project`, { project_id })).data as {
        ok: boolean; replaced?: string[]
      },
    onSuccess: (d) => {
      if (d.replaced?.length) toast.info(`Stack lain sejenis dilepas otomatis (${d.replaced.length})`)
      else toast.success("Stack ter-link ke project")
      invalidate()
    },
    onError,
  })

  const unlink = useMutation({
    mutationFn: async ({ observ_id, project_id }: { observ_id: string; project_id: string }) =>
      (await api.post(`/config/observability-targets/${observ_id}/unlink-project`, { project_id })).data,
    onSuccess: () => { toast.success("Link stack-project dilepas"); invalidate() },
    onError,
  })

  return { link, unlink }
}


// ── Fix #47: link/unlink project ↔ notification channel (atomik) ─────────────

export function useNtfProjectLinks() {
  const qc = useQueryClient()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["workspaces"] })
    qc.invalidateQueries({ queryKey: ["project-notification-channels"] })
  }
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, "Operasi link notifikasi gagal"))

  const link = useMutation({
    mutationFn: async ({ notif_id, project_id }: { notif_id: string; project_id: string }) =>
      (await api.post(`/config/notification-targets/${notif_id}/link-project`, { project_id })).data,
    onSuccess: () => { toast.success("Channel ter-link ke project"); invalidate() },
    onError,
  })

  const unlink = useMutation({
    mutationFn: async ({ notif_id, project_id }: { notif_id: string; project_id: string }) =>
      (await api.post(`/config/notification-targets/${notif_id}/unlink-project`, { project_id })).data,
    onSuccess: () => { toast.success("Link channel-project dilepas"); invalidate() },
    onError,
  })

  return { link, unlink }
}
