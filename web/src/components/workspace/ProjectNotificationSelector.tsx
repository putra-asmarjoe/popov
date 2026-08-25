import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Bell, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  useLinkChannelMutations,
  useProjectChannels,
} from "@/hooks/useNotificationChannels"

/**
 * ProjectNotificationSelector (Fix #40) — ws-admin-only di ProjectPage:
 * link/unlink BANYAK channel Telegram ke project ini (broadcast = union).
 * Endpoint project-scoped; channel workspace-wide otomatis melayani project
 * tanpa perlu link. Gate admin sudah dilakukan parent (ProjectPage).
 */
export function ProjectNotificationSelector({ projectId }: { projectId?: string }) {
  const { t } = useTranslation("settings")
  const { data: channels } = useProjectChannels(projectId ?? null)
  const { link, unlink } = useLinkChannelMutations(projectId ?? null)
  const [busy, setBusy] = useState(false)

  if (!projectId) return null

  const list = channels ?? []
  const linkedCount = list.filter((c) => c.linked).length
  const toggle = async (notifId: string, next: boolean) => {
    setBusy(true)
    try {
      if (next) await link.mutateAsync(notifId)
      else await unlink.mutateAsync(notifId)
    } finally {
      setBusy(false)
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" disabled={busy}>
          <Bell className="size-3.5 text-muted-foreground" />
          {list.length === 0
            ? t("notif_selector.no_bot")
            : linkedCount > 0
              ? `${linkedCount} channel ter-link`
              : t("notif_selector.link_label")}
          <ChevronDown className="size-3 opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Channel ter-link hanya kirim insiden project ini; channel tanpa link mengirim semua project.
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {list.length === 0 ? (
          <div className="px-2 py-3 text-center text-xs text-muted-foreground">
            {t("channels.no_channel_hint")}
          </div>
        ) : (
          list.map((c) => (
            <DropdownMenuCheckboxItem
              key={c.notif_id}
              checked={!!c.linked}
              disabled={busy || c.enabled === false}
              onCheckedChange={(v) => void toggle(c.notif_id, v)}
              onSelect={(e) => e.preventDefault()}
              className="gap-2"
            >
              <span className="min-w-0 flex-1 truncate">
                🔔 {c.name}
                {!c.enabled && <span className="ml-1 text-[10px] text-muted-foreground">(nonaktif)</span>}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {(c.project_ids?.length ?? 0) === 0 ? "ws-wide" : "linked"}
              </span>
            </DropdownMenuCheckboxItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
