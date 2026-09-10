import { useEffect, useState } from "react"
import { cn } from "@/lib/utils"
import { chipKeyOf, type Suggestion, type SuggestionChip } from "@/lib/chat-meta"

function isChip(s: Suggestion): s is SuggestionChip {
  return typeof s === "object" && s !== null && "label" in s
}

/**
 * ChatSuggestions — chips follow-up.
 * Dua tipe (Gap 5):
 *  - investigation (🔍): klik → auto-send action identifier ("investigate:<node>") via onSend
 *  - general (💡): klik → isi input (onPick) — user bisa edit dulu (existing behavior)
 * USER_PROFILE_PLAN Phase 2: chipKey ikut dikirim (key stabil / action) → counter
 * chips_clicked di backend. DRY: dipakai chat tiket (ChatPanel) & chat project (ProjectChatPage).
 */
export function ChatSuggestions({
  suggestions,
  onPick,
  onSend,
  className,
  contentClassName,
  showDelayMs,
}: {
  suggestions: Suggestion[]
  onPick: (text: string, chipKey?: string) => void
  onSend?: (text: string, chipKey?: string) => void
  className?: string
  contentClassName?: string
  showDelayMs?: number
}) {
  const sig = suggestions
    .map((s) => (isChip(s) ? s.label : s))
    .join("\u0000")
  const [prevSig, setPrevSig] = useState(sig)
  const [visible, setVisible] = useState(() => !showDelayMs)

  if (prevSig !== sig) {
    setPrevSig(sig)
    setVisible(!showDelayMs)
  }

  useEffect(() => {
    if (visible || !showDelayMs || sig === "") return
    const t = setTimeout(() => setVisible(true), showDelayMs)
    return () => clearTimeout(t)
  }, [visible, showDelayMs, sig])

  if (suggestions.length === 0 || !visible) return null
  return (
    <div className={cn("pt-2 pb-1", className)}>
      <div className={cn("flex flex-wrap gap-1.5", contentClassName)}>
        {suggestions.map((sug) => {
          const chip = isChip(sug)
          const label = chip ? sug.label : sug
          const isInvestigation = chip && sug.type === "investigation"
          return (
            <button
              key={label}
              type="button"
              onClick={() => {
                if (isInvestigation && sug.action && onSend) {
                  onSend(sug.action, chipKeyOf(sug))
                } else {
                  onPick(label, chipKeyOf(sug))
                }
              }}
              className={cn(
                "rounded-full border px-2.5 py-1 text-left text-xs transition-colors",
                isInvestigation
                  ? "bg-primary/10 border-primary/30 hover:bg-primary/20"
                  : "bg-muted/50 hover:bg-muted border-border/60 text-foreground/90"
              )}
            >
              {isInvestigation ? "🔍" : "💡"} {label}
            </button>
          )
        })}
      </div>
    </div>
  )
}