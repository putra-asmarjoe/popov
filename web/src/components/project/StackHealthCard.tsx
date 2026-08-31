import { useTranslation } from "react-i18next"
import { Activity } from "lucide-react"
import { cn, timeAgo } from "@/lib/utils"
import type { StackHealth } from "@/types/overview"

type Tone = "ok" | "degraded" | "error" | "unknown"

function healthTone(status: string): Tone {
  const s = (status || "").toLowerCase()
  if (s === "ok") return "ok"
  if (s.startsWith("degraded")) return "degraded"
  if (s.startsWith("error")) return "error"
  return "unknown"
}

const TONE_DOT: Record<Tone, string> = {
  ok: "bg-green-600",
  degraded: "bg-amber-500",
  error: "bg-red-500",
  unknown: "bg-muted-foreground/50",
}

const STALE_MS = 90_000

/** Stack health — baca health_status (watchdog), JANGAN probe ulang.
 *  Stale: last_health_check_at > 90s → muted + tag "stale". */
export function StackHealthCard({
  stacks,
  generatedAt,
}: {
  stacks: StackHealth[]
  generatedAt?: string
}) {
  const { t } = useTranslation("project")
  const okCount = stacks.filter((s) => healthTone(s.health_status) === "ok").length
  const staleNow = () => Date.now()

  return (
    <div className="flex min-h-0 flex-col rounded-xl border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <Activity className="size-3.5 text-primary" aria-hidden="true" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t("overview.stack_health")}
        </span>
        <span className="ml-auto tabular-nums text-[10px] text-muted-foreground">
          {t("overview.updated")} {timeAgo(generatedAt)}
        </span>
        <span className="text-xs tabular-nums">
          <span className="font-bold">{okCount}</span>
          <span className="text-muted-foreground">/{stacks.length}</span>
        </span>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-border/50 overflow-y-auto">
        {stacks.length === 0 && (
          <li className="px-3 py-6 text-center text-xs text-muted-foreground">
            {t("overview.stacks_empty")}
          </li>
        )}
        {stacks.map((s) => {
          const tone = healthTone(s.health_status)
          const last = s.last_health_check_at ? new Date(s.last_health_check_at).getTime() : 0
          const stale = last !== 0 && staleNow() - last > STALE_MS
          return (
            <li key={s.id} className="flex items-center gap-2 px-3 py-2">
              <span
                className={cn("size-2 shrink-0 rounded-full", TONE_DOT[tone])}
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-xs font-medium">{s.kind ?? "?"}</p>
                {s.url && (
                  <p className="truncate text-[10px] text-muted-foreground/70">{s.url}</p>
                )}
              </div>
              <span
                className={cn(
                  "shrink-0 text-[10px]",
                  tone === "error" && "text-destructive",
                  tone === "degraded" && "text-amber-600 dark:text-amber-400",
                  tone === "ok" && "text-green-700 dark:text-green-400",
                  tone === "unknown" && "text-muted-foreground",
                )}
              >
                {t(`overview.health.${tone}`)}
              </span>
              {stale && (
                <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-[9px] uppercase text-muted-foreground">
                  {t("overview.stale")}
                </span>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}