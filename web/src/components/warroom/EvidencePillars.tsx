import { useTranslation } from "react-i18next"
import { Database, HeartPulse, Radar, Box, Minus } from "lucide-react"
import { cn, formatMs } from "@/lib/utils"
import type { WarroomPillar } from "@/types/warroom"

const PILLARS = [
  { key: "mongo", icon: Database, labelKey: "warroom.pillar_mongo" },
  { key: "metrics", icon: Radar, labelKey: "warroom.pillar_metrics" },
  { key: "trace", icon: Box, labelKey: "warroom.pillar_trace" },
  { key: "span", icon: HeartPulse, labelKey: "warroom.pillar_span" },
] as const

/** 4 pillar evidence — ran = summary + durasi; skipped = muted, bukan kotak kosong. */
export function EvidencePillars({
  pillars,
}: {
  pillars: Record<"mongo" | "metrics" | "trace" | "span", WarroomPillar>
}) {
  const { t } = useTranslation("project")

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
      {PILLARS.map(({ key, icon: Icon, labelKey }) => {
        const p = pillars[key]
        const ran = p?.status === "ran"
        return (
          <div
            key={key}
            className={cn(
              "flex min-w-0 flex-col gap-1.5 rounded-lg border bg-card px-3 py-2.5 ring-1 ring-foreground/5",
              !ran && "opacity-70",
            )}
          >
            <div className="flex items-center gap-1.5">
              <Icon className={cn("size-3.5", ran ? "text-primary" : "text-muted-foreground")} aria-hidden="true" />
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                {t(labelKey)}
              </span>
              <span className="ml-auto">
                {ran ? (
                  <span className="rounded bg-green-600/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-green-700 dark:text-green-400">
                    {t("warroom.ran")}
                  </span>
                ) : (
                  <span className="flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[9px] font-semibold uppercase text-muted-foreground">
                    <Minus className="size-2.5" aria-hidden="true" /> {t("warroom.skipped")}
                  </span>
                )}
              </span>
            </div>
            {ran ? (
              <>
                <p className="line-clamp-2 min-h-8 text-xs leading-snug text-foreground/90">
                  {p.summary || t("warroom.no_data")}
                </p>
                <p className="tabular-nums text-[10px] text-muted-foreground">
                  {formatMs(p.duration_ms)}
                </p>
              </>
            ) : (
              <p className="min-h-8 text-[11px] italic text-muted-foreground">
                {t("warroom.pillar_skipped_hint")}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}