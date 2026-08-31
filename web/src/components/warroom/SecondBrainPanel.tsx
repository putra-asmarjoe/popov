import { useTranslation } from "react-i18next"
import { BookOpen, CheckCircle2, Clock } from "lucide-react"
import { cn, formatMs, timeAgo } from "@/lib/utils"
import type { WarroomSecondBrain } from "@/types/warroom"

function simTone(sim: number | null): { label: string; cls: string } {
  if (sim == null) return { label: "-", cls: "bg-muted text-muted-foreground" }
  if (sim >= 0.55)
    return { label: "known", cls: "bg-green-600/15 text-green-700 dark:text-green-400" }
  if (sim >= 0.3)
    return { label: "partial", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-400" }
  return { label: "unknown", cls: "bg-muted text-muted-foreground" }
}

/** Second Brain — episode serupa dari history: root cause + resolution + TTR. */
export function SecondBrainPanel({ items }: { items: WarroomSecondBrain[] }) {
  const { t } = useTranslation("project")
  if (!items.length) return null

  return (
    <div className="rounded-xl border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <BookOpen className="size-3.5 text-primary" aria-hidden="true" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t("warroom.second_brain")}
        </span>
      </div>
      <ul className="divide-y divide-border/60">
        {items.map((it) => {
          const tone = simTone(it.similarity)
          const ttr = it.actual_ttr_minutes
          return (
            <li key={it.episode_id ?? String(it.similarity)} className="px-3 py-2.5">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-semibold">{it.episode_id}</span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase",
                    tone.cls,
                  )}
                >
                  {tone.label} {it.similarity != null ? `${Math.round(it.similarity * 100)}%` : ""}
                </span>
                <span className="ml-auto text-[10px] text-muted-foreground">
                  {timeAgo(it.created_at ?? it.timestamp)}
                </span>
              </div>
              {it.root_cause && (
                <p className="mt-1 line-clamp-2 text-xs leading-snug text-foreground/90">
                  {it.root_cause}
                </p>
              )}
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                {ttr != null && (
                  <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                    <Clock className="size-3" aria-hidden="true" />
                    <span className="tabular-nums">{formatMs(ttr * 60_000)}</span>
                    {" " + t("warroom.ttr")}
                  </span>
                )}
                {it.resolution_actions?.slice(0, 2).map((a, i) => (
                  <span
                    key={i}
                    className="flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-foreground/80"
                  >
                    <CheckCircle2 className="size-3 text-green-600" aria-hidden="true" />
                    {a}
                  </span>
                ))}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}