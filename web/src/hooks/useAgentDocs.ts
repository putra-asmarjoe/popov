import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"

export const DOC_CATEGORIES = [
  { id: "general", label: "agent_docs.category.general" },
  { id: "services", label: "agent_docs.category.services" },
  { id: "playbooks", label: "agent_docs.category.playbooks" },
  { id: "schemas", label: "agent_docs.category.schemas" },
  { id: "connections", label: "agent_docs.category.connections" },
  { id: "observability", label: "agent_docs.category.observability" },
] as const

export type DocCategory = (typeof DOC_CATEGORIES)[number]["id"]

export interface AgentDocMeta {
  [k: string]: unknown
}

export interface AgentDoc {
  category: string
  key: string
  body_len: number
  updatedAt: string
  meta: AgentDocMeta
}

export interface AgentDocDetail extends AgentDoc {
  body: string
}

export function useAgentDocs(category: string) {
  return useQuery({
    queryKey: ["agent-docs", category],
    queryFn: async () => {
      const { data } = await api.get("/docs/agent-docs", { params: { category } })
      return data.docs as AgentDoc[]
    },
  })
}

export function useAgentDoc(category: string, key: string | null) {
  return useQuery({
    queryKey: ["agent-docs", category, key],
    enabled: !!key,
    queryFn: async () => {
      const { data } = await api.get(`/docs/agent-docs/${category}/${key}`)
      return data as AgentDocDetail
    },
  })
}

export function useAgentDocMutations() {
  const { t } = useTranslation("management")
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: ["agent-docs"] })
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, t("agent_docs.op_failed")))

  const create = useMutation({
    mutationFn: async (input: {
      category: string
      key: string
      meta?: Record<string, unknown>
      body?: string
    }) => (await api.post("/docs/agent-docs", input)).data,
    onSuccess: () => {
      toast.success(t("agent_docs.created"))
      invalidate()
    },
    onError,
  })

  const update = useMutation({
    mutationFn: async ({
      category,
      key,
      ...patch
    }: {
      category: string
      key: string
      meta?: Record<string, unknown>
      body?: string
    }) => (await api.patch(`/docs/agent-docs/${category}/${key}`, patch)).data,
    onSuccess: () => {
      toast.success(t("agent_docs.updated"))
      invalidate()
    },
    onError,
  })

  const remove = useMutation({
    mutationFn: async ({ category, key }: { category: string; key: string }) =>
      (await api.delete(`/docs/agent-docs/${category}/${key}`)).data,
    onSuccess: () => {
      toast.success(t("agent_docs.deleted"))
      invalidate()
    },
    onError,
  })

  const reload = useMutation({
    mutationFn: async () => (await api.post("/docs/agent-docs/reload")).data,
    onSuccess: (data: { source?: string }) => {
      toast.success(t("agent_docs.reloaded", { source: data.source ?? "db" }))
      invalidate()
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, t("agent_docs.reload_failed"))),
  })

  return { create, update, remove, reload }
}