import type { ComponentType } from "react"
import { useCallback, useEffect, useState } from "react"
import { Activity, BellRing, Gauge, Layers, Ticket } from "lucide-react"
import { AlertFeedCard } from "@/components/project/AlertFeedCard"
import { StackHealthCard } from "@/components/project/StackHealthCard"
import { EpisodeTimeline } from "@/components/project/EpisodeTimeline"
import { TicketSummaryWidget } from "@/components/overview/TicketSummaryWidget"
import { ErrorRateCard } from "@/components/overview/ErrorRateCard"

/**
 * Registry widget Overview — titik plug-in developer.
 * ATURAN: widget/chart BARU WAJIB `defaultEnabled: false` (owner decision v3) —
 * muncul di customize sebagai item "add", tidak auto-render.
 */
export interface OverviewWidgetDef {
  id: string
  titleKey: string
  icon: ComponentType<{ className?: string }>
  size: 1 | 2 | 3 // kolom span (md+)
  component: ComponentType
  defaultEnabled: boolean
  /** slice overview yang dibutuhkan widget (ADA = butuh fetch `project-overview`).
   *  Dipakai gate query — widget di-disable tidak fetch. */
  dataKey?: string
  /** widget butuh query `tickets` (list tiket). Default false. */
  needsTickets?: boolean
}

export const OVERVIEW_WIDGETS: OverviewWidgetDef[] = [
  // ── EXISTING — default ON (muncul tanpa user tambah) ──
  { id: "tickets", titleKey: "overview.open_tickets", icon: Ticket, size: 1, component: TicketSummaryWidget, defaultEnabled: true, needsTickets: true },
  { id: "alerts", titleKey: "overview.alerts", icon: BellRing, size: 1, component: AlertFeedCard, defaultEnabled: true, dataKey: "alert_feed" },
  { id: "stack", titleKey: "overview.stack_health", icon: Activity, size: 1, component: StackHealthCard, defaultEnabled: true, dataKey: "stack_health" },
  { id: "episodes", titleKey: "overview.episodes", icon: Layers, size: 3, component: EpisodeTimeline, defaultEnabled: true, dataKey: "episode_timeline" },
  // ── BARU (implementasi ini) — default OFF (optional, user tambah sendiri) ──
  { id: "error_rate", titleKey: "overview.widgets.error_rate", icon: Gauge, size: 2, component: ErrorRateCard, defaultEnabled: false, dataKey: "episode_timeline" },
]

/** Apakah ada widget enabled yang butuh query overview (4 collection). */
export function widgetsNeedOverview(ids: string[]): boolean {
  return ids.some((id) => OVERVIEW_WIDGETS.find((w) => w.id === id)?.dataKey != null)
}

/** Apakah ada widget enabled yang butuh query list tiket. */
export function widgetsNeedTickets(ids: string[]): boolean {
  return ids.some((id) => OVERVIEW_WIDGETS.find((w) => w.id === id)?.needsTickets)
}

// ── Storage (localStorage, mirror theme-storage.ts) ──────────────────────────

const STORAGE_PREFIX = "popov:overview-widgets:"

export function defaultWidgetIds(): string[] {
  return OVERVIEW_WIDGETS.filter((w) => w.defaultEnabled).map((w) => w.id)
}

function readPrefs(projectId: string): string[] {
  if (typeof window === "undefined") return defaultWidgetIds()
  try {
    const raw = localStorage.getItem(`${STORAGE_PREFIX}${projectId}`)
    if (!raw) return defaultWidgetIds()
    const ids = JSON.parse(raw)
    if (!Array.isArray(ids)) return defaultWidgetIds()
    const known = new Set(OVERVIEW_WIDGETS.map((w) => w.id))
    const valid = ids.filter((id): id is string => typeof id === "string" && known.has(id))
    return valid.length ? valid : defaultWidgetIds()
  } catch {
    return defaultWidgetIds()
  }
}

/**
 * getWidgetPrefs — default = widget defaultEnabled (EXISTING saja).
 * - ada prefs tersimpan → pakai itu (authoritative)
 * - belum ada → fallback defaultEnabled: true
 * ⇒ widget baru (default OFF) TIDAK otomatis muncul walau prefs lama/baru.
 */
export function getWidgetPrefs(projectId: string): string[] {
  return readPrefs(projectId)
}

export function setWidgetPrefs(projectId: string, ids: string[]): void {
  if (typeof window === "undefined") return
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${projectId}`, JSON.stringify(ids))
  } catch {
    // private browsing / storage full — diam
  }
}

/** "Reset default" → hapus prefs → kembali ke set defaultEnabled: true. */
export function resetWidgetPrefs(projectId: string): void {
  if (typeof window === "undefined") return
  try {
    localStorage.removeItem(`${STORAGE_PREFIX}${projectId}`)
  } catch {
    // diam
  }
}

/** Hook prefs widget — state sync + persist localStorage per project. */
export function useWidgetPrefs(projectId: string | null | undefined) {
  const [enabled, setEnabled] = useState<string[]>(() =>
    projectId ? getWidgetPrefs(projectId) : defaultWidgetIds(),
  )
  useEffect(() => {
    if (projectId) setEnabled(getWidgetPrefs(projectId))
  }, [projectId])
  const update = useCallback(
    (ids: string[]) => {
      setEnabled(ids)
      if (projectId) setWidgetPrefs(projectId, ids)
    },
    [projectId],
  )
  const reset = useCallback(() => {
    if (projectId) resetWidgetPrefs(projectId)
    setEnabled(defaultWidgetIds())
  }, [projectId])
  return { enabled, update, reset }
}