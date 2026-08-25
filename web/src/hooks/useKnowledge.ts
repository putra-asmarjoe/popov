import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"
import type { KnowledgeFolder, KnowledgeItem, KnowledgeUsage, WorkspaceKnowledgeRef } from "@/types/knowledge"

// ── Library Pribadi (milik uploader) ──────────────────────────────────────────

export function useMyLibrary() {
  return useQuery({
    queryKey: ["knowledge", "library"],
    queryFn: async () => {
      const { data } = await api.get("/knowledge/library")
      return data.items as KnowledgeItem[]
    },
  })
}

export interface KnowledgeInput {
  name: string
  folder: KnowledgeFolder
  content: string
}

export function useCreateKnowledge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: KnowledgeInput) =>
      (await api.post("/knowledge/library", input)).data as KnowledgeItem,
    onSuccess: (item) => {
      toast.success(`Knowledge "${item.name}" tersimpan di library`)
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menyimpan knowledge")),
  })
}

export function useUpdateKnowledge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: KnowledgeInput & { id: string }) =>
      (await api.patch(`/knowledge/library/${id}`, input)).data as KnowledgeItem,
    onSuccess: () => {
      toast.success("Knowledge diperbarui — semua workspace ter-link ikut versi baru")
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal memperbarui knowledge")),
  })
}

export interface DeleteKnowledgeResult {
  needsConfirm?: boolean
  workspaces?: KnowledgeUsage[]
}

/**
 * Hapus item library. Bila masih dipakai workspace dan confirm=false,
 * backend balas 409 + daftar workspace → hook melempar objek usage ke caller.
 */
export function useDeleteKnowledge(): UseMutationResult<
  { deleted: string; refsRemoved: number },
  unknown,
  { id: string; confirm?: boolean },
  DeleteKnowledgeResult
> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, confirm = false }) => {
      const { data } = await api.delete(`/knowledge/library/${id}`, {
        params: confirm ? { confirm: true } : {},
      })
      return data as { deleted: string; refsRemoved: number }
    },
    onSuccess: (data) => {
      toast.success(
        data.refsRemoved > 0
          ? `Dokumen dihapus beserta ${data.refsRemoved} link workspace`
          : "Dokumen dihapus",
      )
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menghapus knowledge")),
  })
}

/** Ambil daftar workspace pemakai (untuk warning sebelum hapus). */
export async function fetchKnowledgeUsage(id: string): Promise<KnowledgeUsage[]> {
  const { data } = await api.get(`/knowledge/library/${id}/usage`)
  return data.usage as KnowledgeUsage[]
}

// ── Knowledge Workspace ───────────────────────────────────────────────────────

export function useWorkspaceKnowledge(wsId: string | null) {
  return useQuery({
    queryKey: ["knowledge", "ws", wsId],
    queryFn: async () => {
      const { data } = await api.get(`/knowledge/workspaces/${wsId}`)
      return data.items as WorkspaceKnowledgeRef[]
    },
    enabled: !!wsId,
  })
}

export function useLinkKnowledge(wsId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (libraryId: string) => {
      const { data } = await api.post(`/knowledge/workspaces/${wsId}`, { libraryId })
      return data as WorkspaceKnowledgeRef
    },
    onSuccess: (ref) => {
      toast.success(`"${ref.name}" ter-link ke workspace`)
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal menambahkan knowledge")),
  })
}

export function useUnlinkKnowledge(wsId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (refId: string) =>
      (await api.delete(`/knowledge/workspaces/${wsId}/${refId}`)).data,
    onSuccess: () => {
      toast.success("Knowledge dilepas dari workspace (library tetap utuh)")
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, "Gagal melepas knowledge")),
  })
}
