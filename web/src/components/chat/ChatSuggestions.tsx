import { cn } from "@/lib/utils"

/**
 * ChatSuggestions — chips 💡 recommended questions (follow-up suggestions).
 * DRY: dipakai chat tiket (ChatPanel) & chat project (ProjectChatPage).
 * Klik chip → isi input chat (onPick), bukan langsung kirim — user bisa edit dulu.
 */
export function ChatSuggestions({
  suggestions,
  onPick,
  className,
  contentClassName,
}: {
  suggestions: string[]
  onPick: (text: string) => void
  className?: string
  contentClassName?: string
}) {
  if (suggestions.length === 0) return null
  return (
    <div className={cn("border-t px-4 py-2", className)}>
      <div className={cn("mx-auto flex flex-wrap gap-1.5", contentClassName)}>
        {suggestions.map((sug) => (
          <button
            key={sug}
            type="button"
            onClick={() => onPick(sug)}
            className="rounded-full border bg-muted/40 px-2.5 py-1 text-left text-xs hover:bg-muted"
          >
            💡 {sug}
          </button>
        ))}
      </div>
    </div>
  )
}
