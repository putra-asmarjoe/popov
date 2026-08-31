import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"

// ── Notification Channels (Fix #40 — menggantikan hook global useManagement) ──
// Channel milik WORKSPACE; dikelola ws-admin di Workspace Settings → tab Notifikasi.
// Bot token TIDAK pernah dikembalikan API — hanya mask + metadata health.

export interface NotificationChannel {
  notif_id: string
  name: string
  channel: "telegram" | "email" // whatsapp/slack/discord = roadmap
  workspace_id: string | null
  project_ids: string[]
  enabled: boolean
  config?: {
    telegram?: {
      chat_id?: string
      bot_token_masked?: string | null
      botUsername?: string | null
      health_status?: "ok" | "error"
      last_health_check_at?: string
    }
    email?: {
      smtp_host?: string
      smtp_port?: number
      security?: "starttls" | "ssl" | "none"
      ignore_tls_error?: boolean
      disable_starttls?: boolean
      smtp_user?: string | null
      smtp_pass_masked?: string | null
      from_addr?: string
      to_addrs?: string[]
      cc_addrs?: string[]
      bcc_addrs?: string[]
      smtp_banner?: string | null
      health_status?: "ok" | "error"
      last_health_check_at?: string
    }
  }
  /** hanya ada pada GET /projects/{pid}/notification-channels */
  linked?: boolean
}

export interface ChannelTestResult {
  getMe?: { ok: boolean; bot_id?: number; username?: string; error?: string }
  smtp?: { ok: boolean; banner?: string; error?: string }
  test_sent: boolean
  error: string | null
}

// Input union — telegram | email (discriminated by channel)
export type ChannelCreateInput =
  | { channel: "telegram"; name: string; bot_token: string; chat_id: string; project_ids?: string[] }
  | {
      channel: "email"
      name: string
      smtp_host: string
      smtp_port: number
      security: "starttls" | "ssl" | "none"
      ignore_tls_error: boolean
      disable_starttls: boolean
      smtp_user?: string | null
      smtp_pass?: string | null
      from_addr: string
      to_addrs: string[]
      cc_addrs: string[]
      bcc_addrs: string[]
      project_ids?: string[]
    }

export type ChannelUpdateInput =
  | { name?: string; enabled?: boolean; bot_token?: string; chat_id?: string }
  | {
      name?: string
      enabled?: boolean
      smtp_host?: string
      smtp_port?: number
      security?: string
      ignore_tls_error?: boolean
      disable_starttls?: boolean
      smtp_user?: string | null
      smtp_pass?: string | null
      from_addr?: string
      to_addrs?: string[]
      cc_addrs?: string[]
      bcc_addrs?: string[]
    }

/** Error 409 delete: channel masih ter-link project (detail.projects berisi daftarnya). */
export class ChannelLinkedError extends Error {
  projects: { projectId: string; name: string }[]
  constructor(projects: { projectId: string; name: string }[]) {
    super("Channel masih ter-link ke project")
    this.projects = projects
  }
}

// ── Workspace-scoped (Settings → tab Notifikasi) ─────────────────────────────

export function useWorkspaceChannels(wsId: string | null) {
  return useQuery({
    queryKey: ["workspaces", wsId, "notification-channels"],
    enabled: !!wsId,
    queryFn: async () => {
      const { data } = await api.get(`/workspaces/${wsId}/notification-channels`)
      return data.channels as NotificationChannel[]
    },
  })
}

export function useChannelMutations(wsId: string | null) {
  const qc = useQueryClient()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["workspaces", wsId, "notification-channels"] })
    qc.invalidateQueries({ queryKey: ["project-notification-channels"] })
  }
  const onError = (e: unknown) => toast.error(apiErrorMessage(e))

  const create = useMutation({
    mutationFn: async (input: ChannelCreateInput) =>
      (await api.post(`/workspaces/${wsId}/notification-channels`, input)).data as {
        channel: NotificationChannel
      },
    onSuccess: () => {
      toast.success("Channel dibuat & kredensial tervalidasi")
      invalidate()
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal membuat channel (cek kredensial)")),
  })

  const update = useMutation({
    mutationFn: async ({ notif_id, ...input }: { notif_id: string } & ChannelUpdateInput) =>
      (await api.patch(`/notification-channels/${notif_id}`, input)).data,
    onSuccess: () => {
      toast.success("Channel diperbarui")
      invalidate()
    },
    onError,
  })

  // Tidak auto-toast: 409 (masih ter-link) ditangani komponen utk konfirmasi paksa
  const remove = useMutation({
    mutationFn: async ({ notif_id, confirm = false }: { notif_id: string; confirm?: boolean }) => {
      try {
        return (await api.delete(`/notification-channels/${notif_id}`, { params: { confirm } })).data
      } catch (e: unknown) {
        if (isAxios409(e)) {
          const detail = (e as { response?: { data?: { detail?: { projects?: { projectId: string; name: string }[] } } } })
            .response?.data?.detail
          throw new ChannelLinkedError(detail?.projects ?? [])
        }
        throw e
      }
    },
    onSuccess: () => {
      toast.success("Channel dihapus")
      invalidate()
    },
    onError: (e) => {
      if (!(e instanceof ChannelLinkedError)) toast.error(apiErrorMessage(e, "Gagal hapus channel"))
    },
  })

  const test = useMutation({
    mutationFn: async (notif_id: string) =>
      (await api.post(`/notification-channels/${notif_id}/test`)).data as ChannelTestResult,
    onSuccess: (d) => {
      // Telegram: d.getMe; Email: d.smtp — salah satu harus ada
      const probe = d.getMe ?? d.smtp
      if (!probe?.ok) toast.error(`Kredensial invalid: ${probe?.error ?? d.error ?? "?"}`)
      else if (d.test_sent) {
        if (d.getMe?.username) toast.success(`Tes terkirim via @${d.getMe.username}`)
        else toast.success("Tes terkirim via email")
      } else toast.warning(`Koneksi OK, tapi pesan tes gagal: ${d.error ?? "?"}`)
      invalidate()
    },
    onError,
  })

  return { create, update, remove, test }
}

// ── Test raw credentials (before save — create dialog) ───────────────────────

export interface TestCredentialsInput {
  channel: "telegram" | "email"
  bot_token?: string
  chat_id?: string
  smtp_host?: string
  smtp_port?: number
  security?: "starttls" | "ssl" | "none"
  ignore_tls_error?: boolean
  disable_starttls?: boolean
  smtp_user?: string
  smtp_pass?: string
}

export interface TestCredentialsResult {
  getMe?: { ok: boolean; bot_id?: number; username?: string; error?: string }
  smtp?: { ok: boolean; banner?: string; error?: string }
  error: string | null
}

export function useTestChannelCredentials() {
  return useMutation({
    mutationFn: async (input: TestCredentialsInput) =>
      (await api.post("/notification-channels/test-credentials", input)).data as TestCredentialsResult,
  })
}

// ── Project-scoped (ProjectNotificationSelector) ─────────────────────────────

export function useProjectChannels(projectId: string | null) {
  return useQuery({
    queryKey: ["project-notification-channels", projectId],
    enabled: !!projectId,
    queryFn: async () => {
      const { data } = await api.get(`/projects/${projectId}/notification-channels`)
      return data.channels as NotificationChannel[]
    },
  })
}

export function useLinkChannelMutations(projectId: string | null) {
  const qc = useQueryClient()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["project-notification-channels"] })
    qc.invalidateQueries({ queryKey: ["workspaces"] })
  }
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, "Gagal mengubah link channel"))

  const link = useMutation({
    mutationFn: async (notif_id: string) =>
      (await api.post(`/projects/${projectId}/notification-channels/${notif_id}`)).data,
    onSuccess: () => invalidate(),
    onError,
  })

  const unlink = useMutation({
    mutationFn: async (notif_id: string) =>
      (await api.delete(`/projects/${projectId}/notification-channels/${notif_id}`)).data,
    onSuccess: () => invalidate(),
    onError,
  })

  return { link, unlink }
}

function isAxios409(e: unknown): boolean {
  return (
    !!e &&
    typeof e === "object" &&
    (e as { response?: { status?: number } }).response?.status === 409
  )
}
