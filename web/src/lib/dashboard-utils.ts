/** Format detik → string human-readable, misal 14400 → "4h" atau "4h 30m" */
export function formatMttr(seconds: number | null): string {
  if (seconds === null || seconds === 0) return "—"
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h === 0) return `${m}m`
  if (m === 0) return `${h}h`
  return `${h}h ${m}m`
}

/** Warna per severity — konsisten dgn ticket list badge (utils.ts severityColor) */
export const SEVERITY_COLOR: Record<string, string> = {
  critical: "#ef4444",   // red-500 (severity-critical-bg)
  high:     "#f87171",   // red-400 (severity-high-bg)
  medium:   "#f59e0b",   // amber-500 (severity-medium-bg)
  low:      "#a1a1aa",   // zinc-400 (severity-low-bg)
}

/** Isi tanggal yang hilang di trend array supaya line chart mulus.
 *  Basis UTC — backend group by UTC date (createdAt ISO UTC). */
export function fillTrendGaps(
  trend: { date: string; count: number }[],
  days: number,
): { date: string; count: number }[] {
  const map = Object.fromEntries(trend.map((t) => [t.date, t.count]))
  const result = []
  const nowMs = Date.now()
  for (let i = days - 1; i >= 0; i--) {
    const key = new Date(nowMs - i * 86_400_000).toISOString().slice(0, 10)
    result.push({ date: key.slice(5), count: map[key] ?? 0 })
  }
  return result
}
