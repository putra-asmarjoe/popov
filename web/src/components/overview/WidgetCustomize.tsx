import { useTranslation } from "react-i18next"
import { Check, ChevronDown, ChevronUp, RotateCcw, SlidersHorizontal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { OVERVIEW_WIDGETS } from "@/lib/overview-widgets"

/**
 * WidgetCustomize — popover (pola MultiSelectPopover): daftar SEMUA widget registry,
 * checkbox enable/disable (widget default OFF tampil sebagai "add"), up/down reorder,
 * "Reset default". Reorder v1 = up/down (drag interactjs = enhancement).
 */
export function WidgetCustomize({
  enabled,
  onToggle,
  onMove,
  onReset,
}: {
  enabled: string[]
  onToggle: (id: string) => void
  onMove: (id: string, dir: -1 | 1) => void
  onReset: () => void
}) {
  const { t } = useTranslation("project")
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="icon-sm" aria-label={t("overview.widgets.title")}>
          <SlidersHorizontal className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2">
        <div className="mb-1 flex items-center justify-between px-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("overview.widgets.title")}
          </span>
          <Button variant="ghost" size="sm" className="h-6 gap-1 px-1.5 text-[10px]" onClick={onReset}>
            <RotateCcw className="size-3" aria-hidden="true" />
            {t("overview.widgets.reset")}
          </Button>
        </div>
        <ul className="space-y-0.5">
          {OVERVIEW_WIDGETS.map((def) => {
            const on = enabled.includes(def.id)
            const pos = enabled.indexOf(def.id)
            const Icon = def.icon
            return (
              <li
                key={def.id}
                className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-muted/50"
              >
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  onClick={() => onToggle(def.id)}
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded border transition",
                    on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-transparent",
                  )}
                  aria-label={on ? t("overview.widgets.remove", { title: t(def.titleKey) }) : t("overview.widgets.add", { title: t(def.titleKey) })}
                >
                  {on && <Check className="size-3" aria-hidden="true" />}
                </button>
                <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-xs">{t(def.titleKey)}</span>
                {on && (
                  <div className="flex shrink-0 items-center">
                    <button
                      type="button"
                      disabled={pos === 0}
                      onClick={() => onMove(def.id, -1)}
                      className="rounded p-0.5 text-muted-foreground hover:bg-muted disabled:opacity-30"
                      aria-label={t("overview.widgets.move_up", { title: t(def.titleKey) })}
                    >
                      <ChevronUp className="size-3.5" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      disabled={pos === -1 || pos === enabled.length - 1}
                      onClick={() => onMove(def.id, 1)}
                      className="rounded p-0.5 text-muted-foreground hover:bg-muted disabled:opacity-30"
                      aria-label={t("overview.widgets.move_down", { title: t(def.titleKey) })}
                    >
                      <ChevronDown className="size-3.5" aria-hidden="true" />
                    </button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      </PopoverContent>
    </Popover>
  )
}