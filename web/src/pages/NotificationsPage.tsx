import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Bell, CheckCheck } from "lucide-react"
import { useTranslation } from "react-i18next"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { useMarkRead, useNotifications } from "@/hooks/useNotifications"
import { useWorkspaces } from "@/hooks/useWorkspaces"
import { cn, formatDate } from "@/lib/utils"
import type { NotificationItem } from "@/types/notification"

/** NotificationsPage (/notifications) — daftar penuh + filter unread. */
export function NotificationsPage() {
  const { t } = useTranslation("common")
  const [unreadOnly, setUnreadOnly] = useState(false)
  const { data, isLoading } = useNotifications(50, unreadOnly)
  const markRead = useMarkRead()
  const navigate = useNavigate()
  const { data: workspaces } = useWorkspaces()

  const openTicket = async (n: NotificationItem) => {
    if (!n.readAt) markRead.mutate([n.id])
    const { projectId, ticketNumber, projectKey } = n.payload
    if (!projectId || !ticketNumber) return
    try {
      // Cari project di seluruh workspace milik user → dapatkan slug untuk routing
      for (const ws of workspaces ?? []) {
        const { data: projs } = await api.get(`/workspaces/${ws.id}/projects`)
        const found = (projs.projects as { id: string; slug: string }[]).find(
          (p) => p.id === projectId,
        )
        if (found) {
          navigate(`/w/${ws.slug}/${found.slug}?ticket=${projectKey ?? "?"}-${ticketNumber}`)
          return
        }
      }
    } catch {
      // project tidak ditemukan — diam di halaman ini
    }
  }

  return (
    <div className="mx-auto max-w-2xl p-6 md:p-8">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-xl bg-muted">
          <Bell className="size-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-lg font-semibold">{t("notif.title")}</h1>
          <p className="text-xs text-muted-foreground">
            {data ? t("notif.unread", { count: data.unread }) : t("notif.loading")}
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            onClick={() => setUnreadOnly((v) => !v)}
          >
            {unreadOnly ? t("notif.all") : t("notif.unread_only")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1 text-xs"
            onClick={() => markRead.mutate(undefined)}
            disabled={!data?.unread}
          >
            <CheckCheck className="size-3.5" /> {t("notif.mark_all")}
          </Button>
        </div>
      </div>

      <div className="mt-6 space-y-2">
        {isLoading ? (
          [...Array(4)].map((_, i) => <Skeleton key={i} className="h-14 w-full rounded-lg" />)
        ) : !data?.notifications.length ? (
          <div className="rounded-xl border border-dashed p-10 text-center">
            <p className="text-sm font-medium">{t("notif.empty")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("notif.empty_desc")}
            </p>
          </div>
        ) : (
          data.notifications.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => openTicket(n)}
              className={cn(
                "flex w-full cursor-pointer items-start gap-3 rounded-lg border p-3.5 text-left transition-colors hover:bg-muted/50",
                !n.readAt && "border-primary/30 bg-primary/5",
              )}
            >
              <span
                className={cn(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  n.readAt ? "bg-muted-foreground/30" : "bg-primary",
                )}
              />
              <span className="min-w-0 flex-1">
                <span className={cn("block text-sm leading-snug", !n.readAt && "font-medium")}>
                  {n.title}
                </span>
                <span className="mt-1 block text-[11px] text-muted-foreground">
                  {formatDate(n.createdAt)} · {n.type}
                </span>
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
