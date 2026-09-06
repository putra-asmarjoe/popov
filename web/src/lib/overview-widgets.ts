import type { ComponentType } from "react"
import { useCallback, useEffect, useState } from "react"
import { Activity, BellRing, Gauge, Layers, Ticket } from "lucide-react"
import { BarChart3, LayoutDashboard, Megaphone, PieChart as PieIcon, TrendingUp } from "lucide-react"
import { AlertFeedCard } from "@/components/project/AlertFeedCard"
import { StackHealthCard } from "@/components/project/StackHealthCard"
import { EpisodeTimeline } from "@/components/project/EpisodeTimeline"
import { TicketSummaryWidget } from "@/components/overview/TicketSummaryWidget"
import { ErrorRateCard } from "@/components/overview/ErrorRateCard"
import { DashboardStatCards } from "@/components/overview/DashboardStatCards"
import { TicketTrendChart } from "@/components/overview/TicketTrendChart"
import { SeverityDonutChart } from "@/components/overview/SeverityDonutChart"
import { TopServicesTable } from "@/components/overview/TopServicesTable"
import { TopAlertTypesTable } from "@/components/overview/TopAlertTypesTable"

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
  // ── DASHBOARD (default OFF — owner decision v3) ──
  { id: "dashboard_stat_cards", titleKey: "overview.widgets.dashboard_stats", icon: LayoutDashboard, size: 2, component: DashboardStatCards, defaultEnabled: false, dataKey: "dashboard_stats" },
  { id: "ticket_trend", titleKey: "overview.widgets.ticket_trend", icon: TrendingUp, size: 3, component: TicketTrendChart, defaultEnabled: false, dataKey: "dashboard_stats" },
  { id: "severity_donut", titleKey: "overview.widgets.severity_donut", icon: PieIcon, size: 2, component: SeverityDonutChart, defaultEnabled: false, dataKey: "dashboard_stats" },
  { id: "top_services", titleKey: "overview.widgets.top_services", icon: BarChart3, size: 1, component: TopServicesTable, defaultEnabled: false, dataKey: "dashboard_stats" },
  { id: "top_alert_types", titleKey: "overview.widgets.top_alert_types", icon: Megaphone, size: 1, component: TopAlertTypesTable, defaultEnabled: false, dataKey: "dashboard_stats" },
]

// ── Dashboard widget IDs (shared by classic + warroom) ───────────────────────
export const DASHBOARD_WIDGET_IDS = [
  "dashboard_stat_cards",
  "ticket_trend",
  "severity_donut",
  "top_services",
  "top_alert_types",
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
type ViewMode = "classic" | "warroom"

export function defaultWidgetIds(): string[] {
  return OVERVIEW_WIDGETS.filter((w) => w.defaultEnabled).map((w) => w.id)
}

function storageKey(projectId: string, view: ViewMode): string {
  return `${STORAGE_PREFIX}${view}:${projectId}`
}

function readPrefs(projectId: string, view: ViewMode): string[] {
  if (typeof window === "undefined") return defaultWidgetIds()
  try {
    const raw = localStorage.getItem(storageKey(projectId, view))
    if (!raw) {
      // F2 migration: coba baca key lama (tanpa view) bila key view kosong
      const legacyKey = `${STORAGE_PREFIX}${projectId}`
      const legacyRaw = localStorage.getItem(legacyKey)
      if (legacyRaw) {
        const ids = JSON.parse(legacyRaw)
        if (Array.isArray(ids)) {
          const known = new Set(OVERVIEW_WIDGETS.map((w) => w.id))
          const valid = ids.filter((id): id is string => typeof id === "string" && known.has(id))
          if (valid.length) {
            // Migrate: simpan ke key baru, hapus key lama
            localStorage.setItem(storageKey(projectId, view), JSON.stringify(valid))
            localStorage.removeItem(legacyKey)
            return valid
          }
        }
      }
      return defaultWidgetIds()
    }
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
export function getWidgetPrefs(projectId: string, view: ViewMode = "warroom"): string[] {
  return readPrefs(projectId, view)
}

export function setWidgetPrefs(projectId: string, ids: string[], view: ViewMode = "warroom"): void {
  if (typeof window === "undefined") return
  try {
    localStorage.setItem(storageKey(projectId, view), JSON.stringify(ids))
  } catch {
    // private browsing / storage full — diam
  }
}

/** "Reset default" → hapus prefs → kembali ke set defaultEnabled: true. */
export function resetWidgetPrefs(projectId: string, view: ViewMode = "warroom"): void {
  if (typeof window === "undefined") return
  try {
    localStorage.removeItem(storageKey(projectId, view))
  } catch {
    // diam
  }
}

/** Hook prefs widget — state sync + persist localStorage per project per view. */
export function useWidgetPrefs(
  projectId: string | null | undefined,
  view: ViewMode = "warroom",
) {
  const [enabled, setEnabled] = useState<string[]>(() =>
    projectId ? getWidgetPrefs(projectId, view) : defaultWidgetIds(),
  )
  useEffect(() => {
    if (projectId) setEnabled(getWidgetPrefs(projectId, view))
  }, [projectId, view])
  const update = useCallback(
    (ids: string[]) => {
      setEnabled(ids)
      if (projectId) setWidgetPrefs(projectId, ids, view)
    },
    [projectId, view],
  )
  const reset = useCallback(() => {
    if (projectId) resetWidgetPrefs(projectId, view)
    setEnabled(defaultWidgetIds())
  }, [projectId, view])
  return { enabled, update, reset }
}