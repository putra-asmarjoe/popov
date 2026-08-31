import { useMemo } from "react"
import { useTranslation } from "react-i18next"
import { CheckCircle2, Circle, Layers } from "lucide-react"
import { cn, formatMs, timeAgo } from "@/lib/utils"
import type { OverviewEpisode } from "@/types/overview"

const DAYS = 30

/** Episode pulse — CSS bar sparkline (tanpa library chart) + list episode.
 *  Episode tak punya severity → tampilkan root_cause + confidence. Resolved
 *  ditandai enriched_at (terisi saat tiket resolved). */
export function EpisodeTimeline({ episodes }: { episodes: OverviewEpisode[] }) {
  const { t } = useTranslation("project")

  const buckets = useMemo(() => {
    const arr = new Array<number>(DAYS).fill(0)
    const now = new Date()
    for (const ep of episodes) {
      const d = new Date(ep.created_at ?? "")
      if (Number.isNaN(d.getTime())) continue
      const dayIdx = Math.max(0, Math.floor((now.getTime() - d.getTime()) / 86_400_000))
      if (dayIdx < DAYS) arr[dayIdx] += 1
    }
    return arr
  }, [episodes])

  const max = Math.max(1, ...buckets)
  const resolvedCount = episodes.filter((e) => e.enriched_at).length
  const total = episodes.length

  return (
    <div className="rounded-xl border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <Layers className="size-3.5 text-primary" aria-hidden="true" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t("overview.episodes")}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {total} · {resolvedCount} {t("overview.resolved")}
        </span>
      </div>

      {/* Pulse: episode count per day (30d) — CSS bars, aksesibel via label */}
      <div
        role="img"
        aria-label={`${total} ${t("overview.episodes")} dalam 30 hari, ${resolvedCount} resolved`}
        className="flex h-14 items-end gap-[3px] border-b px-3 py-2"
      >
        {buckets.map((c, i) => (
          <div
            key={i}
            title={`${c} · ${DAYS - 1 - i}d ago`}
            className={cn(
              "min-w-0 flex-1 rounded-sm",
              c > 0 ? "bg-primary/60" : "bg-muted",
            )}
            style={{ height: c > 0 ? `${Math.max(15, (c / max) * 100)}%` : "15%" }}
          />
        ))}
      </div>

      {total === 0 && (
        <p className="px-3 py-6 text-center text-xs text-muted-foreground">
          {t("overview.episodes_empty")}
        </p>
      )}

      {total > 0 && (
        <ul className="divide-y divide-border/50">
          {episodes.slice(0, 6).map((ep) => {
            const resolved = Boolean(ep.enriched_at)
            return (
              <li key={ep.id} className="flex items-center gap-2 px-3 py-2">
                {resolved ? (
                  <CheckCircle2 className="size-3.5 shrink-0 text-green-600" aria-hidden="true" />
                ) : (
                  <Circle className="size-3.5 shrink-0 text-amber-500" aria-hidden="true" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs">
                    <span className="font-mono font-semibold">{ep.episode_id ?? "—"}</span>
                    {ep.root_cause && (
                      <span className="ml-1.5 text-muted-foreground">{ep.root_cause}</span>
                    )}
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    {timeAgo(ep.created_at)}
                    {ep.confidence != null && (
                      <span className="tabular-nums">
                        {" · "}
                        {Math.round(ep.confidence * 100)}%
                      </span>
                    )}
                    {ep.actual_ttr_minutes != null && (
                      <span className="tabular-nums">
                        {" · TTR "}
                        {formatMs(ep.actual_ttr_minutes * 60_000)}
                      </span>
                    )}
                  </p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}