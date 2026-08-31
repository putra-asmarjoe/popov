import { useTranslation } from "react-i18next"
import ReactMarkdown from "react-markdown"
import rehypeHighlight from "rehype-highlight"
import { Bot, User, GitBranch } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ChatMessage as ChatMessageType, AgentTrace } from "@/types/chat"
import { useChatStore } from "@/store/chat.store"

/** Satu bubble pesan — assistant dirender sebagai Markdown + syntax highlight.
 *  Default export: di-lazy-load ChatMessages (code-split react-markdown+highlight.js).
 *  Fase 2: bubble assistant klikabel bila meta.agent_traces ada → buka graph trace. */
export function ChatMessage({ message }: { message: ChatMessageType }) {
  const { t } = useTranslation("project")
  const isUser = message.role === "user"
  const traces = (message.meta?.agent_traces as AgentTrace[] | undefined) ?? []
  const requestId = (message.meta?.request_id as string | undefined) ?? null
  const openTrace = useChatStore((s) => s.openTrace)

  return (
    <div className={cn("flex min-w-0 gap-2.5", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted",
        )}
      >
        {isUser ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
      </div>
      <div
        className={cn(
          "min-w-0 max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted",
          !isUser && traces.length > 0 && "cursor-pointer hover:ring-1 hover:ring-primary/40",
        )}
        onClick={() => {
          if (!isUser && traces.length > 0) openTrace(message.id, traces, requestId)
        }}
        title={!isUser && traces.length > 0 ? t("chat.trace_hint") : undefined}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="chat-markdown prose-sm break-words [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-code-block [&_pre]:p-2.5 [&_pre]:text-xs [&_pre]:text-code-block-fg [&_pre]:border [&_pre]:border-code-block-border [&_code]:font-mono [&_p]:my-1.5 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-4 [&_strong]:font-semibold [&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-sm [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold">
            <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{message.content}</ReactMarkdown>
          </div>
        )}
        {!isUser && traces.length > 0 && (
          <div className="mt-1.5 flex items-center gap-1 text-[10px] text-muted-foreground/70">
            <GitBranch className="size-3" />
            {traces.length} {t("chat.trace_label")}
          </div>
        )}
      </div>
    </div>
  )
}

export default ChatMessage
