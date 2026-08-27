import { useLayoutEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Send, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useChatStore } from "@/store/chat.store"

/** Input chat: textarea autosize + kirim/stop. Chat selalu terikat tiket (1 sesi = 1 tiket). */
export function ChatInput({ sessionId, disabled }: { sessionId: string; disabled?: boolean }) {
  const { t } = useTranslation("project")
  const [text, setText] = useState("")
  // Streaming di-scope per-session — bukan global, agar tak konflik dgn sesi lain.
  const isStreaming = useChatStore((s) => s.streaming[sessionId]?.isStreaming ?? false)
  const sendMessage = useChatStore((s) => s.sendMessage)
  const stopStream = useChatStore((s) => s.stopStream)
  // Autosize: tinggi textarea mengikuti isian (1 baris = 36px, max ~8 baris = 192px).
  const taRef = useRef<HTMLTextAreaElement | null>(null)
  useLayoutEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = "0"
    const next = Math.min(el.scrollHeight, 192)
    el.style.height = `${Math.max(36, next)}px`
  }, [text])

  const submit = () => {
    const value = text.trim()
    if (value.length < 2 || isStreaming || disabled) return
    setText("")
    void sendMessage(sessionId, value)
  }

  return (
    <div className="min-w-0 space-y-2 border-t px-3 py-2.5">
      <div className="flex items-end gap-2">
        <Textarea
          ref={taRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={t("chat.input_placeholder")}
          className="min-h-9 max-h-48 resize-none overflow-y-auto text-sm"
          rows={1}
          disabled={disabled}
        />
        {isStreaming ? (
          <Button
            size="icon"
            variant="outline"
            className="size-9 shrink-0"
            onClick={stopStream}
            title={t("chat.stop_stream")}
          >
            <Square className="size-3.5" />
          </Button>
        ) : (
          <Button
            size="icon"
            className="size-9 shrink-0"
            disabled={disabled || text.trim().length < 2}
            onClick={submit}
          >
            <Send className="size-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
