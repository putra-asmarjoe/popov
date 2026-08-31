import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"
import type { KnowledgeFolder, KnowledgeItem, KnowledgeUsage, WorkspaceKnowledgeRef, AgentDoc, AgentDocRef } from "@/types/knowledge"

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseContentTooLong(error: unknown): { maxChars: number; actual: number } | null {
  const msg = apiErrorMessage(error, "")
  const match = msg.match(/content_too_long\|max_chars=(\d+)\|actual=(\d+)/)
  if (match) return { maxChars: parseInt(match[1]), actual: parseInt(match[2]) }
  return null
}

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

export function useManagementLibrary() {
  return useQuery({
    queryKey: ["knowledge", "management-library"],
    queryFn: async () => {
      const { data } = await api.get("/knowledge/management-library")
      return data.items as KnowledgeItem[]
    },
  })
}

export function useGroundingDocs() {
  return useQuery({
    queryKey: ["knowledge", "grounding-docs"],
    queryFn: async () => {
      const { data } = await api.get("/docs/agent-docs")
      return data.docs as AgentDoc[]
    },
  })
}

export interface KnowledgeInput {
  name: string
  folder: KnowledgeFolder
  content: string
  meta?: Record<string, any>
}

export function useCreateKnowledge() {
  const { t } = useTranslation("management")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: KnowledgeInput) =>
      (await api.post("/knowledge/library", input)).data as KnowledgeItem,
    onSuccess: (item) => {
      toast.success(t("knowledge_lib.saved", { name: item.name }))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => {
      const tooLong = parseContentTooLong(e)
      if (tooLong) {
        toast.error(t("knowledge_lib.content_too_long", { maxChars: tooLong.maxChars, actual: tooLong.actual }))
      } else {
        toast.error(apiErrorMessage(e, t("knowledge_lib.save_failed")))
      }
    },
  })
}

export function useUpdateKnowledge() {
  const { t } = useTranslation("management")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: KnowledgeInput & { id: string }) =>
      (await api.patch(`/knowledge/library/${id}`, input)).data as KnowledgeItem,
    onSuccess: () => {
      toast.success(t("knowledge_lib.updated"))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => {
      const tooLong = parseContentTooLong(e)
      if (tooLong) {
        toast.error(t("knowledge_lib.content_too_long", { maxChars: tooLong.maxChars, actual: tooLong.actual }))
      } else {
        toast.error(apiErrorMessage(e, t("knowledge_lib.update_failed")))
      }
    },
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
  const { t } = useTranslation("management")
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
          ? t("knowledge_lib.deleted_with_refs", { count: data.refsRemoved })
          : t("knowledge_lib.deleted"),
      )
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("knowledge_lib.delete_failed"))),
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

export interface WorkspaceKnowledgeSummary {
  workspace_refs: number
  service_knowledge: number
  agent_docs: number
  total: number
  has: boolean
}

/** Keberadaan knowledge workspace: workspace refs + service knowledge + grounding docs. */
export function useWorkspaceKnowledgeSummary(wsId: string | null) {
  return useQuery({
    queryKey: ["knowledge", "ws-summary", wsId],
    queryFn: async () => {
      const { data } = await api.get(`/knowledge/workspaces/${wsId}/summary`)
      return data as WorkspaceKnowledgeSummary
    },
    enabled: !!wsId,
  })
}

export function useLinkKnowledge(wsId: string | null) {
  const { t } = useTranslation("management")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (libraryId: string) => {
      const { data } = await api.post(`/knowledge/workspaces/${wsId}`, { libraryId })
      return data as WorkspaceKnowledgeRef
    },
    onSuccess: (ref) => {
      toast.success(t("knowledge_lib.linked", { name: ref.name }))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("knowledge_lib.link_failed"))),
  })
}

export function useUnlinkKnowledge(wsId: string | null) {
  const { t } = useTranslation("management")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (refId: string) =>
      (await api.delete(`/knowledge/workspaces/${wsId}/${refId}`)).data,
    onSuccess: () => {
      toast.success(t("knowledge_lib.unlinked"))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("knowledge_lib.unlink_failed"))),
  })
}

// ── Workspace Knowledge (CRUD spesifik workspace) ──────────────────────────────

export interface WorkspaceKnowledgeItem {
  id: string
  workspaceId: string
  ownerId: string
  name: string
  folder: string
  sizeBytes?: number
  createdAt?: string
  updatedAt?: string
  content?: string
}

export function useWorkspaceItems(wsId: string | null) {
  return useQuery({
    queryKey: ["knowledge", "ws-items", wsId],
    queryFn: async () => {
      const { data } = await api.get(`/knowledge/workspaces/${wsId}`)
      return {
        items: (data.items ?? []) as WorkspaceKnowledgeRef[],
        workspaceItems: (data.workspaceItems ?? []) as WorkspaceKnowledgeItem[],
      }
    },
    enabled: !!wsId,
  })
}

export function useCreateWorkspaceKnowledge(wsId: string | null) {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: { name: string; folder: string; content: string }) => {
      const { data } = await api.post(`/knowledge/workspaces/${wsId}/items`, input)
      return data as WorkspaceKnowledgeItem
    },
    onSuccess: (item) => {
      toast.success(t("knowledge.saved", { name: item.name }))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => {
      const tooLong = parseContentTooLong(e)
      if (tooLong) {
        toast.error(t("knowledge.content_too_long", { maxChars: tooLong.maxChars, actual: tooLong.actual }))
      } else {
        toast.error(apiErrorMessage(e, t("knowledge_lib.save_failed")))
      }
    },
  })
}

export function useUpdateWorkspaceKnowledge(wsId: string | null) {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: { id: string; name?: string; folder?: string; content?: string }) => {
      const { data } = await api.patch(`/knowledge/workspaces/${wsId}/items/${id}`, input)
      return data as WorkspaceKnowledgeItem
    },
    onSuccess: () => {
      toast.success(t("knowledge.updated"))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => {
      const tooLong = parseContentTooLong(e)
      if (tooLong) {
        toast.error(t("knowledge.content_too_long", { maxChars: tooLong.maxChars, actual: tooLong.actual }))
      } else {
        toast.error(apiErrorMessage(e, t("knowledge_lib.update_failed")))
      }
    },
  })
}

export function useDeleteWorkspaceKnowledge(wsId: string | null) {
  const { t } = useTranslation("management")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (itemId: string) => {
      const { data } = await api.delete(`/knowledge/workspaces/${wsId}/items/${itemId}`)
      return data as { deleted: string }
    },
    onSuccess: () => {
      toast.success(t("knowledge_lib.deleted"))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("knowledge_lib.delete_failed"))),
  })
}

// ── Agent Doc Refs (Grounding Docs → Workspace) ─────────────────────────────

export function useAgentDocRefs(wsId: string | null) {
  return useQuery({
    queryKey: ["knowledge", "agent-doc-refs", wsId],
    queryFn: async () => {
      const { data } = await api.get(`/knowledge/workspaces/${wsId}/agent-docs`)
      return data.items as AgentDocRef[]
    },
    enabled: !!wsId,
  })
}

export function useAvailableAgentDocs(wsId: string | null) {
  return useQuery({
    queryKey: ["knowledge", "available-agent-docs", wsId],
    queryFn: async () => {
      const { data } = await api.get(`/knowledge/workspaces/${wsId}/agent-docs/available`)
      return data.items as AgentDoc[]
    },
    enabled: !!wsId,
  })
}

export function useLinkAgentDoc(wsId: string | null) {
  const { t } = useTranslation("management")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ category, key }: { category: string; key: string }) => {
      const { data } = await api.post(`/knowledge/workspaces/${wsId}/agent-docs`, { category, key })
      return data as AgentDocRef
    },
    onSuccess: () => {
      toast.success(t("knowledge_lib.grounding_linked"))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("knowledge_lib.grounding_link_failed"))),
  })
}

export function useUnlinkAgentDoc(wsId: string | null) {
  const { t } = useTranslation("management")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (refId: string) =>
      (await api.delete(`/knowledge/workspaces/${wsId}/agent-docs/${refId}`)).data,
    onSuccess: () => {
      toast.success(t("knowledge_lib.grounding_unlinked"))
      qc.invalidateQueries({ queryKey: ["knowledge"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("knowledge_lib.grounding_unlink_failed"))),
  })
}
