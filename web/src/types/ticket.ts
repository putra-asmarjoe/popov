// Data model tiket — dari popov-frontend-plan.md + field join/detail FE-3.

export type TicketSeverity = "critical" | "high" | "medium" | "low"
export type TicketStatus =
  | "new"
  | "open"
  | "in_progress"
  | "needs_review"
  | "resolved"
  | "closed"
export type TicketKind = "business_logic" | "infrastructure"
export type TicketEnvironment = "production" | "staging" | "development"
export type TicketSource = "manual" | "watchdog"

export interface ProgressEntry {
  id: string
  note: string
  by: string
  byName: string
  at: string
}

export interface AssigneeDetail {
  userId: string
  name: string
  email: string
}

/** Alert notifikasi ter-link ke tiket (1 tiket : N alert, Fix #86). */
export type AlertSeverity = "critical" | "warning" | "info"

export interface TicketAlert {
  id: string
  alertId: string
  ticketId: string
  serviceName: string
  name: string
  severity: AlertSeverity
  source: string
  traceIds: string[]
  occurredAt: string | null
  createdAt: string | null
}

export interface Ticket {
  id: string
  ticketNumber: number
  title: string
  description: string
  workspaceId: string
  projectId: string
  kind: TicketKind
  severity: TicketSeverity
  traceId: string | null
  environment: TicketEnvironment
  createdBy: string
  createdByName: string
  assignees: string[]
  assigneesDetail: AssigneeDetail[]
  status: TicketStatus
  resolvedAt: string | null
  resolvedBy: string | null
  resolvedByName: string | null
  tags: string[]
  progressLog: ProgressEntry[]
  source: TicketSource
  /** Fix #40: service asal insiden (auto-ticket watchdog) — filter list ?service= */
  serviceName: string | null
  /** Fix #86: counter alert ter-link (1 tiket : N alert) */
  alertsCount: number
  lastAlertAt: string | null
  createdAt: string
  updatedAt: string
}

export interface TicketListMeta {
  page: number
  limit: number
  total: number
  pages: number
}

// ── Konstanta transisi (mirror server) ────────────────────────────────────────

export const STATUS_CHAIN: Record<TicketStatus, number> = {
  new: 0,
  open: 1,
  in_progress: 2,
  needs_review: 3,
  resolved: 4,
  closed: 5,
}

/** Opsi status valid dari status saat ini (mirror valid_transition backend). */
export function nextStatuses(current: TicketStatus): TicketStatus[] {
  if (current === "closed") return []
  if (current === "resolved") return ["closed"]
  const all = Object.keys(STATUS_CHAIN) as TicketStatus[]
  // closed hanya dari resolved (server rule); sisanya forward jump bebas
  return all.filter(
    (s) => s !== "closed" && STATUS_CHAIN[s] > STATUS_CHAIN[current],
  )
}

export const SEVERITY_LABEL: Record<TicketSeverity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
}

export const STATUS_LABEL: Record<TicketStatus, string> = {
  new: "New",
  open: "Open",
  in_progress: "In Progress",
  needs_review: "Needs Review",
  resolved: "Resolved",
  closed: "Closed",
}

export const KIND_LABEL: Record<TicketKind, string> = {
  business_logic: "Business Logic",
  infrastructure: "Infrastructure",
}
