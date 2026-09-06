import type { WarroomSymptoms } from "./warroom"

/** Project Overview — GET /api/v1/projects/{id}/overview (backend verified). */

export interface OverviewTicket {
  id: string
  ticketNumber: number
  title: string
  severity: string
  severityRank: number | null
  status: string
  serviceName: string | null
  createdAt: string
}

export interface OverviewAlert {
  id: string
  message: string
  fingerprint: string | null
  service_name: string | null
  observ_id: string | null
  sent_at: string
  status: string | null
}

export interface OverviewEpisode {
  id: string
  episode_id: string | null
  service_name: string | null
  root_cause: string | null
  confidence: number | null
  created_at: string | null
  ticket_id: string | null
  actual_ttr_minutes: number | null
  enriched_at: string | null
  symptoms?: WarroomSymptoms | null
}

export interface StackHealth {
  id: string
  kind: string | null
  url: string
  health_status: string
  last_health_check_at: string | null
}

export interface ProjectOverviewData {
  project_id: string
  workspace_id: string
  project_key: string
  project_name: string
  ticket_summary: {
    open_count: number
    by_severity: Record<"critical" | "high" | "medium" | "low", number>
    recent: OverviewTicket[]
  }
  alert_feed: OverviewAlert[]
  episode_timeline: OverviewEpisode[]
  stack_health: StackHealth[]
  generated_at: string
  dashboard_stats?: DashboardStats
}

// ── Dashboard Stats ──────────────────────────────────────────────────────

export interface TrendPoint {
  date: string
  count: number
}

export interface TopService {
  service: string
  count: number
  worst_severity: "critical" | "high" | "medium" | "low"
}

export interface TopAlertType {
  name: string
  count: number
}

export interface DashboardStats {
  days: number
  ticket_counts_by_status: Record<string, number>
  ticket_counts_by_severity: Record<string, number>
  ticket_counts_by_kind: Record<string, number>
  tickets_created_trend: TrendPoint[]
  tickets_resolved_trend: TrendPoint[]
  top_services: TopService[]
  top_alert_types: TopAlertType[]
  mttr_seconds: number | null
  unassigned_open_count: number
  ai_investigated_count: number
  recurring_alerts_count: number
}