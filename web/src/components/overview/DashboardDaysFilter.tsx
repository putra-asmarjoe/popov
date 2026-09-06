import { useTranslation } from "react-i18next"

const OPTIONS = [
  { key: "today", labelKey: "dashboard.days_1", value: 1 },
  { key: "d3", labelKey: "dashboard.days_3", value: 3 },
  { key: "d7", labelKey: "dashboard.days_7", value: 7 },
  { key: "d30", labelKey: "dashboard.days_30", value: 30 },
] as const

interface Props {
  value: number
  onChange: (days: number) => void
}

/** Filter rentang hari widget dashboard. Label i18n (en/id). */
export function DashboardDaysFilter({ value, onChange }: Props) {
  const { t } = useTranslation("project")
  return (
    <div
      className="flex items-center gap-1 rounded-md border bg-muted/40 p-0.5"
      role="group"
      aria-label={t("dashboard.days_filter")}
    >
      {OPTIONS.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={[
            "rounded px-2.5 py-1 text-xs font-medium transition-colors",
            value === o.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          ].join(" ")}
        >
          {t(o.labelKey)}
        </button>
      ))}
    </div>
  )
}
