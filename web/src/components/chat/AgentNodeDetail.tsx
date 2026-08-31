import { useTranslation } from "react-i18next"
import type { AgentTrace } from "@/types/chat"

/** Detail satu node agent: durasi + ringkasan hasil (key-value). Per-Agent Tracing Fase 2. */
export function AgentNodeDetail({ trace }: { trace: AgentTrace }) {
  const { t } = useTranslation("project")
  const dur = trace.duration_ms
  const entries = Object.entries(trace.summary || {})

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-lg border bg-muted/40 px-3 py-2">
        <span className="text-sm font-semibold">{trace.agent}</span>
        <span className="text-xs text-muted-foreground">
          {dur == null ? "…" : `${(dur / 1000).toFixed(2)}s`}
        </span>
      </div>

      {entries.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("chat.trace_no_data")}</p>
      ) : (
        <dl className="space-y-1.5">
          {entries.map(([k, v]) => (
            <div key={k} className="rounded-md border bg-background px-3 py-1.5">
              <dt className="text-[11px] font-medium text-muted-foreground">{k}</dt>
              <dd className="mt-0.5 break-words font-mono text-xs">
                {typeof v === "object" ? JSON.stringify(v) : String(v)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
