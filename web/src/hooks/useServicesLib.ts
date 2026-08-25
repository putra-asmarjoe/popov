import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"
import type {
  ProjectServiceRef,
  ServiceKnowledgeLink,
  ServiceLibraryItem,
  ServiceRegistryEntry,
  ServiceUsage,
  WorkspaceServiceGroup,
} from "@/types/service"

// ── Registry global (dropdown validasi) ───────────────────────────────────────

export function useServiceRegistry() {
  return useQuery({
    queryKey: ["services", "registry"],
    queryFn: async () => {
      const { data } = await api.get("/services/registry")
      return data.services as ServiceRegistryEntry[]
    },
    staleTime: 5 * 60 * 1000,
  })
}

// ── Library pribadi ───────────────────────────────────────────────────────────

export function useMyServices() {
  return useQuery({
    queryKey: ["services", "library"],
    queryFn: async () => {
      const { data } = await api.get("/services/library")
      return data.items as ServiceLibraryItem[]
    },
  })
}

export interface ServiceDbConfig {
  type: "mongodb" | "mysql"
  uri: string
  db: string
  collection?: string
}

export interface ServiceInput {
  service_id?: string
  label?: string
  description?: string
  // Fix #38: koneksi log transaksi per-service (opsional) — service bebas dibuat
  db_config?: ServiceDbConfig | null
}

export function useCreateService() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: Required<Pick<ServiceInput, "service_id">> & ServiceInput) =>
      (await api.post("/services/library", input)).data as ServiceLibraryItem,
    onSuccess: (item) => {
      toast.success(`Service "${item.serviceId}" tersimpan di library`)
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menyimpan service")),
  })
}

export function useUpdateService() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: ServiceInput & { id: string }) =>
      (await api.patch(`/services/library/${id}`, input)).data as ServiceLibraryItem,
    onSuccess: () => {
      toast.success("Service diperbarui")
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal memperbarui service")),
  })
}

export interface DeleteServiceResult {
  needsConfirm?: boolean
  projects?: ServiceUsage[]
}

/** Hapus service library; 409 bila masih dipakai project → caller tampilkan warning. */
export function useDeleteService(): UseMutationResult<
  { deleted: string; refsRemoved: number },
  unknown,
  { id: string; confirm?: boolean }
> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, confirm = false }) => {
      const { data } = await api.delete(`/services/library/${id}`, {
        params: confirm ? { confirm: true } : {},
      })
      return data as { deleted: string; refsRemoved: number }
    },
    onSuccess: (data) => {
      toast.success(
        data.refsRemoved > 0
          ? `Service dihapus beserta ${data.refsRemoved} link project`
          : "Service dihapus",
      )
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menghapus service")),
  })
}

export async function fetchServiceUsage(id: string): Promise<ServiceUsage[]> {
  const { data } = await api.get(`/services/library/${id}/usage`)
  return data.usage as ServiceUsage[]
}

// ── Knowledge links pada service ──────────────────────────────────────────────

export function useServiceKnowledge(serviceId: string | null) {
  return useQuery({
    queryKey: ["services", "library", serviceId, "knowledge"],
    queryFn: async () => {
      const { data } = await api.get(`/services/library/${serviceId}/knowledge`)
      return data.links as ServiceKnowledgeLink[]
    },
    enabled: !!serviceId,
  })
}

export function useLinkServiceKnowledge(serviceId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (knowledgeLibraryId: string) => {
      const { data } = await api.post(`/services/library/${serviceId}/knowledge`, {
        knowledgeLibraryId,
      })
      return data as ServiceKnowledgeLink
    },
    onSuccess: (link) => {
      toast.success(`"${link.name}" ter-link ke service`)
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menambahkan knowledge")),
  })
}

export function useUnlinkServiceKnowledge(serviceId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (refId: string) =>
      (await api.delete(`/services/library/${serviceId}/knowledge/${refId}`)).data,
    onSuccess: () => {
      toast.success("Knowledge dilepas dari service")
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal melepas knowledge")),
  })
}

// ── Services dalam project ────────────────────────────────────────────────────

export function useProjectServices(projectId: string | null) {
  return useQuery({
    queryKey: ["services", "project", projectId],
    queryFn: async () => {
      const { data } = await api.get(`/services/projects/${projectId}`)
      return data.items as ProjectServiceRef[]
    },
    enabled: !!projectId,
  })
}

export function useLinkServiceToProject(projectId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (libraryServiceId: string) => {
      const { data } = await api.post(`/services/projects/${projectId}`, { libraryServiceId })
      return data as ProjectServiceRef
    },
    onSuccess: (ref) => {
      toast.success(`Service "${ref.serviceId}" ditambahkan ke project`)
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menambahkan service")),
  })
}

export function useUnlinkServiceFromProject(projectId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (refId: string) =>
      (await api.delete(`/services/projects/${projectId}/${refId}`)).data,
    onSuccess: () => {
      toast.success("Service dilepas dari project (library tetap utuh)")
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal melepas service")),
  })
}

// ── FE-8.1: agregasi workspace + mutasi flexible (project dipilih saat aksi) ──

export function useWorkspaceServiceGroups(wsId: string | null) {
  return useQuery({
    queryKey: ["services", "workspace", wsId],
    queryFn: async () => {
      const { data } = await api.get(`/services/workspace/${wsId}`)
      return data.groups as WorkspaceServiceGroup[]
    },
    enabled: !!wsId,
  })
}

/** Link service ke project — projectId bagian dari variabel (untuk settings). */
export function useLinkServiceFlexible() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, libraryServiceId }: { projectId: string; libraryServiceId: string }) => {
      const { data } = await api.post(`/services/projects/${projectId}`, { libraryServiceId })
      return data as ProjectServiceRef
    },
    onSuccess: (ref) => {
      toast.success(`Service "${ref.serviceId}" ditambahkan ke project`)
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menambahkan service")),
  })
}

/** Lepas service dari project — projectId bagian dari variabel. */
export function useUnlinkServiceFlexible() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, refId }: { projectId: string; refId: string }) =>
      (await api.delete(`/services/projects/${projectId}/${refId}`)).data,
    onSuccess: () => {
      toast.success("Service dilepas dari project (library tetap utuh)")
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal melepas service")),
  })
}

/** FE-8.2: hapus koneksi knowledge → service (owner service). */
export function useUnlinkKnowledgeFromService() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ serviceLibraryId, refId }: { serviceLibraryId: string; refId: string }) =>
      (await api.delete(`/services/library/${serviceLibraryId}/knowledge/${refId}`)).data,
    onSuccess: () => {
      toast.success("Koneksi knowledge dilepas dari service (dokumen tetap di library)")
      qc.invalidateQueries({ queryKey: ["services"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal melepas koneksi — hanya pemilik service")),
  })
}
