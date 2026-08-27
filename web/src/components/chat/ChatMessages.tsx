import { lazy, useEffect, useMemo, useRef } from "react"
import { useTranslation } from "react-i18next"
import { StreamingDots } from "@/components/chat/StreamingDots"
import { useChatStore } from "@/store/chat.store"
import { cn } from "@/lib/utils"

const EMPTY_MESSAGES: never[] = []
const EMPTY_STREAM = { isStreaming: false, streamingText: "", activeAgent: null as string | null }

// Code-split: react-markdown + rehype-highlight hanya dimuat saat ada pesan
const ChatMessage = lazy(() => import("@/components/chat/ChatMessage"))

/** List bubble pesan + auto-scroll bottom (hanya bila user memang di bawah).
 *  `contentClassName` opsional untuk wrap konten dengan container max-width
 *  (Project Chat rampinge konten, Chat Panel tiket tetap full-bleed). */
export function ChatMessages({
  sessionId,
  contentClassName,
}: {
  sessionId: string
  contentClassName?: string
}) {
  const { t } = useTranslation("project")
  // Selector harus referensi stabil — default [] di luar selector (bukan `s.x ?? []`)
  const messagesMap = useChatStore((s) => s.messages)
  const messages = messagesMap[sessionId] ?? EMPTY_MESSAGES
  // Streaming di-scope PER SESSION — agar perpindahan halaman chat tidak bocor.
  const streamMap = useChatStore((s) => s.streaming)
  const stream = useMemo(
    () => streamMap[sessionId] ?? EMPTY_STREAM,
    [streamMap, sessionId],
  )
  const isStreaming = stream.isStreaming
  const streamingText = stream.streamingText
  const bottomRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  // Hitung jumlah pesan user — bertambah = user baru kirim pesan, dipaksa scroll ke bawah
  // agar agent progress + jawaban berikutnya langsung terlihat tanpa scroll manual.
  const userMessageCount = useMemo(
    () => messages.filter((m) => m.role === "user").length,
    [messages],
  )
  const prevUserMessageCount = useRef(userMessageCount)
  useEffect(() => {
    // User baru kirim pesan → kunci scroll ke bawah (override posisi baca history).
    // Pakai scrollIntoView agar independen dari struktur parent (scroll container
    // adalah ancestor overflow-y-auto — browser auto-scroll nearest scroller).
    if (userMessageCount > prevUserMessageCount.current) {
      stickToBottom.current = true
    }
    prevUserMessageCount.current = userMessageCount
    if (stickToBottom.current) {
      bottomRef.current?.scrollIntoView({ block: "end" })
    }
  }, [messages.length, userMessageCount, streamingText, isStreaming])

  return (
    <div
      className="min-h-0 min-w-0 flex-1 overflow-y-auto"
      onScroll={(e) => {
        const el = e.currentTarget
        stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
      }}
    >
      <div className={cn("mx-auto space-y-3 px-3 py-3", contentClassName)}>
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
                  <StreamingDots sessionId={sessionId} />
                </div>
              </div>
            )}
          </>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
