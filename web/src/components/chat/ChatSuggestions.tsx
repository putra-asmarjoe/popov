import { cn } from "@/lib/utils"
import type { Suggestion, SuggestionChip } from "@/lib/chat-meta"

function isChip(s: Suggestion): s is SuggestionChip {
  return typeof s === "object" && s !== null && "label" in s
}

/**
 * ChatSuggestions — chips follow-up.
 * Dua tipe (Gap 5):
 *  - investigation (🔍): klik → auto-send action identifier ("investigate:<node>") via onSend
 *  - general (💡): klik → isi input (onPick) — user bisa edit dulu (existing behavior)
 * DRY: dipakai chat tiket (ChatPanel) & chat project (ProjectChatPage).
 */
export function ChatSuggestions({
  suggestions,
  onPick,
  onSend,
  className,
  contentClassName,
}: {
  suggestions: Suggestion[]
  onPick: (text: string) => void
  onSend?: (text: string) => void
  className?: string
  contentClassName?: string
}) {
  if (suggestions.length === 0) return null
  return (
    <div className={cn("border-t px-4 py-2", className)}>
      <div className={cn("mx-auto flex flex-wrap gap-1.5", contentClassName)}>
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
                  onSend(sug.action)
                } else {
                  onPick(label)
                }
              }}
              className={cn(
                "rounded-full border px-2.5 py-1 text-left text-xs",
                isInvestigation
                  ? "bg-primary/10 border-primary/30 hover:bg-primary/20"
                  : "bg-muted/40 hover:bg-muted"
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