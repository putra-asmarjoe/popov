import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import type { TicketSeverity, TicketStatus } from "@/types/ticket"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return "-"
  return d.toLocaleString("id-ID", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/** Waktu relatif singkat: "2m ago" / "1h ago" / "3d ago". Kosong → "-". */
export function timeAgo(value: string | null | undefined): string {
  if (!value) return "-"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return "-"
  const diff = Date.now() - d.getTime()
  if (diff < 0) return "now"
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const day = Math.floor(h / 24)
  if (day < 30) return `${day}d ago`
  return formatDate(value)
}

/** Durasi ms → "1.2s" / "800ms"; null → "…". */
export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "…"
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

/** Persentase 0..1 → 0..100 (clamp). */
export function toPct(v: number): number {
  const p = Math.round((v || 0) * 100)
  return Math.min(100, Math.max(0, p))
}

// Warna badge — semantic tokens (tema-aware, kontras AAA).
// Setiap tema override --severity-*/--status-* di CSS.
export const severityColor: Record<TicketSeverity, string> = {
  critical: "bg-severity-critical text-severity-critical-fg",
  high: "bg-severity-high text-severity-high-fg",
  medium: "bg-severity-medium text-severity-medium-fg",
  low: "bg-severity-low text-severity-low-fg",
}

export const statusColor: Record<TicketStatus, string> = {
  new: "bg-status-new text-status-new-fg",
  open: "bg-status-open text-status-open-fg",
  in_progress: "bg-status-in-progress text-status-in-progress-fg",
  needs_review: "bg-status-needs-review text-status-needs-review-fg",
  resolved: "bg-status-resolved text-status-resolved-fg",
  closed: "bg-status-closed text-status-closed-fg",
}
