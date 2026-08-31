import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { FileText, Search } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useAvailableAgentDocs, useLinkAgentDoc } from "@/hooks/useKnowledge"
import type { AgentDoc } from "@/types/knowledge"

interface Props {
  wsId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  excludeKeys?: Set<string>
}

const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "services", label: "Services" },
  { id: "connections", label: "Connections" },
  { id: "schemas", label: "Schemas" },
  { id: "observability", label: "Observability" },
  { id: "playbooks", label: "Playbooks" },
  { id: "general", label: "General" },
]

/**
 * AgentDocsPicker — picker dialog untuk mengkoneksikan grounding docs dari Management ke workspace.
 * Read-only reference — tidak ada CRUD, hanya link/unlink.
 */
export function AgentDocsPicker({ wsId, open, onOpenChange, excludeKeys }: Props) {
  const { t } = useTranslation("management")
  const { data: docs, isLoading } = useAvailableAgentDocs(wsId)
  const link = useLinkAgentDoc(wsId)
  const [filter, setFilter] = useState("all")
  const [search, setSearch] = useState("")

  const filtered = useMemo(() => {
    if (!docs) return []
    return docs.filter((d) => {
      const key = `${d.category}/${d.key}`
      if (excludeKeys?.has(key)) return false
      if (filter !== "all" && d.category !== filter) return false
      if (search && !d.key.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [docs, filter, search, excludeKeys])

  const handleConnect = (doc: AgentDoc) => {
    link.mutate(
      { category: doc.category, key: doc.key },
      { onSuccess: () => {} },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("knowledge_lib.grounding_picker_title")}</DialogTitle>
          <DialogDescription>{t("knowledge_lib.grounding_picker_desc")}</DialogDescription>
        </DialogHeader>

        {/* Category filter + Search */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1">
            {CATEGORIES.map((c) => (
              <button
                key={c.id}
                className={`rounded px-2.5 py-1 text-xs transition-colors ${
                  filter === c.id
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                }`}
                onClick={() => setFilter(c.id)}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div className="relative ml-auto">
            <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              className="h-7 rounded-md border bg-transparent pl-7 pr-2 text-xs"
              placeholder="Search…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto -mx-6 px-6">
          {isLoading ? (
            <div className="space-y-2 py-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              {t("knowledge_lib.grounding_picker_empty")}
            </div>
          ) : (
            <div className="space-y-1 py-2">
              {filtered.map((doc) => {
                const key = `${doc.category}/${doc.key}`
                return (
                  <div
                    key={key}
                    className="flex items-center gap-2.5 rounded-md border px-3 py-2 hover:bg-muted/50"
                  >
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-xs font-medium">{doc.key}</p>
                      <p className="text-[11px] text-muted-foreground">
                        {doc.category} · {(doc.body_len ?? 0).toLocaleString()} chars
                      </p>
                    </div>
                    <Badge variant="secondary" className="shrink-0 text-[10px]">
                      {doc.category}
                    </Badge>
                    <Button
                      size="sm"
                      variant="outline"
                      className="shrink-0"
                      disabled={link.isPending}
                      onClick={() => handleConnect(doc)}
                    >
                      Connect
                    </Button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
