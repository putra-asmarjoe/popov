import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Bell, CheckCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useMarkRead, useNotifications } from "@/hooks/useNotifications"
import { cn, formatDate } from "@/lib/utils"

/** Bell notifikasi di Topbar — 5 terbaru + mark all read + link halaman penuh. */
export function NotifDropdown() {
  const { t } = useTranslation("common")
  const { data } = useNotifications(5)
  const markRead = useMarkRead()
  const unread = data?.unread ?? 0
  const items = data?.notifications ?? []

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="relative cursor-pointer rounded-md p-1.5 outline-none hover:bg-muted ring-ring focus-visible:ring-2">
        <Bell className="size-4.5 size-[18px] text-muted-foreground" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-notif-dot px-1 text-[10px] font-bold leading-4 text-notif-dot-fg">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          {t("notif.title")}
          {unread > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 gap-1 px-2 text-[11px]"
              onClick={() => markRead.mutate(undefined)}
              disabled={markRead.isPending}
            >
              <CheckCheck className="size-3" /> {t("notif.mark_all")}
            </Button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">
            {t("notif.empty")}
          </p>
        ) : (
          items.map((n) => (
            <button
              key={n.id}
              type="button"
              className={cn(
                "flex w-full cursor-pointer items-start gap-2 px-3 py-2.5 text-left hover:bg-muted",
                !n.readAt && "bg-primary/5",
              )}
              onClick={() => !n.readAt && markRead.mutate([n.id])}
            >
              <span
                className={cn(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  n.readAt ? "bg-transparent" : "bg-primary",
                )}
              />
              <span className="min-w-0 flex-1">
                <span className={cn("block text-xs leading-snug", !n.readAt && "font-medium")}>
                  {n.title}
                </span>
                <span className="mt-0.5 block text-[10px] text-muted-foreground">
                  {formatDate(n.createdAt)}
                </span>
              </span>
            </button>
          ))
        )}
        <DropdownMenuSeparator />
        <Button asChild variant="ghost" size="sm" className="w-full text-xs">
          <Link to="/notifications">{t("notif.see_all")}</Link>
        </Button>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
