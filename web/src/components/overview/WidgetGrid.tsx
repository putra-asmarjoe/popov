import { useTranslation } from "react-i18next"
import { OVERVIEW_WIDGETS } from "@/lib/overview-widgets"
import { WidgetShell } from "@/components/overview/WidgetShell"

const SPAN_CLASS: Record<number, string> = {
  1: "md:col-span-1",
  2: "md:col-span-2",
  3: "md:col-span-3",
}

/**
 * WidgetGrid — render widget enabled (urutan prefs) di grid 1/3 kolom.
 * Widget cuma konsumen; data fetch tetap di page (via WidgetDataContext).
 */
export function WidgetGrid({
  enabled,
  onRemove,
}: {
  enabled: string[]
  onRemove: (id: string) => void
}) {
  const { t } = useTranslation("project")
  const defs = enabled
    .map((id) => OVERVIEW_WIDGETS.find((w) => w.id === id))
    .filter((w): w is NonNullable<typeof w> => Boolean(w))

  if (!defs.length) {
    return (
      <p className="rounded-xl border bg-card px-4 py-8 text-center text-xs text-muted-foreground">
        {t("overview.widgets.empty")}
      </p>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {defs.map((def) => (
        <WidgetShell
          key={def.id}
          def={def}
          onRemove={onRemove}
          className={SPAN_CLASS[def.size] ?? "md:col-span-1"}
        >
          <def.component />
        </WidgetShell>
      ))}
    </div>
  )
}