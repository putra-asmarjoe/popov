export interface ChatSession {
  id: string
  userId: string
  projectId: string | null
  ticketId: string | null
  title: string
  createdAt: string
  updatedAt: string
}

export interface ChatMessage {
  id: string
  sessionId: string
  role: "user" | "assistant"
  content: string
  meta?: Record<string, unknown>
  createdAt: string
}

/** Per-Agent Tracing (Fase 1) — satu node graph: agent, urutan, durasi, ringkasan hasil. */
export interface AgentTrace {
  agent: string
  order: number
  duration_ms: number | null
  summary: Record<string, unknown>
}

/** Konteks tiket aktif — di-inject ke pesan chat (frontend-side, sesuai plan FE-5). */
export interface TicketContext {
  ticketId: string
  ticketNumber: string // display "CORE-4"
  title: string
  traceId: string | null
  serviceName: string | null // Fix #49: subject service tiket (utk routing + prefix)
}
