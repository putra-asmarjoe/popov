// ============================================================
// THEME SWITCHER — dropdown UI 5 tema
// shadcn DropdownMenu + lucide-react icons
// ============================================================

import { CloudMoon, Monitor, Moon, Sparkles, Sun } from "lucide-react"
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

export function ThemeSwitcher({ className }: { className?: string }) {
  const { theme, resolvedTheme, setTheme } = useTheme()
  const active = THEMES.find((t) => t.id === theme) ?? THEMES[0]
  const ActiveIcon = ICONS[active.icon]

  // Label yang ditampilkan di trigger: kalau system, tunjukkan "Auto (Light/Dark)"
  const triggerLabel = theme === "system" ? `Auto · ${resolvedTheme}` : active.label

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("h-9 w-9", className)}
          aria-label={`Tema saat ini: ${triggerLabel}. Ganti tema`}
          title={triggerLabel}
        >
          <ActiveIcon className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Tema
        </DropdownMenuLabel>
        {THEMES.map((t: Theme) => {
          const Icon = ICONS[t.icon]
          const isActive = t.id === theme
          const isResolved = t.id !== "system" && t.id === resolvedTheme
          return (
            <DropdownMenuItem
              key={t.id}
              onClick={() => setTheme(t.id)}
              className={cn(
                "flex cursor-pointer items-center gap-2 py-2",
                isActive && "bg-accent text-accent-foreground font-medium",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="flex items-center gap-1.5 text-sm">
                  {t.label}
                  {t.id === "system" && isResolved && (
                    <span className="rounded bg-muted px-1 py-0.5 text-[10px] font-normal text-muted-foreground">
                      → {resolvedTheme}
                    </span>
                  )}
                </span>
                <span className="text-[11px] font-normal text-muted-foreground">
                  {t.description}
                </span>
              </div>
            </DropdownMenuItem>
          )
        })}
        <DropdownMenuSeparator />
        <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
          Kontras target ~10:1 · calming untuk mata
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
