import { Loader2 } from "lucide-react"
import { useTranslation } from "react-i18next"
import { useChatStore } from "@/store/chat.store"

/**
 * Indikator progres + nama agent terakhir dari event progress.
 * Fix #115: node `telegram_agent` = pemformat jawaban akhir di web chat
 * (suppress_telegram — TIDAK mengirim ke Telegram), jadi labelnya dibedakan:
 * "composing reply", bukan "analyzing" + nama "telegram" yang menyesatkan.
 *
 * Streaming state di-scope per sessionId — komponen ini perlu tahu sesi mana
 * yang sedang dirender agar tidak menampilkan progress dari sesi lain.
 */
export function StreamingDots({ sessionId }: { sessionId?: string } = {}) {
  const { t } = useTranslation("project")
  const activeAgent = useChatStore((s) =>
    sessionId ? (s.streaming[sessionId]?.activeAgent ?? null) : null,
  )
  const isComposing = activeAgent === "telegram_agent"
  const label =
    activeAgent && !isComposing
      ? activeAgent.replace(/_agent$/, "").replace(/_/g, " ")
      : "popov agent"
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />
      <span className="capitalize">
        {label} {isComposing ? t("chat.agent_composing") : t("chat.agent_working")}
      </span>
    </div>
  )
}
