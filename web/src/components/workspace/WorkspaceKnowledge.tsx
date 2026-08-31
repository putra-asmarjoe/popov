import { lazy, Suspense, useMemo, useRef, useState, type ChangeEvent } from "react"
import { Trans, useTranslation } from "react-i18next"
import { toast } from "sonner"
import { BookOpen, FilePlus2, FileText, Eye, Network, Pencil, Trash2, Upload } from "lucide-react"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  useCreateWorkspaceKnowledge,
  useDeleteWorkspaceKnowledge,
  useUnlinkKnowledge,
  useUpdateWorkspaceKnowledge,
  useWorkspaceItems,
  useAgentDocRefs,
  useUnlinkAgentDoc,
  type WorkspaceKnowledgeItem,
} from "@/hooks/useKnowledge"
import { useWorkspaceServiceGroups } from "@/hooks/useServicesLib"
import type { AgentDocRef } from "@/types/knowledge"
import { AgentDocsPicker } from "@/components/workspace/AgentDocsPicker"
import { KnowledgeViewDialog } from "@/components/shared/KnowledgeViewDialog"

const MarkdownView = lazy(() =>
  import("@/components/shared/MarkdownView").then((m) => ({ default: m.MarkdownView })),
)

interface Props {
  wsId: string
  isAdmin: boolean
}

interface EditorState {
  item: WorkspaceKnowledgeItem | null
  name: string
  folder: string
  content: string
}

const FOLDERS = [
  { id: "general", label: "General" },
  { id: "services", label: "Services" },
  { id: "playbooks", label: "Playbooks" },
  { id: "schemas", label: "Schemas" },
  { id: "connections", label: "Connections" },
  { id: "observability", label: "Observability" },
]

/**
 * Section Knowledge (WorkspaceSettingsPage) — FE-7.
 * Member: baca + preview. Admin: CRUD knowledge spesifik workspace + link dari Management library.
 * Popov Agent memakai knowledge ini saat menganalisis via chat/tiket di workspace ini.
 *
 * UI pattern: single Dialog with inline editor (same as ServiceKnowledgeDialog).
 */
export function WorkspaceKnowledge({ wsId, isAdmin }: Props) {
  const { t } = useTranslation("workspace")
  const { data: wsData, isLoading: wsItemsLoading } = useWorkspaceItems(wsId)
  const wsItems = wsData?.workspaceItems ?? []
  const linkedRefs = wsData?.items ?? []
  const { data: groups } = useWorkspaceServiceGroups(wsId)
  const { data: agentDocRefs } = useAgentDocRefs(wsId)
  const unlinkAgentDoc = useUnlinkAgentDoc(wsId)
  const unlinkRef = useUnlinkKnowledge(wsId)
  const createWs = useCreateWorkspaceKnowledge(wsId)
  const updateWs = useUpdateWorkspaceKnowledge(wsId)
  const deleteWs = useDeleteWorkspaceKnowledge(wsId)
  const [confirmDeleteWs, setConfirmDeleteWs] = useState<WorkspaceKnowledgeItem | null>(null)
  const [confirmUnlinkRef, setConfirmUnlinkRef] = useState<{ id: string; name: string } | null>(null)
  const [confirmUnlinkAgentDoc, setConfirmUnlinkAgentDoc] = useState<AgentDocRef | null>(null)
  const [agentDocPickerOpen, setAgentDocPickerOpen] = useState(false)
  const [viewDoc, setViewDoc] = useState<{ name: string; content: string } | null>(null)

  // Single dialog state: null = closed, "list" = list view, EditorState = editor view
  const [dialogMode, setDialogMode] = useState<"list" | EditorState | null>(null)
  const [editorMode, setEditorMode] = useState<"tulis" | "preview">("tulis")
  const fileRef = useRef<HTMLInputElement>(null)

  const serviceKnowledgeCount = useMemo(() => {
    let n = 0
    for (const g of groups ?? []) for (const s of g.services) n += s.knowledge?.length ?? 0
    return n
  }, [groups])

  const isLoading = wsItemsLoading
  const hasItems = wsItems.length > 0 || linkedRefs.length > 0
  const isEditor = dialogMode !== null && dialogMode !== "list"
  const editor = isEditor ? dialogMode : null

  const openList = () => setDialogMode("list")

  const openViewWs = async (itemId: string, name: string) => {
    setViewDoc({ name, content: "" })
    try {
      const { data } = await api.get(`/knowledge/workspaces/${wsId}/items/${itemId}`)
      setViewDoc({ name, content: data.content ?? "" })
    } catch {
      setViewDoc({ name, content: "" })
    }
  }

  const openViewRef = async (knowledgeLibraryId: string, name: string) => {
    setViewDoc({ name, content: "" })
    try {
      const { data } = await api.get(`/knowledge/library/${knowledgeLibraryId}`)
      setViewDoc({ name, content: data.content ?? "" })
    } catch {
      setViewDoc({ name, content: "" })
    }
  }

  const openCreate = () => {
    setEditorMode("tulis")
    setDialogMode({ item: null, name: "", folder: "general", content: "" })
  }

  const MAX_FILE_SIZE = 250 * 1024

  const handleFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (f.size > MAX_FILE_SIZE) {
      toast.error(t("knowledge.file_too_large", { max: "250KB" }))
      if (fileRef.current) fileRef.current.value = ""
      return
    }
    setEditorMode("tulis")
    setDialogMode({
      item: null,
      name: f.name.replace(/\.(md|txt)$/i, ""),
      folder: "general",
      content: await f.text(),
    })
    if (fileRef.current) fileRef.current.value = ""
  }

  const openEdit = async (item: WorkspaceKnowledgeItem) => {
    setEditorMode("tulis")
    setDialogMode({ item, name: item.name, folder: item.folder, content: "" })
    try {
      const { data } = await api.get(`/knowledge/workspaces/${wsId}/items/${item.id}`)
      setDialogMode({ item, name: data.name ?? item.name, folder: data.folder ?? item.folder, content: data.content ?? "" })
    } catch {
      setDialogMode({ item, name: item.name, folder: item.folder, content: "" })
    }
  }

  const saveEditor = () => {
    if (!editor) return
    if (editor.item) {
      updateWs.mutate(
        { id: editor.item.id, name: editor.name, folder: editor.folder, content: editor.content },
        { onSuccess: () => setDialogMode("list") },
      )
    } else {
      createWs.mutate(
        { name: editor.name, folder: editor.folder, content: editor.content },
        { onSuccess: () => setDialogMode("list") },
      )
    }
  }

  const updateEditor = (patch: Partial<EditorState>) => {
    if (editor) setDialogMode({ ...editor, ...patch })
  }

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
          <Button size="sm" variant="outline" className="gap-1.5" onClick={openList}>
            <BookOpen className="size-4" /> {t("knowledge.manage")}
          </Button>
        )}
      </div>

      {/* Workspace-specific knowledge (read-only list on page) */}
      {(wsItems ?? []).length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-medium text-muted-foreground">{t("knowledge.workspace_specific")}</p>
          <div className="overflow-hidden rounded-lg border">
            {(wsItems ?? []).map((item) => (
              <div key={item.id} className="flex items-center gap-2.5 border-b px-3 py-2 last:border-b-0">
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-xs font-medium">{item.name}</p>
                  <p className="text-[11px] text-muted-foreground">{item.folder}</p>
                </div>
                <Badge variant="secondary" className="shrink-0 text-[10px]">{item.folder}</Badge>
                <Button variant="ghost" size="icon" className="size-6" title={t("btn_view", { ns: "services" })}
                  onClick={() => openViewWs(item.id, item.name)}>
                  <Eye className="size-3" />
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Linked from Management library (read-only list on page) */}
      {linkedRefs.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-medium text-muted-foreground">{t("knowledge.linked_from_library")}</p>
          <div className="overflow-hidden rounded-lg border">
            {linkedRefs.map((ref) => (
              <div key={ref.id} className="flex items-center gap-2.5 border-b px-3 py-2 last:border-b-0">
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-xs font-medium">{ref.name}</p>
                  <p className="text-[11px] text-muted-foreground">{ref.folder}</p>
                </div>
                <Badge variant="secondary" className="shrink-0 text-[10px]">{ref.folder}</Badge>
                <Badge variant="outline" className="shrink-0 text-[9px] px-1">library</Badge>
                <Button variant="ghost" size="icon" className="size-6" title={t("btn_view", { ns: "services" })}
                  onClick={() => openViewRef(ref.libraryId, ref.name)}>
                  <Eye className="size-3" />
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {!isLoading && !hasItems && (
        <div className="flex flex-col items-center gap-2 p-10 text-center text-muted-foreground">
          <FileText className="size-8 opacity-40" />
          <p className="text-sm">{t("knowledge.empty")}</p>
          {isAdmin && (
            <p className="text-xs">{t("knowledge.admin_empty_hint")}</p>
          )}
          {serviceKnowledgeCount > 0 && (
            <p className="text-xs max-w-md">
              <Trans
                i18nKey="knowledge.service_hint"
                ns="workspace"
                values={{ count: serviceKnowledgeCount }}
                components={{ 1: <b /> }}
              />
            </p>
          )}
        </div>
      )}

      {/* Grounding Documents (Agent Docs) — read-only reference */}
      <div className="mt-6">
        <div className="mb-2 flex items-center justify-between">
          <div>
            <p className="text-xs font-medium text-muted-foreground">{t("knowledge_lib.grounding_section_title", { ns: "management" })}</p>
            <p className="text-[11px] text-muted-foreground">{t("knowledge_lib.grounding_readonly", { ns: "management" })}</p>
          </div>
          {isAdmin && (
            <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setAgentDocPickerOpen(true)}>
              <Network className="size-4" /> {t("knowledge_lib.grounding_connect", { ns: "management" })}
            </Button>
          )}
        </div>
        <div className="overflow-hidden rounded-lg border">
          {(agentDocRefs ?? []).length === 0 ? (
            <div className="flex flex-col items-center gap-2 p-8 text-center text-muted-foreground">
              <FileText className="size-6 opacity-40" />
              <p className="text-xs">{t("knowledge_lib.grounding_empty", { ns: "management" })}</p>
            </div>
          ) : (
            (agentDocRefs ?? []).map((ref) => (
              <div key={ref.id} className="flex items-center gap-2.5 border-b px-3 py-2 last:border-b-0">
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-xs font-medium">{ref.docKey}</p>
                  <p className="text-[11px] text-muted-foreground">{ref.docCategory}</p>
                </div>
                <Badge variant="secondary" className="shrink-0 text-[10px]">{ref.docCategory}</Badge>
                {isAdmin && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 text-destructive hover:text-destructive"
                    onClick={() => setConfirmUnlinkAgentDoc(ref)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Agent Docs Picker */}
      <AgentDocsPicker
        wsId={wsId}
        open={agentDocPickerOpen}
        onOpenChange={setAgentDocPickerOpen}
      />

      {/* ── Single Dialog: Choice screen + Inline Editor + Items list ── */}
      <Dialog open={dialogMode !== null} onOpenChange={(open) => !open && setDialogMode(null)}>
        <DialogContent className="sm:max-w-3xl overflow-y-auto max-h-[88vh]">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">
              {isEditor
                ? (editor?.item ? `Edit: ${editor.item.name}` : t("knowledge.add_new"))
                : `${t("knowledge.title")} — manage`}
            </DialogTitle>
            <DialogDescription>
              {isEditor
                ? t("knowledge.description")
                : t("knowledge.manage_description")}
            </DialogDescription>
          </DialogHeader>

          {/* ── Choice screen: Tulis / Upload (always show when not editing) ── */}
          {!isEditor && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">{t("knowledge.choose_method")}</p>
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" className="h-16 gap-2" onClick={openCreate}>
                  <FilePlus2 className="size-5" />
                  <div className="text-left">
                    <p className="text-sm font-medium">{t("knowledge.write_new")}</p>
                    <p className="text-[11px] text-muted-foreground">{t("knowledge.write_desc")}</p>
                  </div>
                </Button>
                <Button variant="outline" className="h-16 gap-2" onClick={() => fileRef.current?.click()}>
                  <Upload className="size-5" />
                  <div className="text-left">
                    <p className="text-sm font-medium">{t("knowledge.upload")}</p>
                    <p className="text-[11px] text-muted-foreground">{t("knowledge.upload_hint")}</p>
                  </div>
                </Button>
              </div>
              <input
                ref={fileRef}
                type="file"
                accept=".md,.txt"
                className="hidden"
                onChange={handleFileUpload}
              />
            </div>
          )}

          {/* ── Editor tulis/edit ── */}
          {isEditor && (editor?.item || editor?.content) && (
            <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold">
                  {editor?.item
                    ? <>Edit <span className="font-mono">{editor.name}</span></>
                    : <>{t("knowledge.new_knowledge")} <span className="font-mono">{wsId}</span></>
                  }
                </p>
                <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setDialogMode("list")}>
                  {t("knowledge.cancel")}
                </Button>
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-36 flex-1 space-y-1">
                  <Label className="text-xs">{t("knowledge.name_label")}</Label>
                  <Input
                    className="h-8 font-mono text-xs"
                    placeholder="runbook-oom-killed"
                    value={editor?.name ?? ""}
                    onChange={(e) => updateEditor({ name: e.target.value })}
                  />
                </div>
                <Select value={editor?.folder ?? "general"} onValueChange={(v) => updateEditor({ folder: v })}>
                  <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {FOLDERS.map((f) => (
                      <SelectItem key={f.id} value={f.id}>{f.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex w-fit rounded-md border p-0.5 text-xs">
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
                    {m === "tulis" ? "✍️ Tulis" : "👁 Preview"}
                  </button>
                ))}
              </div>
              {editorMode === "tulis" ? (
                <Textarea
                  rows={10}
                  className="min-h-[220px] max-h-[45vh] resize-y overflow-y-auto font-mono text-xs leading-relaxed"
                  placeholder={t("knowledge.placeholder_runbook")}
                  value={editor?.content ?? ""}
                  onChange={(e) => updateEditor({ content: e.target.value })}
                />
              ) : (
                <Suspense fallback={<Skeleton className="h-48 w-full" />}>
                  <div className="min-h-[220px] max-h-[45vh] overflow-y-auto rounded-md border bg-background p-3">
                    {(editor?.content ?? "").trim()
                      ? <MarkdownView content={editor?.content ?? ""} />
                      : <p className="text-sm text-muted-foreground">{t("knowledge.preview_empty")}</p>}
                  </div>
                </Suspense>
              )}
              {!editor?.item && (editor?.content ?? "").length > 0 && (editor?.content ?? "").length < 50 && (
                <p className="text-[11px] text-amber-600">
                  {t("knowledge.content_min_chars", { current: (editor?.content ?? "").length, min: 50 })}
                </p>
              )}
              <Button
                size="sm"
                className="w-full"
                disabled={createWs.isPending || updateWs.isPending || !editor?.name || !editor?.content}
                onClick={saveEditor}
              >
                {createWs.isPending || updateWs.isPending
                  ? t("knowledge.saving")
                  : editor?.item
                    ? t("knowledge.save_changes")
                    : t("knowledge.save_and_link")}
              </Button>
              {(!editor?.name || !editor?.content) && (
                <p className="text-center text-[11px] text-muted-foreground">
                  {t("knowledge.fill_name_content")}
                </p>
              )}
            </div>
          )}

          {/* ── Items list (always visible below editor or choice screen) ── */}
          {!isEditor && (
            <div className="space-y-3">
              {/* Workspace-specific */}
              {(wsItems ?? []).length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">{t("knowledge.workspace_specific")}</p>
                  <div className="overflow-hidden rounded-lg border">
                    {(wsItems ?? []).map((item) => (
                      <div key={item.id} className="flex items-center gap-2.5 border-b px-3 py-1.5 last:border-b-0">
                        <FileText className="size-4 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate font-mono text-xs">{item.name}</span>
                        <Badge variant="secondary" className="shrink-0 text-[10px]">{item.folder}</Badge>
                        {isAdmin && (
                          <>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              title={t("btn_view", { ns: "services" })}
                              onClick={() => openViewWs(item.id, item.name)}
                            >
                              <Eye className="size-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              title={t("btn_edit", { ns: "services" })}
                              onClick={() => openEdit(item)}
                            >
                              <Pencil className="size-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7 text-destructive hover:text-destructive"
                              title="Delete"
                              onClick={() => { setDialogMode(null); setConfirmDeleteWs(item) }}
                            >
                              <Trash2 className="size-3.5" />
                            </Button>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Linked from Management library */}
              {linkedRefs.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">{t("knowledge.linked_from_library")}</p>
                  <div className="overflow-hidden rounded-lg border">
                    {linkedRefs.map((ref) => (
                      <div key={ref.id} className="flex items-center gap-2.5 border-b px-3 py-1.5 last:border-b-0">
                        <FileText className="size-4 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate font-mono text-xs">{ref.name}</span>
                        <Badge variant="secondary" className="shrink-0 text-[10px]">{ref.folder}</Badge>
                        <Badge variant="outline" className="shrink-0 text-[9px] px-1">library</Badge>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          title={t("btn_view", { ns: "services" })}
                          onClick={() => openViewRef(ref.libraryId, ref.name)}
                        >
                          <Eye className="size-3.5" />
                        </Button>
                        {isAdmin && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7 text-destructive hover:text-destructive"
                            title={t("btn_unlink", { ns: "services" })}
                            onClick={() => { setDialogMode(null); setConfirmUnlinkRef({ id: ref.id, name: ref.name }) }}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {(wsItems ?? []).length === 0 && linkedRefs.length === 0 && (
                <p className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
                  {t("knowledge.empty")}
                </p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Hapus workspace knowledge */}
      <AlertDialog open={!!confirmDeleteWs} onOpenChange={(open) => !open && setConfirmDeleteWs(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("knowledge.delete_title", { name: confirmDeleteWs?.name ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("knowledge.delete_description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmDeleteWs) deleteWs.mutate(confirmDeleteWs.id)
                setConfirmDeleteWs(null)
              }}
            >
              {t("knowledge.delete_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Lepas link dari Management library */}
      <AlertDialog open={!!confirmUnlinkRef} onOpenChange={(open) => !open && setConfirmUnlinkRef(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("knowledge.unlink_title", { name: confirmUnlinkRef?.name ?? "" })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("knowledge.unlink_description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmUnlinkRef) unlinkRef.mutate(confirmUnlinkRef.id)
                setConfirmUnlinkRef(null)
              }}
            >
              {t("knowledge.unlink_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Lepas koneksi grounding doc */}
      <AlertDialog open={!!confirmUnlinkAgentDoc} onOpenChange={(open) => !open && setConfirmUnlinkAgentDoc(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Disconnect: {confirmUnlinkAgentDoc?.docKey ?? ""}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("knowledge.unlink_description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmUnlinkAgentDoc) unlinkAgentDoc.mutate(confirmUnlinkAgentDoc.id)
                setConfirmUnlinkAgentDoc(null)
              }}
            >
              {t("knowledge.unlink_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* View markdown */}
      <KnowledgeViewDialog doc={viewDoc} onClose={() => setViewDoc(null)} />
    </div>
  )
}
