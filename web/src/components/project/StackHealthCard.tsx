import { useTranslation } from "react-i18next"
import { cn, timeAgo } from "@/lib/utils"
import { useWidgetData } from "@/components/overview/WidgetDataContext"

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

/** Stack health — body-only (chrome di WidgetShell). Data via WidgetDataContext.
 *  Baca health_status (watchdog), JANGAN probe ulang. Stale: last check >90s → muted. */
export function StackHealthCard() {
  const { t } = useTranslation("project")
  const { overview } = useWidgetData()
  const stacks = overview?.stack_health ?? []
  const generatedAt = overview?.generated_at
  const okCount = stacks.filter((s) => healthTone(s.health_status) === "ok").length

  if (!stacks.length) {
    return (
      <p className="px-3 py-6 text-center text-xs text-muted-foreground">
        {t("overview.stacks_empty")}
      </p>
    )
  }

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-1.5 text-[10px] text-muted-foreground">
        <span className="tabular-nums">
          <span className="font-bold text-foreground">{okCount}</span>/{stacks.length}
        </span>
        <span className="ml-auto tabular-nums">{t("overview.updated")} {timeAgo(generatedAt)}</span>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-border/50 overflow-y-auto">
        {stacks.map((s) => {
          const tone = healthTone(s.health_status)
          const last = s.last_health_check_at ? new Date(s.last_health_check_at).getTime() : 0
          const stale = last !== 0 && Date.now() - last > STALE_MS
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