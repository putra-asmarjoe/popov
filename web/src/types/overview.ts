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
}