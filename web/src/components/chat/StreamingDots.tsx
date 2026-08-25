import { Loader2 } from "lucide-react"
import { useChatStore } from "@/store/chat.store"

/** Indikator "agent sedang memproses..." + nama agent terakhir dari event progress. */
export function StreamingDots() {
  const activeAgent = useChatStore((s) => s.activeAgent)
  const label = activeAgent
    ? activeAgent.replace(/_agent$/, "").replace(/_/g, " ")
    : "popov agent"
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />
      <span className="capitalize">{label} sedang menganalisis…</span>
    </div>
  )
}
