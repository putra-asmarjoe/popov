// ============================================================
// THEME SWITCHER — dropdown UI 5 tema
// shadcn DropdownMenu + lucide-react icons
// ============================================================

import { CloudMoon, Monitor, Moon, Sparkles, Sun } from "lucide-react"
import { useTranslation } from "react-i18next"
import { THEMES, useTheme, type Theme, type ThemeIconName } from "@/lib/theme"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const ICONS: Record<ThemeIconName, typeof Sun> = {
  Sun,
  Moon,
  Sparkles,
  CloudMoon,
  Monitor,
}

/** Map theme id → i18n label key */
const THEME_LABEL_KEY: Record<string, string> = {
  light: "theme.light",
  dark: "theme.dark",
  fancy: "theme.fancy",
  calm: "theme.calm",
  system: "theme.system",
}

/** Map theme id → i18n description key */
const THEME_DESC_KEY: Record<string, string> = {
  light: "theme.desc_light",
  dark: "theme.desc_dark",
  fancy: "theme.desc_fancy",
  calm: "theme.desc_calm",
  system: "theme.desc_system",
}

export function ThemeSwitcher({ className }: { className?: string }) {
  const { theme, resolvedTheme, setTheme } = useTheme()
  const { t } = useTranslation("common")
  const active = THEMES.find((th) => th.id === theme) ?? THEMES[0]
  const ActiveIcon = ICONS[active.icon]

  // Label yang ditampilkan di trigger: kalau system, tunjukkan "Auto (Light/Dark)"
  const triggerLabel = theme === "system"
    ? `Auto · ${t(THEME_LABEL_KEY[resolvedTheme] ?? `theme.${resolvedTheme}`)}`
    : t(THEME_LABEL_KEY[theme] ?? `theme.${theme}`)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("h-9 w-9", className)}
          aria-label={t("theme.trigger_aria", { theme: triggerLabel })}
          title={triggerLabel}
        >
          <ActiveIcon className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          {t("theme.label")}
        </DropdownMenuLabel>
        {THEMES.map((th: Theme) => {
          const Icon = ICONS[th.icon]
          const isActive = th.id === theme
          const isResolved = th.id !== "system" && th.id === resolvedTheme
          return (
            <DropdownMenuItem
              key={th.id}
              onClick={() => setTheme(th.id)}
              className={cn(
                "flex cursor-pointer items-center gap-2 py-2",
                isActive && "bg-accent text-accent-foreground font-medium",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="flex items-center gap-1.5 text-sm">
                  {t(THEME_LABEL_KEY[th.id] ?? th.label)}
                  {th.id === "system" && isResolved && (
                    <span className="rounded bg-muted px-1 py-0.5 text-[10px] font-normal text-muted-foreground">
                      → {t(THEME_LABEL_KEY[resolvedTheme] ?? resolvedTheme)}
                    </span>
                  )}
                </span>
                <span className="text-[11px] font-normal text-muted-foreground">
                  {t(THEME_DESC_KEY[th.id] ?? th.description)}
                </span>
              </div>
            </DropdownMenuItem>
          )
        })}
        <DropdownMenuSeparator />
        <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
          {t("theme.contrast_note")}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
