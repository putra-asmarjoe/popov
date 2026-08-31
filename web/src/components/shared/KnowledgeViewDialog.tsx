import { lazy, Suspense } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

const MarkdownView = lazy(() =>
  import("@/components/shared/MarkdownView").then((m) => ({ default: m.MarkdownView })),
)

export interface ViewDocState {
  name: string
  folder?: string
  content: string
  meta?: Record<string, any>
}

export interface KnowledgeTabItem {
  knowledgeLibraryId: string
  name: string
  folder: string
}

export function KnowledgeViewDialog({
  doc,
  onClose,
  items,
  activeKnowledgeId,
  onNavigate,
}: {
  doc: ViewDocState | null
  onClose: () => void
  items?: KnowledgeTabItem[]
  activeKnowledgeId?: string
  onNavigate?: (knowledgeLibraryId: string) => void
}) {
  const showTabs = items && items.length > 1 && onNavigate

  return (
    <Dialog open={!!doc} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-4xl overflow-y-auto max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm flex items-center gap-2">
            <span>{doc?.name}</span>
            {doc?.folder && (
              <span className="text-[10px] font-sans px-2 py-0.5 rounded bg-muted text-muted-foreground border">
                {doc.folder}
              </span>
            )}
          </DialogTitle>
        </DialogHeader>

        {/* Tabs for switching between knowledge items */}
        {showTabs && (
          <div className="flex gap-1.5 overflow-x-auto pb-5">
            {items.map((item) => (
              <button
                key={item.knowledgeLibraryId}
                type="button"
                className={cn(
                  "shrink-0 rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
                  item.knowledgeLibraryId === activeKnowledgeId
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground",
                )}
                onClick={() => onNavigate(item.knowledgeLibraryId)}
              >
                {item.name}
              </button>
            ))}
          </div>
        )}

        {/* Structured Meta JSON */}
        {doc?.meta && Object.keys(doc.meta).length > 0 && (
          <div className="rounded-md border bg-muted/40 p-3 space-y-1.5">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
              Meta (JSON)
            </p>
            <pre className="text-xs font-mono bg-background p-2.5 rounded border overflow-x-auto leading-relaxed">
              {JSON.stringify(doc.meta, null, 2)}
            </pre>
          </div>
        )}

        {doc && !doc.content ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <Suspense fallback={<Skeleton className="h-48 w-full" />}>
            <div className="min-h-24 rounded-md border bg-muted/30 p-4">
              <MarkdownView content={doc?.content ?? ""} />
            </div>
          </Suspense>
        )}
      </DialogContent>
    </Dialog>
  )
}
