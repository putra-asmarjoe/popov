import { lazy, Suspense, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { FileText, Library, Link2, Trash2 } from "lucide-react"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useLinkKnowledge, useMyLibrary, useUnlinkKnowledge, useWorkspaceKnowledge } from "@/hooks/useKnowledge"
import type { WorkspaceKnowledgeRef } from "@/types/knowledge"

const MarkdownView = lazy(() => import("@/components/shared/MarkdownView"))

interface Props {
  wsId: string
  isAdmin: boolean
}

/**
 * Section Knowledge (WorkspaceSettingsPage) — FE-7.
 * Member: baca + preview. Admin: link dari library sendiri / tulis baru (masuk library dulu), lepas link.
 * Popov Agent memakai knowledge ini saat menganalisis via chat/tiket di workspace ini.
 */
export function WorkspaceKnowledge({ wsId, isAdmin }: Props) {
  const { t } = useTranslation("workspace")
  const { data: refs, isLoading } = useWorkspaceKnowledge(wsId)
  const { data: myLibrary } = useMyLibrary()
  const link = useLinkKnowledge(wsId)
  const unlink = useUnlinkKnowledge(wsId)
  const [preview, setPreview] = useState<WorkspaceKnowledgeRef | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<WorkspaceKnowledgeRef | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)

  // item library milikku yang BELUM ter-link ke workspace ini
  const linkable = useMemo(() => {
    const linked = new Set((refs ?? []).map((r) => r.libraryId))
    return (myLibrary ?? []).filter((i) => !linked.has(i.id))
  }, [refs, myLibrary])

  return (
    <div className="mt-8">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{t("knowledge.title")}</h2>
          <p className="text-xs text-muted-foreground">
            {t("knowledge.description")}
            {!isAdmin && t("knowledge.admin_only_hint")}
          </p>
        </div>
        {isAdmin && (
          <div className="flex gap-2">
            <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setPickerOpen(true)}>
              <Library className="size-4" /> {t("knowledge.from_library")}
            </Button>
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-lg border">
        {isLoading ? (
          <div className="p-3"><Skeleton className="h-9 w-full" /></div>
        ) : (refs ?? []).length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-10 text-center text-muted-foreground">
            <FileText className="size-8 opacity-40" />
            <p className="text-sm">{t("knowledge.empty")}</p>
            {isAdmin && (
              <p className="text-xs">{t("knowledge.admin_empty_hint")}</p>
            )}
          </div>
        ) : (
          (refs ?? []).map((ref) => (
            <div key={ref.id} className="flex items-center gap-2.5 border-b px-3 py-2 last:border-b-0">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <button className="min-w-0 flex-1 text-left" onClick={() => setPreview(ref)}>
                <p className="truncate font-mono text-xs font-medium hover:underline">{ref.name}</p>
                <p className="text-[11px] text-muted-foreground">{t("knowledge.category_prefix", { folder: ref.folder })}</p>
              </button>
              <Badge variant="secondary" className="shrink-0 text-[10px]">{ref.folder}</Badge>
              {isAdmin && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 text-destructive hover:text-destructive"
                  onClick={() => setConfirmRemove(ref)}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </div>
          ))
        )}
      </div>

      {/* Picker dari library */}
      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("knowledge.picker_title")}</DialogTitle>
            <DialogDescription>{t("knowledge.picker_description")}</DialogDescription>
          </DialogHeader>
          <div className="max-h-80 space-y-1.5 overflow-y-auto">
            {linkable.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t("knowledge.picker_empty")}
              </p>
            ) : (
              linkable.map((item) => (
                <button
                  key={item.id}
                  className="flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left hover:bg-accent disabled:opacity-50"
                  disabled={link.isPending}
                  onClick={() =>
                    link.mutate(item.id, {
                      onSuccess: () => setPickerOpen(false),
                    })
                  }
                >
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">{item.name}</span>
                  <Badge variant="secondary" className="text-[10px]">{item.folder}</Badge>
                  <Link2 className="size-3.5 shrink-0 opacity-50" />
                </button>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Preview konten */}
      <Dialog open={!!preview} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="max-w-2xl overflow-y-auto max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{preview?.name}</DialogTitle>
            <DialogDescription>{t("knowledge.preview_category", { folder: preview?.folder ?? "" })}</DialogDescription>
          </DialogHeader>
          <Suspense fallback={<Skeleton className="h-40 w-full" />}>
            {preview && (
              <MarkdownView content={preview.content ?? ""} className="min-h-24 rounded-md" />
            )}
          </Suspense>
        </DialogContent>
      </Dialog>

      {/* Lepas link */}
      <AlertDialog open={!!confirmRemove} onOpenChange={(open) => !open && setConfirmRemove(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("knowledge.unlink_title", { name: confirmRemove?.name ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("knowledge.unlink_description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmRemove) unlink.mutate(confirmRemove.id)
                setConfirmRemove(null)
              }}
            >
              {t("knowledge.unlink_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
