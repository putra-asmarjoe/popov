import { useLayoutEffect, useMemo, useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ArrowLeft, Send, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { ChatMessages } from "@/components/chat/ChatMessages"
import { ChatSuggestions } from "@/components/chat/ChatSuggestions"
import { AgentTracePanel } from "@/components/chat/AgentTracePanel"
import { useChatMessages, useChatSessions, useChatStream } from "@/hooks/useChatStream"
import { useChatStore } from "@/store/chat.store"
import { useProjects } from "@/hooks/useWorkspaces"
import { useWorkspaceStore } from "@/store/workspace.store"
import { cn } from "@/lib/utils"
import { lastAssistantMeta } from "@/lib/chat-meta"
import type { Suggestion } from "@/lib/chat-meta"

/**
 * ProjectChatPage — halaman chat ber-konteks project (Chat by Project fase 1).
 * Terpisah dari chat detail tiket: sesi punya projectId TANPA ticketId.
 * Chips dari meta jawaban assistant terakhir (persist server, refresh-safe):
 * - suggestions → isi input dengan saran follow-up (via ChatSuggestions)
 * - ticket_refs → navigate ke detail tiket (/w/:ws/:proj?ticket=KEY-N)
 */

const CHAT_MODES = ["low", "medium", "thinking"] as const
type ChatMode = (typeof CHAT_MODES)[number]

export function ProjectChatPage() {
  const { t } = useTranslation("pchat")
  const { wsSlug = "", sessionId = "" } = useParams()
  const [text, setText] = useState("")
  const [mode, setMode] = useState<ChatMode>("low")
  const { activeWorkspace } = useWorkspaceStore()
  const { data: projects } = useProjects(activeWorkspace?.id ?? null)
  const sessionsQuery = useChatSessions(null, 100) // Fix G1
  const messagesQuery = useChatMessages(sessionId || null)
  const activeTraceMessages = useChatStore((s) => s.activeTraceMessages)
  const activeTraceRequestId = useChatStore((s) => s.activeTraceRequestId)

  // Tutup Agent Trace panel saat pindah session — trace milik session lama
  const closeTrace = useChatStore((s) => s.closeTrace)
  useLayoutEffect(() => {
    closeTrace()
  }, [sessionId, closeTrace])

  const session = useMemo(
    () => sessionsQuery.data?.find((s) => s.id === sessionId) ?? null,
    [sessionsQuery.data, sessionId],
  )
  const project = useMemo(
    () => projects?.find((p) => p.id === session?.projectId) ?? null,
    [projects, session?.projectId],
  )

  // Chips dari meta jawaban assistant TERAKHIR
  const meta = lastAssistantMeta(messagesQuery.data)
  const suggestions = meta?.suggestions ?? []
  const ticketRefs = meta?.ticket_refs ?? []

  return (
    <div className="flex h-full min-w-0">
      <div className="flex h-full min-w-0 flex-1 flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 border-b px-4 py-2.5">
          <div className="mx-auto flex w-full max-w-3xl items-center gap-3">
            <Button variant="ghost" size="icon" className="size-8 shrink-0" asChild>
              <Link to={project ? `/w/${wsSlug}/${project.slug}` : `/w/${wsSlug}`} aria-label={t("back")}>
                <ArrowLeft className="size-4" />
              </Link>
            </Button>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {sessionsQuery.isLoading ? (
                  <Skeleton className="h-4 w-48" />
                ) : (
                  session?.title || t("title_fallback")
                )}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {project ? `${project.key} · ${project.name}` : ""}
              </p>
            </div>
          </div>
        </div>

        {/* Messages */}
        {sessionId ? (
          <ChatMessages sessionId={sessionId} contentClassName="max-w-3xl" />
        ) : (
          <div className="flex flex-1 items-center justify-center px-4 text-sm text-muted-foreground">
            <div className="mx-auto w-full max-w-3xl">{t("no_session")}</div>
          </div>
        )}

        {/* Chips: link tiket (🎟️) — saran follow-up (💡) via ChatSuggestions */}
        {ticketRefs.length > 0 && (
          <div className="border-t px-4 py-2">
            <div className="mx-auto flex max-w-3xl flex-wrap gap-1.5">
              {ticketRefs.map((ref) => {
                const proj = projects?.find((p) => p.key === ref.projectKey) ?? project
                const href = proj ? `/w/${wsSlug}/${proj.slug}?ticket=${proj.key}-${ref.ticketNumber}` : "#"
                return (
                  <Link
                    key={`ref-${ref.ticketId}`}
                    to={href}
                    className="rounded-full border bg-muted/40 px-2.5 py-1 text-xs hover:bg-muted"
                  >
                    🎟️ {ref.projectKey ?? project?.key}-{ref.ticketNumber}
                  </Link>
                )
              })}
            </div>
          </div>
        )}
        {/* Mode selector + input */}
        <div className="border-t px-4 py-2.5">
          <div className="mx-auto w-full max-w-3xl space-y-2">
            <div className="flex items-center gap-1">
              {CHAT_MODES.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  title={t(`mode_hint.${m}`)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-[11px] capitalize",
                    mode === m
                      ? "border-primary bg-primary font-medium text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  {m === "thinking" ? `🧠 ${m}` : m}
                </button>
              ))}
            </div>
            <ProjectChatInput sessionId={sessionId} mode={mode} onTextChange={setText} draft={text} suggestions={suggestions} />
          </div>
        </div>
      </div>

      {/* Trace panel (right side, fixed width) */}
      {activeTraceMessages.length > 0 && (
        <div className="w-[420px] shrink-0 border-l">
          <AgentTracePanel traces={activeTraceMessages} requestId={activeTraceRequestId} />
        </div>
      )}
    </div>
  )
}

/** Input chat project: textarea autosize + kirim (dgn mode depth) / stop stream. */
function ProjectChatInput({
  sessionId,
  mode,
  onTextChange,
  draft,
  suggestions,
}: {
  sessionId: string
  mode: ChatMode
  onTextChange: (v: string) => void
  draft: string
  suggestions: Suggestion[]
}) {
  const { t } = useTranslation("pchat")
  const sendMessage = useChatStream().sendMessage
  const stopStream = useChatStream().stopStream
  // Streaming di-scope per sessionId, bukan global.
  const isStreaming = useChatStore((s) => s.streaming[sessionId]?.isStreaming ?? false)
  // Autosize: tinggi textarea mengikuti isian user (1 baris = 36px, max ~8 baris = 192px).
  const taRef = useRef<HTMLTextAreaElement | null>(null)
  useLayoutEffect(() => {
    const el = taRef.current
    if (!el) return
    // Reset ke 0 lalu ukur scrollHeight agar shrink saat draft dihapus
    el.style.height = "0"
    const next = Math.min(el.scrollHeight, 192) // max 192px
    el.style.height = `${Math.max(36, next)}px` // min 36px (1 baris)
  }, [draft])

  const submit = () => {
    const value = draft.trim()
    if (value.length < 2 || !sessionId || isStreaming) return
    onTextChange("")
    void sendMessage(sessionId, value, mode)
  }

  return (
    <div className="space-y-2">
      <ChatSuggestions suggestions={suggestions} onPick={onTextChange} onSend={(t) => void sendMessage(sessionId, t, mode)} contentClassName="max-w-3xl" />
      <div className="flex items-end gap-2">
      <Textarea
        ref={taRef}
        value={draft}
        onChange={(e) => onTextChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        placeholder={t("input_placeholder")}
        className="min-h-9 max-h-48 resize-none overflow-y-auto py-1.5 text-sm"
        rows={1}
      />
      {isStreaming ? (
        <Button size="icon" variant="outline" className="size-9 shrink-0" onClick={stopStream} aria-label={t("stop")}>
          <Square className="size-3.5" />
        </Button>
      ) : (
        <Button
          size="icon"
          className="size-9 shrink-0"
          disabled={!sessionId || draft.trim().length < 2}
          onClick={submit}
          aria-label={t("send")}
        >
          <Send className="size-4" />
        </Button>
      )}
      </div>
    </div>
  )
}
