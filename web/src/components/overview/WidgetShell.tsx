import { useTranslation } from "react-i18next"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { OverviewWidgetDef } from "@/lib/overview-widgets"

/**
 * WidgetShell — chrome card + header (icon + title + tombol × remove).
 * Body = def.component. Widget EXISTING default ON; BARU default OFF (registry).
 */
export function WidgetShell({
  def,
  onRemove,
  className,
  children,
}: {
  def: OverviewWidgetDef
  onRemove: (id: string) => void
  className?: string
  children: React.ReactNode
}) {
  const { t } = useTranslation("project")
  const Icon = def.icon
  return (
    <div className={cn("group flex min-h-0 flex-col rounded-xl border bg-card ring-1 ring-foreground/5", className)}>
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <Icon className="size-3.5 shrink-0 text-primary" aria-hidden="true" />
        <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t(def.titleKey)}
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          className="ml-auto size-6 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100"
          onClick={() => onRemove(def.id)}
          aria-label={t("overview.widgets.remove", { title: t(def.titleKey) })}
        >
          <X className="size-3.5" aria-hidden="true" />
        </Button>
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  )
}