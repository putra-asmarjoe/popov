import { lazy, Suspense, useState } from "react"
import { useTranslation } from "react-i18next"
import i18n from "@/lib/i18n"
import { toast } from "sonner"
import { FileText, ScrollText, Trash2 } from "lucide-react"
import { api, apiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { DOC_CATEGORIES, useAgentDocMutations, useAgentDocs } from "@/hooks/useAgentDocs"
import type { AgentDoc, AgentDocMeta } from "@/hooks/useAgentDocs"

const MarkdownView = lazy(() => import("@/components/shared/MarkdownView"))

interface EditorState {
  mode: "create" | "edit"
  category: string
  key: string
  collection: string
  metaJson: string
  body: string
}

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  DOC_CATEGORIES.map((c) => [c.id, c.label]),
)

/**
 * Tab Docs (/management) — kelola grounding docs agent (agent_docs, DB).
 * Services/playbooks/schemas/connections/observability — sumber RAG agent.
 * Editor meta JSON (YAML frontmatter dulu) + body markdown + preview.
 */
export function AgentDocsManager() {
  const { t } = useTranslation("management")
  const [category, setCategory] = useState("general")
  const { data: docs, isLoading } = useAgentDocs(category)
  const { create, update, remove } = useAgentDocMutations()

  const [editor, setEditor] = useState<EditorState | null>(null)
  const [editorMode, setEditorMode] = useState<"tulis" | "preview">("tulis")
  const [preview, setPreview] = useState<{ key: string; body: string } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<{ category: string; key: string } | null>(null)

  const openCreate = () => {
    setEditorMode("tulis")
    setEditor({ mode: "create", category, key: "", collection: "", metaJson: "{}", body: "" })
  }

  const openEdit = async (doc: AgentDoc) => {
    try {
      const { data } = await api.get(`/docs/agent-docs/${doc.category}/${doc.key}`)
      const meta = (data.meta ?? {}) as AgentDocMeta
      setEditorMode("tulis")
      setEditor({
        mode: "edit",
        category: doc.category,
        key: doc.key,
        collection: (meta.collections as { primary?: string } | undefined)?.primary ?? "",
        metaJson: JSON.stringify(meta, null, 2),
        body: data.body ?? "",
      })
    } catch (e) {
      toast.error(apiErrorMessage(e, t("agent_docs.load_failed")))
    }
  }

  const openPreview = (doc: AgentDoc) => {
    setPreview({ key: doc.key, body: "" })
    void api
      .get(`/docs/agent-docs/${doc.category}/${doc.key}`)
      .then(({ data }) => setPreview({ key: doc.key, body: data.body ?? "" }))
      .catch((e) => {
        setPreview(null)
        toast.error(apiErrorMessage(e, t("agent_docs.load_failed")))
      })
  }

  const metaBadge = (doc: AgentDoc): string => {
    if (doc.category === "general") return t("agent_docs.general_badge")
    if (doc.category === "services") {
      return String((doc.meta.collections as { primary?: string } | undefined)?.primary ?? "")
    }
    if (doc.category === "playbooks") {
      const applies = (doc.meta.applies_to_services as unknown[]) ?? []
      return applies.length ? applies.join(", ") : "universal"
    }
    if (doc.category === "schemas") {
      return String(doc.meta.collection ?? "")
    }
    return String(doc.meta.service_id ?? doc.meta.id ?? "")
  }

  const save = () => {
    if (!editor) return
    let meta: Record<string, unknown>
    try {
      meta = JSON.parse(editor.metaJson || "{}")
    } catch {
      toast.error(t("agent_docs.meta_invalid_json"))
      return
    }
    if (editor.collection.trim()) {
      meta.collections = { ...((meta.collections as object) ?? {}), primary: editor.collection.trim() }
    }
    const input = { category: editor.category, key: editor.key, meta, body: editor.body }
    const onDone = () => setEditor(null)
    if (editor.mode === "create") {
      if (!editor.key.trim()) {
        toast.error(t("agent_docs.key_required"))
        return
      }
      create.mutate(input, { onSuccess: onDone })
    } else {
      update.mutate(input, { onSuccess: onDone })
    }
  }

  if (isLoading) return <Skeleton className="h-64 w-full rounded-lg" />

  return (
    <div className="max-w-4xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{t("agent_docs.title")}</h2>
          <p
            className="text-xs text-muted-foreground"
            dangerouslySetInnerHTML={{ __html: t("agent_docs.description") }}
          />
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" className="gap-1.5" onClick={openCreate}>
            <FileText className="size-4" /> {t("agent_docs.create_document")}
          </Button>
        </div>
      </div>

      {/* Kategori */}
      <div className="flex flex-wrap gap-1">
        {DOC_CATEGORIES.map((c) => (
          <button
            key={c.id}
            type="button"
            className={cn(
              "cursor-pointer rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              category === c.id
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setCategory(c.id)}
          >
            {t(c.label)}
          </button>
        ))}
      </div>

      {/* List dokumen kategori */}
      <div className="overflow-hidden rounded-lg border">
        {(docs ?? []).length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-10 text-center text-muted-foreground">
            <ScrollText className="size-8 opacity-40" />
            <p className="text-sm">{t("agent_docs.empty_category", { category: t(CATEGORY_LABEL[category] ?? category) })}</p>
          </div>
        ) : (
          (docs ?? []).map((doc) => (
            <div key={`${doc.category}:${doc.key}`} className="flex items-center gap-2.5 border-b px-3 py-2 last:border-b-0">
              <ScrollText className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-xs font-medium">{doc.key}</p>
                <p className="text-[11px] text-muted-foreground">
                  {formatBytes(doc.body_len)} ·{" "}
                  {new Date(doc.updatedAt ?? "").toLocaleString(i18n.language === "en" ? "en-US" : "id-ID")}
                </p>
              </div>
              {metaBadge(doc) && (
                <Badge variant="secondary" className="shrink-0 max-w-52 truncate text-[10px]">
                  {metaBadge(doc)}
                </Badge>
              )}
              <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => openPreview(doc)}>
                {t("agent_docs.read")}
              </Button>
              <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => openEdit(doc)}>
                {t("agent_docs.edit")}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 text-destructive hover:text-destructive"
                onClick={() => setConfirmDelete({ category: doc.category, key: doc.key })}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))
        )}
      </div>

      {/* Editor */}
      <Dialog open={!!editor} onOpenChange={(open) => !open && setEditor(null)}>
        <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {editor?.mode === "create" ? t("agent_docs.create_title") : t("agent_docs.edit_title", { key: editor?.key ?? "" })}
            </DialogTitle>
            <DialogDescription>
              {t("agent_docs.dialog_description_services")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-48 flex-1 space-y-1.5">
                <Label>{t("agent_docs.key_label")}</Label>
                <input
                  className="w-full rounded-md border bg-transparent px-3 py-2 font-mono text-sm disabled:opacity-60"
                  placeholder={t("agent_docs.key_placeholder")}
                  value={editor?.key ?? ""}
                  disabled={editor?.mode === "edit"}
                  onChange={(e) => editor && setEditor({ ...editor, key: e.target.value })}
                />
              </div>
              {editor?.category === "services" && (
                <div className="min-w-48 flex-1 space-y-1.5">
                  <Label>{t("agent_docs.collection_label")}</Label>
                  <input
                    className="w-full rounded-md border bg-transparent px-3 py-2 font-mono text-sm"
                    placeholder="logs_<service>"
                    value={editor?.collection ?? ""}
                    onChange={(e) => editor && setEditor({ ...editor, collection: e.target.value })}
                  />
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <Label>{t("agent_docs.meta_label")}</Label>
              <Textarea
                rows={5}
                className="min-h-24 resize-y font-mono text-xs leading-relaxed"
                placeholder={t('agent_docs.meta_placeholder')}
                value={editor?.metaJson ?? ""}
                onChange={(e) => editor && setEditor({ ...editor, metaJson: e.target.value })}
              />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label>{t("agent_docs.body_label")}</Label>
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
                      {m === "tulis" ? t("agent_docs.mode_write") : t("agent_docs.mode_preview")}
                    </button>
                  ))}
                </div>
              </div>
              {editorMode === "tulis" ? (
                <Textarea
                  rows={12}
                  className="min-h-64 max-h-[50vh] resize-y overflow-y-auto font-mono text-xs leading-relaxed"
                  placeholder={t("agent_docs.body_placeholder")}
                  value={editor?.body ?? ""}
                  onChange={(e) => editor && setEditor({ ...editor, body: e.target.value })}
                />
              ) : (
                <Suspense fallback={<Skeleton className="h-64 w-full" />}>
                  <div className="min-h-64 max-h-[50vh] overflow-y-auto rounded-md border bg-muted/30 p-4">
                    {(editor?.body ?? "").trim() ? (
                      <MarkdownView content={editor?.body ?? ""} />
                    ) : (
                      <p className="text-sm text-muted-foreground">{t("agent_docs.preview_empty")}</p>
                    )}
                  </div>
                </Suspense>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditor(null)}>{t("apikeys.cancel", { ns: "management" })}</Button>
            <Button
              onClick={save}
              disabled={create.isPending || update.isPending || !editor?.key}
            >
              {t("agent_docs.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Preview */}
      <Dialog open={!!preview} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{preview?.key}</DialogTitle>
          </DialogHeader>
          {preview && !preview.body ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <Suspense fallback={<Skeleton className="h-48 w-full" />}>
              <div className="min-h-24 rounded-md border bg-muted/30 p-4">
                <MarkdownView content={preview?.body ?? ""} />
              </div>
            </Suspense>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete confirm */}
      <AlertDialog open={!!confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("agent_docs.delete_confirm_title", { key: confirmDelete?.key ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>{t("agent_docs.delete_confirm_desc")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("apikeys.cancel", { ns: "management" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmDelete) remove.mutate(confirmDelete)
                setConfirmDelete(null)
              }}
            >
              {t("agent_docs.confirm_delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function formatBytes(n?: number): string {
  if (!n) return "0 B"
  if (n < 1024) return `${n} B`
  return `${(n / 1024).toFixed(1)} KB`
}