import { useTranslation } from "react-i18next"
import { MessageSquarePlus, MessagesSquare } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn, formatDate } from "@/lib/utils"
import type { ChatSession } from "@/types/chat"

/** Dropdown daftar sesi chat + tombol chat baru. */
export function SessionList({
  sessions,
  activeSessionId,
  onSelect,
  onNew,
  creating,
}: {
  sessions: ChatSession[]
  activeSessionId: string | null
  onSelect: (session: ChatSession) => void
  onNew: () => void
  creating: boolean
}) {
  const { t } = useTranslation("project")
  const active = sessions.find((s) => s.id === activeSessionId)
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <DropdownMenu>
        <DropdownMenuTrigger className="flex min-w-0 cursor-pointer items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground outline-none hover:bg-muted">
          <MessagesSquare className="size-3.5 shrink-0" />
          <span className="max-w-32 truncate">{active?.title ?? t("chat.history_fallback")}</span>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-60">
          <DropdownMenuLabel className="text-xs">{t("chat.sessions_label")}</DropdownMenuLabel>
          {sessions.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">{t("chat.no_other_sessions")}</p>
          ) : (
            sessions.map((s) => (
              <DropdownMenuItem
                key={s.id}
                className={cn("flex-col items-start gap-0.5", s.id === activeSessionId && "bg-muted")}
                onClick={() => onSelect(s)}
              >
                <span className="w-full truncate text-sm">{s.title}</span>
                <span className="text-[10px] text-muted-foreground">{formatDate(s.updatedAt)}</span>
              </DropdownMenuItem>
            ))
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 shrink-0 gap-1 px-2 text-xs"
        onClick={onNew}
        disabled={creating}
        title={t("chat.new_chat")}
      >
        <MessageSquarePlus className="size-3.5" />
        {t("chat.new_button")}
      </Button>
    </div>
  )
}
