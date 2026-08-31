/** War Room — tipe data dari GET /api/v1/tickets/{id}/warroom (backend verified). */

export interface WarroomPillar {
  status: "ran" | "skipped"
  summary: string | null
  duration_ms: number | null
}

export interface WarroomTimelineStep {
  agent: string
  order: number | null
  duration_ms: number | null
}

export interface WarroomDiagnosis {
  hypothesis: string
  confidence: number
  correlation_summary: string
  data_gaps: string[]
  suggested_next: string[]
}

export interface WarroomRun {
  request_id: string | null
  channel: string | null
  investigated_at: string | null
  diagnosis: WarroomDiagnosis
  pillars: Record<"mongo" | "metrics" | "trace" | "span", WarroomPillar>
  timeline: WarroomTimelineStep[]
}

export interface WarroomEpisode {
  root_cause: string | null
  confidence: number
  correlation_result: string | null
  resolution_actions: string[]
  actual_ttr_minutes: number | null
}

export interface WarroomSecondBrain {
  episode_id: string | null
  service_name: string | null
  root_cause: string | null
  similarity: number | null
  timestamp: string | null
  created_at: string | null
  resolution_actions: string[]
  actual_ttr_minutes: number | null
}

export interface WarroomResponse {
  ticket_id: string
  ticket_number: string
  service_name: string | null
  source: "request_logs" | "incident_episodes" | "none"
  runs: WarroomRun[]
  episode: WarroomEpisode | null
  second_brain: WarroomSecondBrain[]
  meta: {
    investigated_at: string | null
    channel: string | null
    generated_at: string
  }
}