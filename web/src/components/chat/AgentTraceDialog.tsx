import { useState } from "react"
import { useTranslation } from "react-i18next"
import { GitBranch } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { AgentGraphSVG } from "@/components/chat/AgentGraphSVG"
import { AgentNodeDetail } from "@/components/chat/AgentNodeDetail"
import type { AgentTrace } from "@/types/chat"

/** Modal visualisasi per-agent trace (Fase 2): graph node + detail per agent.
 *  Dibuka dari klik bubble assistant (bila meta.agent_traces ada). */
export function AgentTraceDialog({
  open,
  onOpenChange,
  traces,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  traces: AgentTrace[]
}) {
  const { t } = useTranslation("project")
  const [selected, setSelected] = useState<string | null>(traces[0]?.agent ?? null)
  const selectedTrace = traces.find((tr) => tr.agent === selected) ?? traces[0] ?? null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-[95vw] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranch className="size-4 text-primary" />
            {t("chat.trace_title")}
          </DialogTitle>
          <DialogDescription>{t("chat.trace_desc")}</DialogDescription>
        </DialogHeader>

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
      </DialogContent>
    </Dialog>
  )
}
