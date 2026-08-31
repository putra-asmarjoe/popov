import { useTranslation } from "react-i18next"
import { AlertTriangle, ArrowRightCircle, MessageSquare } from "lucide-react"
import { cn, timeAgo } from "@/lib/utils"
import type { WarroomRun } from "@/types/warroom"

/** Daftar investigasi per run (1 tiket = banyak reply/bubble). Pilih run aktif. */
export function RunsList({
  runs,
  activeIndex,
  onSelect,
  onOpenChat,
}: {
  runs: WarroomRun[]
  activeIndex: number
  onSelect: (i: number) => void
  onOpenChat: () => void
}) {
  const { t } = useTranslation("project")
  if (!runs.length) return null

  return (
    <div className="rounded-xl border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t("warroom.investigations")} ({runs.length})
        </span>
      </div>
      <ul className="divide-y divide-border/50">
        {runs.map((r, i) => {
          const active = i === activeIndex
          return (
            <li key={r.request_id ?? i}>
              <button
                type="button"
                onClick={() => onSelect(i)}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-muted/40",
                  active && "bg-primary/10",
                )}
                aria-pressed={active}
              >
                <span
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    active ? "bg-primary" : "bg-border",
                  )}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {r.diagnosis.hypothesis || t("warroom.unknown")}
                  </span>
                  <span className="block text-[10px] text-muted-foreground">
                    {timeAgo(r.investigated_at)} · {r.channel ?? "-"}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1 text-muted-foreground">
                  <MessageSquare
                    className={cn("size-3.5", active && "text-primary")}
                    aria-hidden="true"
                  />
                  <span className="sr-only">{t("warroom.open_in_chat")}</span>
                </span>
              </button>
              {active && (
                <div className="flex items-center gap-1.5 px-3 pb-2 text-[10px] text-muted-foreground">
                  <AlertTriangle className="size-3" aria-hidden="true" />
                  {t("warroom.investigation_hint")}
                  <button
                    type="button"
                    onClick={onOpenChat}
                    className="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-primary hover:bg-primary/10"
                  >
                    <ArrowRightCircle className="size-3" aria-hidden="true" />
                    {t("warroom.open_in_chat")}
                  </button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}