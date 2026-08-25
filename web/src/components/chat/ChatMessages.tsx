import { lazy, useEffect, useRef } from "react"
import { useTranslation } from "react-i18next"
import { StreamingDots } from "@/components/chat/StreamingDots"
import { useChatStore } from "@/store/chat.store"

const EMPTY_MESSAGES: never[] = []

// Code-split: react-markdown + rehype-highlight hanya dimuat saat ada pesan
const ChatMessage = lazy(() => import("@/components/chat/ChatMessage"))

/** List bubble pesan + auto-scroll bottom (hanya bila user memang di bawah). */
export function ChatMessages({ sessionId }: { sessionId: string }) {
  const { t } = useTranslation("project")
  // Selector harus referensi stabil — default [] di luar selector (bukan `s.x ?? []`)
  const messagesMap = useChatStore((s) => s.messages)
  const messages = messagesMap[sessionId] ?? EMPTY_MESSAGES
  const isStreaming = useChatStore((s) => s.isStreaming)
  const streamingText = useChatStore((s) => s.streamingText)
  const bottomRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  useEffect(() => {
    const el = bottomRef.current?.parentElement
    if (el && stickToBottom.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages.length, streamingText, isStreaming])

  return (
    <div
      className="min-h-0 min-w-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
      onScroll={(e) => {
        const el = e.currentTarget
        stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
      }}
    >
      {messages.length === 0 && !isStreaming && (
        <div className="flex h-full flex-col items-center justify-center text-center">
          <div className="flex size-10 items-center justify-center rounded-xl bg-muted text-lg">🤖</div>
          <p className="mt-3 text-sm font-medium">{t("chat.empty_title")}</p>
          <p className="mt-1 max-w-56 text-xs leading-relaxed text-muted-foreground">
            {t("chat.empty_hint")}
          </p>
        </div>
      )}

      {messages.map((m) => (
        <ChatMessage key={m.id} message={m} />
      ))}

      {isStreaming && (
        <>
          {streamingText ? (
            <div className="flex gap-2.5">
              <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
                🤖
              </div>
              <div className="max-w-[85%] whitespace-pre-wrap rounded-xl bg-muted px-3 py-2 text-sm leading-relaxed">
                {streamingText}
                <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/60 align-middle" />
              </div>
            </div>
          ) : (
            <div className="flex gap-2.5">
              <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
                🤖
              </div>
              <div className="flex items-center rounded-xl bg-muted px-3 py-2">
                <StreamingDots />
              </div>
            </div>
          )}
        </>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
