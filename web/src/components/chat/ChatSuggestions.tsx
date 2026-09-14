import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowRight, ArrowUpRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { chipKeyOf, chipKind, type Suggestion, type SuggestionChip } from "@/lib/chat-meta"

function isChip(s: Suggestion): s is SuggestionChip {
  return typeof s === "object" && s !== null && "label" in s
}

/**
 * ChatSuggestions — chips follow-up, kontrak dua tipe (CHAT3 §4A.7, Rev 7):
 *  - ACTION (aksen + ikon panah maju): giliran percakapan yang aman — teks chip
 *    masuk chat sebagai pesan user via relay onPick/onSend existing (K1 tetap).
 *  - OFFER (muted + ↗): keluar dari percakapan → navigasi ke `target` (react-router).
 * Semantic carrier = field `type` dari backend; ikon/warna hanya styling FE.
 * Legacy: type "investigation" | "general" → action; type hilang → action
 * (safe default); plain string → action dgn perilaku lama (isi input, onPick) —
 * additive, tidak merusak producer string lama.
 * chipKey tetap dikirim → counter chips_clicked (USER_PROFILE_PLAN Phase 2).
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
  const navigate = useNavigate()
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
          const chip = isChip(sug) ? sug : null
          const label = isChip(sug) ? sug.label : sug
          const key = chip ? chipKeyOf(chip) : undefined
          const isOffer = chipKind(sug) === "offer"
          return (
            <button
              key={label}
              type="button"
              onClick={() => {
                if (isOffer) {
                  // OFFER: navigasi keluar dari percakapan; tanpa target → fallback aman ke onPick
                  if (chip?.target) navigate(chip.target)
                  else onPick(label, key)
                  return
                }
                // ACTION: relay teks via jalur existing
                if (chip?.action && onSend) {
                  onSend(chip.action, key) // legacy investigation chip → auto-send identifier
                } else if (chip?.type === "action" && onSend) {
                  onSend(label, key) // chip bertipe action → teks chip jadi pesan user (§4A.7)
                } else {
                  onPick(label, key) // plain string / legacy general / tanpa onSend → isi input
                }
              }}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-left text-xs transition-colors",
                isOffer
                  ? "bg-muted/50 hover:bg-muted border-border/60 text-foreground/90"
                  : "bg-primary/10 border-primary/30 text-primary hover:bg-primary/20",
              )}
            >
              {isOffer ? <ArrowUpRight className="size-3 shrink-0" /> : <ArrowRight className="size-3 shrink-0" />}
              {label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
