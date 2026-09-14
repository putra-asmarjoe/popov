import { useTranslation } from "react-i18next"
import { useChatStore } from "@/store/chat.store"
import { cn } from "@/lib/utils"

/** CHAT3 §4A.3 — SSE node → i18n key (K9, Rev 8). Nama node = nama graph node REAL
 *  (AGENT_BRIEF, 16 node). Label TIDAK pernah berisi reasoning — hanya aktivitas. */
const NODE_ACTIVITY_KEY: Record<string, string> = {
  supervisor: "activity.supervisor",
  triage_agent: "activity.triage",
  mongo_agent: "activity.mongo",
  metrics_agent: "activity.metrics",
  k8s_agent: "activity.k8s",
  trace_agent: "activity.trace",
  span_agent: "activity.span",
  correlation_agent: "activity.correlation",
  health_agent: "activity.health",
  data_agent: "activity.data",
  follow_up_agent: "activity.followup",
  response_agent: "activity.response",
  knowledge_agent: "activity.knowledge",
  ticket_agent: "activity.ticket",
  project_agent: "activity.project",
  planner_node: "activity.planner",
  chat_agent: "activity.chat", // Phase 2
}

/**
 * ThinkingSteps — activity list KOMPAK (CHAT3 §4A.2), bukan panel prominen:
 * header "● Activity/Proses" + baris ✓/● per node graph dari SSE.
 * Visibility MODE-DECOUPLED (owner ALT3 §13): tampil sejak event node pertama,
 * auto-dismiss saat stream selesai (store clear di finalize/stopStream).
 * Tujuan = latency perception, BUKAN expose chain-of-thought.
 * Streaming di-scope per sessionId — tidak bocor dari sesi lain.
 */
export function ThinkingSteps({ sessionId }: { sessionId: string }) {
  const { t } = useTranslation("common")
  const steps = useChatStore((s) => s.thinkingSteps[sessionId])
  const isStreaming = useChatStore((s) => s.streaming[sessionId]?.isStreaming ?? false)

  if (!isStreaming || !steps || steps.length === 0) return null

  return (
    <div className="flex gap-2.5" data-testid="thinking-steps">
      {/* gutter = lebar avatar (size-7) agar rata dengan kolom bubble response */}
      <div className="size-7 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 rounded-lg border border-border/60 bg-muted/40 px-3 py-2">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          <span className="inline-block size-1.5 animate-pulse rounded-full bg-primary/70" />
          {t("activity.title")}
        </div>
        <ul className="mt-1.5 space-y-1">
          {steps.map((node, i) => {
            const isLast = i === steps.length - 1
            const label = NODE_ACTIVITY_KEY[node] ? t(NODE_ACTIVITY_KEY[node]) : node
            return (
              <li
                key={`${node}-${i}`}
                className={cn(
                  "flex items-center gap-1.5 text-xs",
                  isLast ? "text-foreground/90" : "text-muted-foreground",
                )}
              >
                <span
                  className={cn("shrink-0", isLast ? "animate-pulse text-primary" : "text-green-500")}
                  aria-hidden
                >
                  {isLast ? "●" : "✓"}
                </span>
                {label}
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
