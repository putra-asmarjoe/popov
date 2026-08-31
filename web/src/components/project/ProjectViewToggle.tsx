import { useTranslation } from "react-i18next"
import { LayoutDashboard, List } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ProjectView } from "@/lib/project-view"

/** Toggle mode halaman utama project: Classic (list tiket) | War Room (overview). */
export function ProjectViewToggle({
  value,
  onChange,
}: {
  value: ProjectView
  onChange: (v: ProjectView) => void
}) {
  const { t } = useTranslation("project")
  const opts: { value: ProjectView; label: string; icon: typeof List }[] = [
    { value: "classic", label: t("view.classic"), icon: List },
    { value: "warroom", label: t("view.warroom"), icon: LayoutDashboard },
  ]

  return (
    <div
      role="group"
      aria-label={t("view.label")}
      className="flex items-center rounded-lg border bg-muted/40 p-0.5"
    >
      {opts.map(({ value: v, label, icon: Icon }) => {
        const active = v === value
        return (
          <button
            key={v}
            type="button"
            onClick={() => onChange(v)}
            aria-pressed={active}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              active
                ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3.5" aria-hidden="true" />
            {label}
          </button>
        )
      })}
    </div>
  )
}