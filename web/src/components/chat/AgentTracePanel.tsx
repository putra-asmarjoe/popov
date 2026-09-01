import { useState } from "react"
import { useTranslation } from "react-i18next"
import { GitBranch, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AgentGraphSVG } from "@/components/chat/AgentGraphSVG"
import { AgentNodeDetail } from "@/components/chat/AgentNodeDetail"
import type { AgentTrace } from "@/types/chat"
import { useChatStore } from "@/store/chat.store"

/** Panel kanan untuk visualisasi agent trace (Fix #150).
 *  Dibuka dari klik bubble assistant → mendorong chat panel ke kiri.
 *  Close via tombol X di header atau klik backdrop. */
export function AgentTracePanel({ traces, requestId }: { traces: AgentTrace[]; requestId?: string | null }) {
  const { t } = useTranslation("project")
  const [selected, setSelected] = useState<string | null>(traces[0]?.agent ?? null)
  const selectedTrace = traces.find((tr) => tr.agent === selected) ?? traces[0] ?? null
  const closeTrace = useChatStore((s) => s.closeTrace)

  if (traces.length === 0) return null

  return (
    <div className="flex h-full min-w-0 flex-col border-l bg-background">
      {/* Header */}
      <div className="flex h-11 shrink-0 items-center gap-2 border-b px-3">
        <GitBranch className="size-4 shrink-0 text-primary" />
        <span className="min-w-0 truncate text-xs font-semibold text-muted-foreground">
          {t("chat.trace_panel_title")}
        </span>
        {requestId && (
          <span className="min-w-0 max-w-[5.5rem] shrink truncate font-mono text-[10px] text-muted-foreground/60" title={requestId}>
            #{requestId.slice(0, 8)}
          </span>
        )}
        <div className="ml-auto shrink-0">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={closeTrace}
            aria-label={t("panel.close")}
          >
            <X className="size-3.5" />
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="space-y-4">
          {/* Graph: node cards + koneksi */}
          <AgentGraphSVG traces={traces} selectedAgent={selected} onSelect={setSelected} />

          {/* Detail node terpilih */}
          <div className="border-t pt-3">
            {selectedTrace ? (
              <AgentNodeDetail trace={selectedTrace} />
            ) : (
              <p className="text-xs text-muted-foreground">{t("chat.trace_no_data")}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
