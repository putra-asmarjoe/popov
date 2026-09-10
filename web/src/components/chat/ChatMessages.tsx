import { lazy, useEffect, useMemo, useRef } from "react"
import { useTranslation } from "react-i18next"
import { Link } from "react-router-dom"
import { StreamingDots } from "@/components/chat/StreamingDots"
import { ChatSuggestions } from "@/components/chat/ChatSuggestions"
import type { Suggestion } from "@/lib/chat-meta"
import { useChatStore } from "@/store/chat.store"
import { cn } from "@/lib/utils"

const EMPTY_MESSAGES: never[] = []
const EMPTY_STREAM = { isStreaming: false, streamingText: "", activeAgent: null as string | null }

// Code-split: react-markdown + rehype-highlight hanya dimuat saat ada pesan
const ChatMessage = lazy(() => import("@/components/chat/ChatMessage"))

export interface TicketRefProp {
  ticketNumber: number
  ticketId: string
  projectKey?: string
  title?: string | null
  status?: string | null
}

export interface ProjectProp {
  id: string
  key: string
  name: string
  slug: string
}

/** List bubble pesan + auto-scroll bottom (hanya bila user memang di bawah).
 *  `contentClassName` opsional untuk wrap konten dengan container max-width
 *  (Project Chat rampingkan konten, Chat Panel tiket tetap full-bleed). */
export function ChatMessages({
  sessionId,
  contentClassName,
  suggestions,
  ticketRefs,
  projects,
  project,
  wsSlug,
  onPickSuggestion,
  onSendSuggestion,
}: {
  sessionId: string
  contentClassName?: string
  suggestions?: Suggestion[]
  ticketRefs?: TicketRefProp[]
  projects?: ProjectProp[]
  project?: ProjectProp | null
  wsSlug?: string
  onPickSuggestion?: (text: string, chipKey?: string) => void
  onSendSuggestion?: (text: string, chipKey?: string) => void
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  // Hitung jumlah pesan user — bertambah = user baru kirim pesan, dipaksa scroll ke bawah
  const userMessageCount = useMemo(
    () => messages.filter((m) => m.role === "user").length,
    [messages],
  )
  const prevUserMessageCount = useRef(userMessageCount)

  const scrollToBottom = useRef(() => {})
  useEffect(() => {
    scrollToBottom.current = () => {
      const el = scrollRef.current
      if (el) {
        el.scrollTop = el.scrollHeight
      }
    }
  }, [])

  // Auto-scroll langsung via ResizeObserver saat tinggi konten berubah
  useEffect(() => {
    const scroller = scrollRef.current
    const content = bottomRef.current?.parentElement
    if (!scroller || !content || typeof ResizeObserver === "undefined") return

    const scheduleScroll = () => {
      if (stickToBottom.current) scrollToBottom.current()
    }

    let lastScrollerHeight = scroller.clientHeight
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.target === scroller) {
          const h = entry.contentRect.height
          if (Math.abs(h - lastScrollerHeight) < 0.5) continue
          lastScrollerHeight = h
        }
        scheduleScroll()
      }
    })
    ro.observe(content)   // tinggi konten berubah (pesan baru, markdown settle, chips)
    ro.observe(scroller)  // tinggi viewport berubah (trace panel toggle)
    return () => {
      ro.disconnect()
    }
  }, [])

  // Posisi reader-centric: saat user kirim pesan & scrollbar sudah ada, posisikan
  // pertanyaan user di tengah/atas-tengah viewport secara smooth agar user membaca
  // jawaban dari awal. Bila belum ada scrollbar, biarkan terbentuk alami.
  useEffect(() => {
    if (userMessageCount > prevUserMessageCount.current) {
      prevUserMessageCount.current = userMessageCount
      stickToBottom.current = false // Jangan paksa scroll ke paling dasar saat streaming

      const raf = requestAnimationFrame(() => {
        const scroller = scrollRef.current
        if (!scroller) return

        // Cek apakah scrollbar sudah terbentuk di container chat
        const hasScroll = scroller.scrollHeight > scroller.clientHeight
        if (!hasScroll) return // Belum ada scrollbar -> biarkan terbentuk alami

        const userElements = scroller.querySelectorAll('[data-role="user"]')
        const lastUserEl = userElements[userElements.length - 1] as HTMLElement | undefined
        if (lastUserEl) {
          const relativeTop = lastUserEl.offsetTop
          const targetTop = Math.max(0, relativeTop - scroller.clientHeight * 0.25)
          scroller.scrollTo({
            top: targetTop,
            behavior: "smooth",
          })
        }
      })
      return () => cancelAnimationFrame(raf)
    }
    prevUserMessageCount.current = userMessageCount
  }, [userMessageCount])

  return (
    <div
      ref={scrollRef}
      className="min-h-0 min-w-0 flex-1 overflow-y-auto"
      style={{ overflowAnchor: "none" }}
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

        {/* Embedded ticket refs & recommendation chips inside scroll stream */}
        {!isStreaming && (
          <div className="space-y-1.5 pt-1">
            {ticketRefs && ticketRefs.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {ticketRefs.map((ref) => {
                  const proj = projects?.find((p) => p.key === ref.projectKey) ?? project
                  const href = proj ? `/w/${wsSlug}/${proj.slug}?ticket=${proj.key}-${ref.ticketNumber}` : "#"
                  return (
                    <Link
                      key={`ref-${ref.ticketId}`}
                      to={href}
                      className="inline-flex items-center rounded-full border border-border/60 bg-muted/50 px-2.5 py-1 text-xs hover:bg-muted"
                    >
                      🎟️ {ref.projectKey ?? project?.key}-{ref.ticketNumber}
                    </Link>
                  )
                })}
              </div>
            )}
            {suggestions && suggestions.length > 0 && onPickSuggestion && (
              <ChatSuggestions
                suggestions={suggestions}
                onPick={onPickSuggestion}
                onSend={onSendSuggestion}
              />
            )}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
