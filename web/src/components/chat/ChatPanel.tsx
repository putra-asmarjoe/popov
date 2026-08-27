import { useEffect, useMemo, useRef } from "react"
import { useTranslation } from "react-i18next"
import { Bot, Loader2 } from "lucide-react"
import { ChatInput } from "@/components/chat/ChatInput"
import { ChatMessages } from "@/components/chat/ChatMessages"
import { useChatMessages, useChatSessions, useCreateChatSession } from "@/hooks/useChatStream"
import { useChatStore, recentlyFinalized } from "@/store/chat.store"
import { api } from "@/lib/api"
import type { TicketContext } from "@/types/chat"

/**
 * ChatPanel — chat yang TERIKAT ke satu tiket (1 sesi chat = 1 tiket).
 * Sesi ditentukan/dibuat otomatis dari `ticket.ticketId`; tidak ada "chat baru"
 * atau perpindahan sesi di sini (chat umum/global dikembangkan terpisah nanti).
 */
export function ChatPanel({
  projectId,
  ticket,
}: {
  projectId: string
  /** Konteks tiket yang mengikat sesi; null = mode non-tiket (belum dipakai). */
  ticket: TicketContext | null
}) {
  const { t } = useTranslation("project")
  const { data: sessions, isLoading } = useChatSessions(projectId)
  const createSession = useCreateChatSession(projectId)
  const setActiveSession = useChatStore((s) => s.setActiveSession)
  const setTicketContext = useChatStore((s) => s.setTicketContext)
  const clearTicketContext = useChatStore((s) => s.clearTicketContext)

  // Sesi tiket ini = session pertama dengan ticketId yang cocok
  const ticketSession = useMemo(
    () => (ticket ? (sessions?.find((s) => s.ticketId === ticket.ticketId) ?? null) : null),
    [sessions, ticket],
  )
  useChatMessages(ticketSession?.id ?? null)

  // Auto-buat sesi saat belum ada (sekali per tiket; ref mencegah dobel create)
  const requestedTicketId = useRef<string | null>(null)
  useEffect(() => {
    if (isLoading || !ticket || ticketSession) return
    if (requestedTicketId.current === ticket.ticketId) return
    requestedTicketId.current = ticket.ticketId
    createSession.mutate({
      ticketId: ticket.ticketId,
      title: `${ticket.ticketNumber} · ${ticket.title.slice(0, 60)}`,
    })
  }, [isLoading, ticket, ticketSession, createSession])

  // Sinkronkan store: stopStream memakai activeSession.id saat menyimpan potongan jawaban
  useEffect(() => {
    if (ticketSession) setActiveSession(ticketSession)
  }, [ticketSession, setActiveSession])

  // Fix #114: setelah refresh, pipeline server mungkin masih berjalan —
  // cek status sesi → ikut stream (tombol Stop tampil, bukan Send).
  // Streaming state di-scope per sessionId — bukan global.
  const attachStream = useChatStore((s) => s.attachStream)
  const sid = ticketSession?.id
  const isStreaming = useChatStore((s) => s.streaming[sid ?? ""]?.isStreaming ?? false)
  useEffect(() => {
    if (!sid || isStreaming) return
    if (recentlyFinalized()) return // baru selesai — jangan attach ulang ke stream mati
    let cancelled = false
    api
      .get(`/chat/sessions/${sid}/active`)
      .then(({ data }) => {
        if (
          !cancelled &&
          data?.active &&
          !useChatStore.getState().streaming[sid]?.isStreaming &&
          !recentlyFinalized()
        ) {
          attachStream(sid)
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [sid, isStreaming, attachStream])

  // Konteks tiket untuk prefix pesan (buildEnrichedMessage di chat.store)
  useEffect(() => {
    if (ticket) setTicketContext(ticket)
    else clearTicketContext()
  }, [ticket, setTicketContext, clearTicketContext])

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      {/* Header */}
      <div className="flex h-11 shrink-0 items-center gap-2 border-b px-3">
        <Bot className="size-4 shrink-0 text-primary" />
        <span className="truncate text-xs font-semibold text-muted-foreground">
          {ticket ? t("chat.ticket_header", { number: ticket.ticketNumber }) : t("chat.generic_header")}
        </span>
        {isLoading && <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" />}
      </div>

      {ticketSession ? (
        <>
          <ChatMessages sessionId={ticketSession.id} />
          <ChatInput sessionId={ticketSession.id} />
        </>
      ) : (
        <div className="flex flex-1 items-center justify-center text-xs text-muted-foreground">
          <Loader2 className="mr-2 size-3.5 animate-spin" /> {t("chat.preparing_session")}
        </div>
      )}
    </div>
  )
}