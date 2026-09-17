import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"
import type { Project, Workspace, WorkspaceDetail } from "@/types/workspace"
import type { WorkspaceRole } from "@/types/workspace"

// ── Queries ───────────────────────────────────────────────────────────────────

export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const { data } = await api.get("/workspaces")
      return data.workspaces as Workspace[]
    },
  })
}

export function useWorkspaceDetail(workspaceId: string | null) {
  return useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: async () => {
      const { data } = await api.get(`/workspaces/${workspaceId}`)
      return data as WorkspaceDetail
    },
    enabled: !!workspaceId,
  })
}

export function useProjects(workspaceId: string | null) {
  return useQuery({
    queryKey: ["projects", workspaceId],
    queryFn: async () => {
      const { data } = await api.get(`/workspaces/${workspaceId}/projects`)
      return data.projects as Project[]
    },
    enabled: !!workspaceId,
  })
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useCreateWorkspace() {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) => {
      const { data } = await api.post("/workspaces", { name })
      return data as Workspace
    },
    onSuccess: (ws) => {
      toast.success(`Workspace "${ws.name}" dibuat`)
      qc.invalidateQueries({ queryKey: ["workspaces"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.workspace_create_failed"))),
  })
}

export function useCreateProject(workspaceId: string | null) {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: { name: string; key: string }) => {
      const { data } = await api.post(`/workspaces/${workspaceId}/projects`, input)
      return data as Project
    },
    onSuccess: (project) => {
      toast.success(`Project ${project.key} dibuat`)
      qc.invalidateQueries({ queryKey: ["projects", workspaceId] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.project_create_failed"))),
  })
}

export function useRenameProject(workspaceId: string | null) {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: { projectId: string; name: string }) => {
      const { data } = await api.patch(`/workspaces/${workspaceId}/projects/${input.projectId}`, {
        name: input.name,
      })
      return data as Project
    },
    onSuccess: (project) => {
      toast.success(`Project di-rename menjadi "${project.name}"`)
      qc.invalidateQueries({ queryKey: ["projects", workspaceId] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.project_rename_failed"))),
  })
}

export function useInviteMember(workspaceId: string | null) {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: { email: string; role: WorkspaceRole }) => {
      const { data } = await api.post(`/workspaces/${workspaceId}/members`, input)
      return data.member as { name: string; email: string }
    },
    onSuccess: (member) => {
      toast.success(`${member.name} ditambahkan ke workspace`)
      qc.invalidateQueries({ queryKey: ["workspace", workspaceId] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.member_invite_failed"))),
  })
}

export function useRemoveMember(workspaceId: string | null) {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (userId: string) => {
      await api.delete(`/workspaces/${workspaceId}/members/${userId}`)
    },
    onSuccess: () => {
      toast.success("Member dikeluarkan")
      qc.invalidateQueries({ queryKey: ["workspace", workspaceId] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.member_remove_failed"))),
  })
}

// ── FE-8.4: Soft-delete project (admin workspace) ────────────────────────────

export interface DeleteProjectResult {
  deleted: string
  slugRenamedTo: string
  servicesDetached: number
  targetsUpdated: number
}

export function useDeleteProject(): UseMutationResult<
  DeleteProjectResult,
  unknown,
  { wsId: string; projectId: string }
> {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ wsId, projectId }) => {
      const { data } = await api.delete(`/workspaces/${wsId}/projects/${projectId}`)
      return data as DeleteProjectResult
    },
    onSuccess: (data) => {
      toast.success(
        t("toasts.project_deleted", { services: data.servicesDetached, targets: data.targetsUpdated })
      )
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.project_delete_failed"))),
  })
}
