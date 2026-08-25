import { useTranslation } from "react-i18next"
import { Languages } from "lucide-react"
import type { Locale } from "@/lib/i18n"
import { LOCALES, setStoredLocale } from "@/lib/i18n"
import { api } from "@/lib/api"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function LocaleSwitcher({ className }: { className?: string }) {
  const { i18n, t } = useTranslation("common")

  const handleChange = async (localeId: Locale) => {
    // 1. Update i18next runtime (lazy load namespace locale baru jika belum)
    await i18n.changeLanguage(localeId)

    // 2. Persist ke localStorage
    setStoredLocale(localeId)

    // 3. Sync ke backend (fire-and-forget — tidak block UI)
    syncLocaleToBackend(localeId).catch(console.error)
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("size-9", className)}
          aria-label={t("locale.switch_language")}
          title={t("locale.switch_language")}
        >
          <Languages className="size-4" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-40">
        {LOCALES.map((locale) => (
          <DropdownMenuItem
            key={locale.id}
            onClick={() => void handleChange(locale.id)}
            className={cn(
              "cursor-pointer gap-2",
              i18n.language === locale.id &&
                "bg-accent font-medium text-accent-foreground",
            )}
          >
            <span>{locale.flag}</span>
            <span>{locale.label}</span>
            {i18n.language === locale.id && (
              <span className="ml-auto size-1.5 rounded-full bg-primary" />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Sync locale preference ke backend — fire and forget */
async function syncLocaleToBackend(locale: Locale): Promise<void> {
  await api.patch("/auth/preferences", { localePreference: locale })
}
