import { lazy, Suspense, useRef, useState } from "react"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { BookMarked, Eye, FileText, Link2, Pencil, Trash2, Upload } from "lucide-react"
import { api, apiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  fetchKnowledgeUsage,
  useCreateKnowledge,
  useDeleteKnowledge,
  useManagementLibrary,
  useMyLibrary,
  useUpdateKnowledge,
} from "@/hooks/useKnowledge"
import type { KnowledgeFolder, KnowledgeItem, KnowledgeUsage } from "@/types/knowledge"

const MarkdownView = lazy(() => import("@/components/shared/MarkdownView"))

interface EditorState {
  item: KnowledgeItem | null
  name: string
  folder: KnowledgeFolder
  content: string
  metaJson: string
}

interface KnowledgeLibraryProps {
  mode?: "management" | "selection"
  onSelect?: (item: KnowledgeItem) => void
  hideHeader?: boolean
  excludeIds?: string[]
}

/**
 * Tab Knowledge (/management) — FE-7: Library Pribadi.
 * Dokumen milik uploader saja; dipakai ulang dengan me-link ke workspace.
 * Bisa dipakai dalam mode "selection" untuk pemilihan di dialog (WorkspaceKnowledge).
 * mode=selection = read-only picker dari Management library (admin-owned) + Grounding docs.
 */
export function KnowledgeLibrary({ mode = "management", onSelect, hideHeader = false, excludeIds = [] }: KnowledgeLibraryProps) {
  const { t } = useTranslation("management")
  const FOLDERS: { id: KnowledgeFolder; label: string }[] = [
    { id: "general", label: t("knowledge_lib.folder_general") },
    { id: "services", label: t("knowledge_lib.folder_services") },
    { id: "playbooks", label: t("knowledge_lib.folder_playbooks") },
    { id: "schemas", label: t("knowledge_lib.folder_schemas") },
    { id: "connections", label: t("knowledge_lib.folder_connections") },
    { id: "observability", label: t("knowledge_lib.folder_observability") },
  ]
  const myLib = useMyLibrary()
  const mgmtLib = useManagementLibrary()
  const isSelection = mode === "selection"
  const { data: items, isLoading } = isSelection ? mgmtLib : myLib
  
  const all = items ?? []
  const create = useCreateKnowledge()
  const update = useUpdateKnowledge()
  const remove = useDeleteKnowledge()
  const fileRef = useRef<HTMLInputElement>(null)

  const [category, setCategory] = useState<KnowledgeFolder>("general")
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [editorMode, setEditorMode] = useState<"tulis" | "preview">("tulis")
  const [confirmDelete, setConfirmDelete] = useState<{
    item: KnowledgeItem
    workspaces?: KnowledgeUsage[]
  } | null>(null)
  const [preview, setPreview] = useState<{ item: KnowledgeItem; content: string } | null>(null)

  const filtered = all.filter((i) => {
    if (i.folder !== category) return false
    if (isSelection && excludeIds.includes(i.id)) return false
    return true
  })

  // View: baca dokumen dalam render Markdown rapi (bukan mentah)
  const openPreview = async (item: KnowledgeItem) => {
    try {
      setPreview({ item, content: "" })
      let endpoint: string
      if (isSelection) {
        endpoint = `/knowledge/management-library/${item.id}`
      } else {
        endpoint = `/knowledge/library/${item.id}`
      }
      const { data } = await api.get(endpoint)
      const content = data.content ?? ""
      setPreview({ item, content })
    } catch (e) {
      setPreview(null)
      toast.error(apiErrorMessage(e, t("knowledge_lib.load_failed")))
    }
  }

  const openCreate = () => {
    setEditorMode("tulis")
    setEditor({ item: null, name: "", folder: category, content: "", metaJson: "{}" })
  }
  const openEdit = (item: KnowledgeItem) => {
    void fetchContentAndOpen(item)
  }

  const fetchContentAndOpen = async (item: KnowledgeItem) => {
    try {
      const { data } = await api.get(`/knowledge/library/${item.id}`)
      setEditorMode("tulis")
      setEditor({
        item,
        name: data.name ?? item.name,
        folder: data.folder ?? item.folder,
        content: data.content ?? "",
        metaJson: JSON.stringify(data.meta ?? {}, null, 2),
      })
    } catch {
      setEditor({ item, name: item.name, folder: item.folder, content: "", metaJson: "{}" })
    }
  }

  const onFile = async (file: File | undefined) => {
    if (!file || !editor) return
    const text = await file.text()
    setEditor({ ...editor, name: file.name.replace(/\.md$/i, ""), content: text })
    if (fileRef.current) fileRef.current.value = ""
  }

  const save = () => {
    if (!editor) return
    let meta: Record<string, any> = {}
    try {
      meta = JSON.parse(editor.metaJson || "{}")
    } catch {
      toast.error("Invalid JSON in Meta field")
      return
    }
    if (editor.item) {
      update.mutate(
        { id: editor.item.id, name: editor.name, folder: editor.folder, content: editor.content, meta },
        { onSuccess: () => setEditor(null) },
      )
    } else {
      create.mutate(
        { name: editor.name, folder: editor.folder, content: editor.content, meta },
        { onSuccess: () => setEditor(null) },
      )
    }
  }

  const askDelete = async (item: KnowledgeItem) => {
    let workspaces: KnowledgeUsage[] | undefined
    try {
      workspaces = await fetchKnowledgeUsage(item.id)
    } catch {
      workspaces = undefined
    }
    setConfirmDelete({ item, workspaces })
  }

  const handleSelect = (item: KnowledgeItem) => {
    if (isSelection && onSelect) onSelect(item)
  }

  const renderItemActions = (item: KnowledgeItem) => {
    if (isSelection) {
      return (
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          title={t("knowledge_lib.select_title")}
          onClick={() => handleSelect(item)}
        >
          <Link2 className="size-3.5" />
        </Button>
      )
    }
    return (
      <>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          title={t("knowledge_lib.read_title")}
          onClick={() => openPreview(item)}
        >
          <Eye className="size-3.5" />
        </Button>
        <Button variant="ghost" size="icon" className="size-7" title={t("knowledge_lib.edit_title_attr")} onClick={() => openEdit(item)}>
          <Pencil className="size-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-7 text-destructive hover:text-destructive"
          onClick={() => askDelete(item)}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </>
    )
  }

  if (isLoading) return <Skeleton className="h-64 w-full rounded-lg" />

  return (
    <div className={cn("space-y-5", isSelection && "max-w-2xl")}>
      {!hideHeader && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">{t("knowledge_lib.title")}</h2>
            <p className="text-xs text-muted-foreground">
              {t("knowledge_lib.description")}
            </p>
          </div>
          <Button size="sm" className="gap-1.5" onClick={openCreate}>
            <Upload className="size-4" /> {t("knowledge_lib.write_upload")}
          </Button>
        </div>
      )}

      {/* Kategori (penyusunan by kategori — pola sama dgn Grounding) */}
      <div className="flex flex-wrap gap-1">
        {FOLDERS.map((f) => {
          const count = all.filter((i) => {
            if (i.folder !== f.id) return false
            if (isSelection && excludeIds.includes(i.id)) return false
            return true
          }).length
          return (
            <button
              key={f.id}
              type="button"
              className={cn(
                "flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                category === f.id
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setCategory(f.id)}
            >
              {f.label}
              <span className={cn("text-[10px]", category === f.id ? "opacity-80" : "opacity-50")}>
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* List dokumen kategori terpilih */}
      <div className="overflow-hidden rounded-lg border">
        {all.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-10 text-center text-muted-foreground">
            <BookMarked className="size-8 opacity-40" />
            <p className="text-sm">{t(isSelection ? "knowledge_lib.empty_all_selection" : "knowledge_lib.empty_all")}</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-8 text-center text-muted-foreground">
            <BookMarked className="size-8 opacity-40" />
            <p className="text-sm">
              {t("knowledge_lib.empty_category", { label: FOLDERS.find((f) => f.id === category)?.label ?? category })}
            </p>
          </div>
        ) : (
          filtered.map((item) => (
            <div key={item.id} className="flex items-center gap-2.5 border-b px-3 py-2 last:border-b-0 hover:bg-accent/50 transition-colors">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1 cursor-pointer" onClick={() => openPreview(item)}>
                <p className="truncate font-mono text-xs font-medium">{item.name}</p>
                <p className="text-[11px] text-muted-foreground">
                  {formatBytes(item.sizeBytes)} · {new Date(item.updatedAt ?? "").toLocaleString()}
                </p>
              </div>
              <Badge variant="secondary" className="shrink-0 text-[10px]">{item.folder}</Badge>
              {(item.usageCount ?? 0) > 0 && !isSelection && (
                <Badge className="shrink-0 gap-1 text-[10px]">
                  <Link2 className="size-3" /> {item.usageCount}
                </Badge>
              )}
              {renderItemActions(item)}
            </div>
          ))
        )}
      </div>

      {/* Preview — untuk kedua mode (selection & management) */}
      <Dialog open={!!preview} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="sm:max-w-4xl overflow-y-auto max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{preview?.item.name}</DialogTitle>
            <DialogDescription>
              {t("knowledge_lib.preview_desc", { folder: preview?.item.folder })}
              {typeof preview?.item.sizeBytes === "number" &&
                ` · ${(preview.item.sizeBytes / 1024).toFixed(1)} KB`}
            </DialogDescription>
          </DialogHeader>
          {preview && !preview.content ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <Suspense fallback={<Skeleton className="h-48 w-full" />}>
              <div className="min-h-24 rounded-md border bg-muted/30 p-4">
                <MarkdownView content={preview?.content ?? ""} />
              </div>
            </Suspense>
          )}
        </DialogContent>
      </Dialog>

      {/* Editor + Delete hanya di management */}
      {mode === "management" && (
        <>
          <Dialog open={!!editor} onOpenChange={(open) => !open && setEditor(null)}>
            <DialogContent className="sm:max-w-3xl overflow-y-auto max-h-[85vh]">
              <DialogHeader>
                <DialogTitle>
                  {editor?.item
                    ? t("knowledge_lib.dialog_edit_title", { name: editor.item.name })
                    : t("knowledge_lib.dialog_create_title")}
                </DialogTitle>
                <DialogDescription>
                  {t("knowledge_lib.dialog_desc")}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="min-w-48 flex-1 space-y-1.5">
                    <Label>{t("knowledge_lib.name_label")}</Label>
                    <input
                      className="w-full rounded-md border bg-transparent px-3 py-2 text-sm"
                      placeholder="runbook-oom-killed"
                      value={editor?.name ?? ""}
                      onChange={(e) => editor && setEditor({ ...editor, name: e.target.value })}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>{t("knowledge_lib.category_label")}</Label>
                    <Select
                      value={editor?.folder ?? "general"}
                      onValueChange={(v) => editor && setEditor({ ...editor, folder: v as KnowledgeFolder })}
                    >
                      <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {FOLDERS.map((f) => (
                          <SelectItem key={f.id} value={f.id}>{f.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <input ref={fileRef} type="file" accept=".md" className="hidden"
                    onChange={(e) => onFile(e.target.files?.[0])} />
                  <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                    {t("knowledge_lib.pick_file")}
                  </Button>
                </div>
                <div className="space-y-1.5">
                  <Label>{t("knowledge_lib.meta_label", "Meta (JSON)")}</Label>
                  <Textarea
                    rows={4}
                    className="min-h-20 max-h-[30vh] resize-y font-mono text-xs leading-relaxed"
                    placeholder='{"criticality": "high", "thresholds": {"error_count_warning": 5}}'
                    value={editor?.metaJson ?? "{}"}
                    onChange={(e) => editor && setEditor({ ...editor, metaJson: e.target.value })}
                  />
                  <p className="text-[11px] text-muted-foreground">
                    {t("knowledge_lib.meta_hint", "Optional structured metadata for agent routing & RCA")}
                  </p>
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label>{t("knowledge_lib.content_label")}</Label>
                    <div className="flex rounded-md border p-0.5 text-xs">
                      {(["tulis", "preview"] as const).map((m) => (
                        <button
                          key={m}
                          type="button"
                          className={cn(
                            "rounded px-2.5 py-1 capitalize transition-colors",
                            editorMode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                          )}
                          onClick={() => setEditorMode(m)}
                        >
                          {m === "tulis" ? t("knowledge_lib.mode_write") : t("knowledge_lib.mode_preview")}
                        </button>
                      ))}
                    </div>
                  </div>
                  {editorMode === "tulis" ? (
                    <Textarea
                      rows={16}
                      className="min-h-[320px] max-h-[60vh] resize-y overflow-y-auto font-mono text-xs leading-relaxed"
                      placeholder={"# Runbook OOMKilled\n" + t("knowledge_lib.preview_empty")}
                      value={editor?.content ?? ""}
                      onChange={(e) => editor && setEditor({ ...editor, content: e.target.value })}
                    />
                  ) : (
                    <Suspense fallback={<Skeleton className="h-72 w-full" />}>
                      <div className="min-h-[320px] max-h-[60vh] overflow-y-auto rounded-md border bg-muted/30 p-4">
                        {(editor?.content ?? "").trim() ? (
                          <MarkdownView content={editor?.content ?? ""} />
                        ) : (
                          <p className="text-sm text-muted-foreground">{t("knowledge_lib.preview_empty")}</p>
                        )}
                      </div>
                    </Suspense>
                  )}
                  <p className="text-[11px] text-muted-foreground">
                    {t("knowledge_lib.chars_hint", { count: editor?.content.length ?? 0 })}
                    {editorMode === "tulis" && t("knowledge_lib.resize_hint")}
                  </p>
                </div>
              </div>
              <DialogFooter>
                <Button variant="ghost" onClick={() => setEditor(null)}>{t("knowledge_lib.cancel")}</Button>
                <Button
                  onClick={save}
                  disabled={create.isPending || update.isPending || !editor?.name || !editor?.content}
                >
                  {t("knowledge_lib.save")}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <AlertDialog open={!!confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(null)}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t("knowledge_lib.delete_title", { name: confirmDelete?.item.name ?? "" })}</AlertDialogTitle>
                <AlertDialogDescription>
                  {confirmDelete?.workspaces?.length ? (
                    <span
                      dangerouslySetInnerHTML={{
                        __html: t("knowledge_lib.delete_in_use", {
                          names: confirmDelete.workspaces.map((w) => w.name).join(", "),
                        }),
                      }}
                    />
                  ) : (
                    t("knowledge_lib.delete_plain")
                  )}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t("knowledge_lib.cancel")}</AlertDialogCancel>
                <AlertDialogAction
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  onClick={() => {
                    if (confirmDelete)
                      remove.mutate({ id: confirmDelete.item.id, confirm: !!confirmDelete.workspaces?.length })
                    setConfirmDelete(null)
                  }}
                >
                  {t("knowledge_lib.delete_confirm_btn")}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </>
      )}
    </div>
  )
}

function formatBytes(n?: number): string {
  if (!n) return "0 B"
  if (n < 1024) return `${n} B`
  return `${(n / 1024).toFixed(1)} KB`
}
