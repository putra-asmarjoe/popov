import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

// ── Types: contract GET /api/v1/llm/usage/{request_id} (Fix #302) ─────────────
// Catatan: endpoint SELALU 200, bahkan untuk request_id tak dikenal —
// total_calls: 0 + models: [] adalah kondisi normal (turn non-LLM), bukan error.

export interface LlmModelUsage {
  provider: string
  model: string
  calls: number
  ok: number
  error: number
  timeout: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  total_latency_ms: number
}

export interface LlmUsageResult {
  request_id: string
  total_calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  total_latency_ms: number
  models: LlmModelUsage[]
}

/** Agregat penggunaan LLM untuk satu chat turn (request_id = satu balasan). */
export function useLlmUsage(requestId: string | null) {
  return useQuery({
    queryKey: ["llm-usage", requestId],
    queryFn: async () => (await api.get(`/llm/usage/${requestId}`)).data as LlmUsageResult,
    enabled: !!requestId,
    staleTime: 30_000,
  })
}
