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
