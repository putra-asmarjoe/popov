import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react"
import { toast } from "sonner"
import { ChevronDown, ChevronRight, Copy, Eye, FilePlus2, FileText, Pencil, Terminal, Trash2, Upload } from "lucide-react"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"
import { SCANNING_GUIDE } from "@/constants/scanning-guide"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useCreateKnowledge, useMyLibrary } from "@/hooks/useKnowledge"
import { useProjects } from "@/hooks/useWorkspaces"
import {
  useLinkServiceKnowledge,
  useServiceKnowledge,
  useUnlinkServiceKnowledge,
} from "@/hooks/useServicesLib"
import type { KnowledgeFolder } from "@/types/knowledge"
import { KnowledgeViewDialog } from "@/components/shared/KnowledgeViewDialog"

const MarkdownView = lazy(() =>
  import("@/components/shared/MarkdownView").then((m) => ({ default: m.MarkdownView })),
)

interface EditorState {
  id: string | null // null = create baru (auto-link)
  name: string
  folder: KnowledgeFolder
  content: string
  metaJson: string
}

/**
 * ServiceKnowledgeDialog — FE-8.1 (shared): kelola knowledge milik satu service.
 * Dipakai di Management (ServiceLibrary) dan Workspace Settings.
 *
 * ATURAN (ketat): pemanggil WAJIB sudah memastikan user = owner service
 * (endpoint /services/library/{id}/knowledge owner-only).
 * - Tulis knowledge baru → masuk library pribadi + OTOMATIS ter-link.
 * - View selalu bisa utk semua dokumen ter-link; Edit/Hapus hanya milik sendiri
 *   (backend 404 bila bukan owner — UI sembunyikan berdasar ownerId).
 */
export function ServiceKnowledgeDialog({
  serviceId,
  serviceLabel,
  meId,
  isAdmin = false,
  onClose,
  autoOpenCreate = false,
  initialEditId,
  initialEditName,
  initialEditFolder,
  workspaceId,
}: {
  serviceId: string
  serviceLabel?: string
  meId: string
  isAdmin?: boolean
  onClose: () => void
  autoOpenCreate?: boolean
  initialEditId?: string
  initialEditName?: string
  initialEditFolder?: string
  workspaceId?: string
}) {
  const { t } = useTranslation("services")
  
  const KNOWLEDGE_FOLDERS: { id: KnowledgeFolder; label: string }[] = [
    { id: "general", label: t("folders.general") },
    { id: "services", label: t("folders.services") },
    { id: "playbooks", label: t("folders.playbooks") },
    { id: "schemas", label: t("folders.schemas") },
    { id: "connections", label: t("folders.connections") },
    { id: "observability", label: t("folders.observability") },
  ]

  const { data: links, isLoading } = useServiceKnowledge(serviceId)
  const { data: myKnowledge } = useMyLibrary()
  const link = useLinkServiceKnowledge(serviceId)
  const unlink = useUnlinkServiceKnowledge(serviceId)
  const createKb = useCreateKnowledge()

  const [showEditor, setShowEditor] = useState(autoOpenCreate)
  const [mode, setMode] = useState<"tulis" | "preview">("tulis")
  const [kName, setKName] = useState("")
  const [kFolder, setKFolder] = useState<KnowledgeFolder>("playbooks")
  const [kContent, setKContent] = useState("")
  const [kMetaJson, setKMetaJson] = useState("{}")
  const [editing, setEditing] = useState<EditorState | null>(null)
  const [viewDoc, setViewDoc] = useState<{ name: string; folder?: string; content: string; meta?: Record<string, any> } | null>(null)
  const [activeKnowledgeId, setActiveKnowledgeId] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // API guide state
  const [showApiGuide, setShowApiGuide] = useState(false)
  const [guideExpanded, setGuideExpanded] = useState(false)
  const hostInput = typeof window !== "undefined" ? window.location.origin : "http://localhost:8000"

  // Project selection (only when workspaceId provided)
  const { data: allProjects } = useProjects(workspaceId ?? null)
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set())
  const prevProjectsRef = useRef<string[]>([])
  useEffect(() => {
    if (allProjects && prevProjectsRef.current.length === 0 && allProjects.length > 0) {
      setSelectedProjectIds(new Set(allProjects.map((p) => p.id)))
    }
    prevProjectsRef.current = allProjects?.map((p) => p.id) ?? []
  }, [allProjects])

  const copyToClipboard = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t("api_guide_copied"))
    } catch {
      toast.error(`Failed to copy ${label}`)
    }
  }

  const envBlock = `POPOV_HOST=${hostInput}
POPOV_TOKEN=# ← get token from Management → API Tokens
POPOV_WORKSPACE_ID=${workspaceId ?? "<workspace-id>"}
SERVICE_ID=${serviceLabel ?? "<service-id>"}`

  useEffect(() => {
    if (initialEditId) {
      openEdit(initialEditId, initialEditName ?? "", initialEditFolder ?? "general")
    }
  }, [initialEditId])

  const resetEditor = () => {
    setShowEditor(false)
    setEditing(null)
    setKName("")
    setKContent("")
    setKMetaJson("{}")
    setMode("tulis")
  }

  const MAX_FILE_SIZE = 250 * 1024 // 250KB

  const handleFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (f.size > MAX_FILE_SIZE) {
      toast.error(t("file_too_large", { max: "250KB" }))
      if (fileRef.current) fileRef.current.value = ""
      return
    }
    setKName(f.name.replace(/\.(md|txt)$/i, ""))
    setKContent(await f.text())
    setShowEditor(true)
    setMode("tulis")
    if (fileRef.current) fileRef.current.value = ""
  }

  const saveNew = () => {
    if (!kName.trim() || !kContent.trim()) return
    let meta: Record<string, any> = {}
    try {
      meta = JSON.parse(kMetaJson || "{}")
    } catch {
      toast.error("Invalid JSON in Meta field")
      return
    }
    createKb.mutate(
      { name: kName, folder: kFolder, content: kContent, meta },
      {
        onSuccess: (created) => {
          link.mutate(created.id, {
            onSuccess: () => {
              // Link service to selected projects (if workspaceId provided and projects selected)
              const projectIds = Array.from(selectedProjectIds)
              if (workspaceId && projectIds.length > 0) {
                api.post(`/services/${serviceId}/link-projects`, { project_ids: projectIds })
                  .then(() => {
                    toast.success(`"${created.name}" ${t("saved_and_linked", { service: serviceLabel ?? "service" })}`)
                  })
                  .catch(() => {
                    toast.success(`"${created.name}" ${t("saved_and_linked", { service: serviceLabel ?? "service" })}`)
                  })
              } else {
                toast.success(`"${created.name}" ${t("saved_and_linked", { service: serviceLabel ?? "service" })}`)
              }
              resetEditor()
            },
            onError: () =>
              toast.info(t("saved_in_library_relink")),
          })
        },
      },
    )
  }

  const saveEdit = () => {
    if (!editing?.id || !kName.trim() || !kContent.trim()) return
    let meta: Record<string, any> = {}
    try {
      meta = JSON.parse(kMetaJson || "{}")
    } catch {
      toast.error("Invalid JSON in Meta field")
      return
    }
    api
      .patch(`/knowledge/library/${editing.id}`, {
        name: kName,
        folder: kFolder,
        content: kContent,
        meta,
      })
      .then(() => {
        toast.success(t("doc_updated_all_users"))
        resetEditor()
      })
      .catch((e) => toast.error(apiErrorMessage(e, t("update_failed"))))
  }

  const openView = async (knowledgeLibraryId: string, name: string) => {
    try {
      setViewDoc({ name, content: "" })
      setActiveKnowledgeId(knowledgeLibraryId)
      const { data } = await api.get(`/knowledge/library/${knowledgeLibraryId}`)
      setViewDoc({ name, folder: data.folder, content: data.content ?? "", meta: data.meta })
    } catch (e) {
      setViewDoc(null)
      setActiveKnowledgeId(null)
      toast.error(apiErrorMessage(e, "Dokumen bukan milikmu / tidak ditemukan"))
    }
  }

  const navigateKnowledge = async (knowledgeLibraryId: string) => {
    const item = (links ?? []).find((l) => l.knowledgeLibraryId === knowledgeLibraryId)
    if (!item) return
    await openView(knowledgeLibraryId, item.name)
  }

  const openEdit = async (knowledgeLibraryId: string, fallbackName: string, fallbackFolder: string) => {
    try {
      const { data } = await api.get(`/knowledge/library/${knowledgeLibraryId}`)
      setShowEditor(true)
      setEditing({ id: knowledgeLibraryId, name: data.name ?? fallbackName, folder: data.folder ?? fallbackFolder, content: data.content ?? "", metaJson: JSON.stringify(data.meta ?? {}, null, 2) })
      setKName(data.name ?? fallbackName)
      setKFolder((data.folder ?? fallbackFolder) as KnowledgeFolder)
      setKContent(data.content ?? "")
      setKMetaJson(JSON.stringify(data.meta ?? {}, null, 2))
      setMode("tulis")
    } catch (e) {
      toast.error(apiErrorMessage(e, t("only_owner_can_edit")))
    }
  }

  const linkable = useMemo(() => {
    const linked = new Set((links ?? []).map((l) => l.knowledgeLibraryId))
    return (myKnowledge ?? []).filter((k) => !linked.has(k.id))
  }, [links, myKnowledge])

  const isEditingExisting = editing !== null

  return (
    <>
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="sm:max-w-3xl overflow-y-auto max-h-[88vh]">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{serviceLabel ?? serviceId} — Knowledge</DialogTitle>
            <DialogDescription>
              {t("dialog_description")}
            </DialogDescription>
          </DialogHeader>

          {/* ── Choice screen: API / Upload / Tulis ── */}
          {!showEditor && !isEditingExisting && !showApiGuide && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">{t("choose_method")}</p>
              <div className="grid grid-cols-3 gap-2">
                <Button variant="outline" className="h-16 gap-2" onClick={() => setShowApiGuide(true)}>
                  <Terminal className="size-5" />
                  <div className="text-left">
                    <p className="text-sm font-medium">{t("api_knowledge")}</p>
                    <p className="text-[11px] text-muted-foreground">{t("api_guide_desc")}</p>
                  </div>
                </Button>
                <Button variant="outline" className="h-16 gap-2" onClick={() => fileRef.current?.click()}>
                  <Upload className="size-5" />
                  <div className="text-left">
                    <p className="text-sm font-medium">{t("upload_knowledge")}</p>
                    <p className="text-[11px] text-muted-foreground">{t("upload_hint")}</p>
                  </div>
                </Button>
                <Button variant="outline" className="h-16 gap-2" onClick={() => setShowEditor(true)}>
                  <FilePlus2 className="size-5" />
                  <p className="text-sm font-medium">{t("write_new_knowledge")}</p>
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

          {/* ── API Guide Panel ── */}
          {showApiGuide && !showEditor && !isEditingExisting && (
            <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold">{t("api_guide_title")}</p>
                <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setShowApiGuide(false)}>
                  {t("api_guide_back")}
                </Button>
              </div>

              {/* Steps */}
              <ol className="list-inside list-decimal space-y-1 text-xs text-muted-foreground">
                <li>{t("api_guide_step1")}</li>
                <li>{t("api_guide_step2")}</li>
                <li>{t("api_guide_step3")}</li>
                <li>{t("api_guide_step4")}</li>
              </ol>

              {/* Collapsible guide */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    className="flex items-center gap-1.5 text-xs font-medium text-foreground hover:underline"
                    onClick={() => setGuideExpanded(!guideExpanded)}
                  >
                    {guideExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                    {t("api_guide_view_guide")}
                  </button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 px-2.5 text-[0.8rem]"
                    onClick={() => copyToClipboard(SCANNING_GUIDE, "guide")}
                  >
                    <Copy className="size-3.5" />
                    {t("api_guide_copy_guide")}
                  </Button>
                </div>
                {guideExpanded && (
                  <div className="max-h-[40vh] overflow-y-auto rounded-md border bg-background p-3">
                    <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted-foreground">
                      {SCANNING_GUIDE}
                    </pre>
                  </div>
                )}
              </div>

              {/* Credentials block */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">{t("api_guide_credentials")}</Label>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 px-2.5 text-[0.8rem]"
                    onClick={() => copyToClipboard(envBlock, "env")}
                  >
                    <Copy className="size-3.5" />
                    {t("api_guide_copy_env")}
                  </Button>
                </div>
                <div className="rounded-md border bg-background p-3 font-mono text-xs">
                  <pre className="whitespace-pre-wrap break-all">{envBlock}</pre>
                </div>
                <div className="flex items-center gap-1.5 text-[11px] text-amber-600">
                  <span>{t("api_guide_no_token")}</span>
                  <a
                    href="/management?tab=apitokens"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline underline-offset-2 hover:text-amber-700"
                  >
                    {t("api_guide_no_token_link")}
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* ── Editor tulis/edit ── */}
          {(showEditor || isEditingExisting) && (
            <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold">
                  {isEditingExisting ? (
                    <>Edit <span className="font-mono">{editing?.name}</span></>
                  ) : (
                    <>
                      {t("new_knowledge_auto_link")}{" "}
                      <span className="font-mono">{serviceLabel ?? serviceId}</span>
                    </>
                  )}
                </p>
                <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={resetEditor}>
                  {t("cancel")}
                </Button>
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-36 flex-1 space-y-1">
                  <Label className="text-xs">{t("name")}</Label>
                  <Input
                    className="h-8 font-mono text-xs"
                    placeholder={`runbook-${serviceLabel ?? serviceId}`}
                    value={kName}
                    onChange={(e) => setKName(e.target.value)}
                  />
                </div>
                <Select value={kFolder} onValueChange={(v) => setKFolder(v as KnowledgeFolder)}>
                  <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {KNOWLEDGE_FOLDERS.map((f) => (
                      <SelectItem key={f.id} value={f.id}>{f.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Meta (JSON)</Label>
                <Textarea
                  rows={3}
                  className="min-h-16 max-h-[20vh] resize-y font-mono text-xs leading-relaxed"
                  placeholder='{"criticality": "high", "thresholds": {"error_count_warning": 5}}'
                  value={kMetaJson}
                  onChange={(e) => setKMetaJson(e.target.value)}
                />
                <p className="text-[11px] text-muted-foreground">
                  Optional structured metadata for agent routing & RCA
                </p>
              </div>
              <div className="flex w-fit rounded-md border p-0.5 text-xs">
                {(["tulis", "preview"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={cn(
                      "rounded px-2.5 py-1 capitalize transition-colors",
                      mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                    onClick={() => setMode(m)}
                  >
                    {m === "tulis" ? "✍️ Tulis" : "👁 Preview"}
                  </button>
                ))}
              </div>
              {mode === "tulis" ? (
                <Textarea
                  rows={10}
                  className="min-h-[220px] max-h-[45vh] resize-y overflow-y-auto font-mono text-xs leading-relaxed"
                  placeholder={t("placeholder_runbook")}
                  value={kContent}
                  onChange={(e) => setKContent(e.target.value)}
                />
              ) : (
                <Suspense fallback={<Skeleton className="h-48 w-full" />}>
                  <div className="min-h-[220px] max-h-[45vh] overflow-y-auto rounded-md border bg-background p-3">
                    {kContent.trim()
                      ? <MarkdownView content={kContent} />
                      : <p className="text-sm text-muted-foreground">{t("no_content")}</p>}
                  </div>
                </Suspense>
              )}
              {!isEditingExisting && kContent.length > 0 && kContent.length < 50 && (
                <p className="text-[11px] text-amber-600">
                  {t("content_min_chars", { current: kContent.length, min: 50 })}
                </p>
              )}
              {/* ── Project selection (workspace context only) ── */}
              {!isEditingExisting && workspaceId && allProjects && allProjects.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs">{t("link_projects_label")}</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 text-xs text-muted-foreground"
                      onClick={() => {
                        const allIds = allProjects.map((p) => p.id)
                        const allSelected = allIds.length === selectedProjectIds.size
                        setSelectedProjectIds(allSelected ? new Set() : new Set(allIds))
                      }}
                    >
                      {selectedProjectIds.size === allProjects.length
                        ? t("deselect_all")
                        : t("select_all")}
                    </Button>
                  </div>
                  <div className="max-h-40 overflow-y-auto rounded-lg border p-2 space-y-0.5">
                    {allProjects.map((p) => (
                      <label
                        key={p.id}
                        className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-muted"
                      >
                        <input
                          type="checkbox"
                          className="size-3.5 accent-primary"
                          checked={selectedProjectIds.has(p.id)}
                          onChange={(e) => {
                            setSelectedProjectIds((prev) => {
                              const next = new Set(prev)
                              if (e.target.checked) next.add(p.id)
                              else next.delete(p.id)
                              return next
                            })
                          }}
                        />
                        <span className="font-medium">{p.name}</span>
                      </label>
                    ))}
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    {t("link_projects_hint", { count: selectedProjectIds.size })}
                  </p>
                </div>
              )}
              <Button
                size="sm"
                className="w-full"
                disabled={createKb.isPending || link.isPending || !kName.trim() || !kContent.trim()}
                onClick={isEditingExisting ? saveEdit : saveNew}
              >
                {createKb.isPending || link.isPending
                  ? t("saving")
                  : isEditingExisting
                    ? t("save_changes")
                    : t("save_and_link_service")}
              </Button>
              {(!kName.trim() || !kContent.trim()) && (
                <p className="text-center text-[11px] text-muted-foreground">
                  {t("fill_name_content")}
                </p>
              )}
            </div>
          )}

          {/* ── List ter-link ── */}
          <div className="space-y-1.5">
            <Label className="text-xs">{t("linked_count", { count: links?.length ?? 0 })}</Label>
            {isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : (links ?? []).length === 0 ? (
              <p className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">
                {t("no_linked_knowledge")}
              </p>
            ) : (
              (links ?? []).map((l) => {
                const mine = l.ownerId === meId || l.ownerId?.startsWith("system:") || isAdmin
                return (
                  <div key={l.id} className="flex items-center gap-2 rounded-lg border px-3 py-1.5">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">{l.name}</span>
                    {!mine && (
                      <span className="shrink-0 text-[10px] text-muted-foreground" title={t("read_only_other_owner")}>
                        🔒
                      </span>
                    )}
                    <Button variant="ghost" size="icon" className="size-7" title={t("btn_view")}
                      onClick={() => openView(l.knowledgeLibraryId, l.name)}>
                      <Eye className="size-3.5" />
                    </Button>
                    {mine && (
                      <>
                        <Button variant="ghost" size="icon" className="size-7" title={t("btn_edit")}
                          onClick={() => openEdit(l.knowledgeLibraryId, l.name, l.folder)}>
                          <Pencil className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7 text-destructive hover:text-destructive"
                          title={t("btn_unlink")}
                          onClick={() => unlink.mutate(l.id)}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </>
                    )}
                  </div>
                )
              })
            )}
          </div>

          {/* ── Picker dari library sendiri ── */}
          {linkable.length > 0 && (
            <div className="space-y-1.5 border-t pt-3">
              <Label className="text-xs">{t("or_link_from_my_library")}</Label>
              <div className="max-h-40 space-y-1.5 overflow-y-auto">
                {linkable.map((k) => (
                  <button
                    key={k.id}
                    className="flex w-full items-center gap-2.5 rounded-lg border px-3 py-1.5 text-left hover:bg-accent disabled:opacity-50"
                    disabled={link.isPending}
                    onClick={() => link.mutate(k.id)}
                  >
                    <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">{k.name}</span>
                    <Badge variant="secondary" className="text-[10px]">{t(`folders.${k.folder}`)}</Badge>
                  </button>
                ))}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* View markdown */}
      <KnowledgeViewDialog
        doc={viewDoc}
        onClose={() => { setViewDoc(null); setActiveKnowledgeId(null) }}
        items={(links ?? []).map((l) => ({ knowledgeLibraryId: l.knowledgeLibraryId, name: l.name, folder: l.folder }))}
        activeKnowledgeId={activeKnowledgeId ?? undefined}
        onNavigate={navigateKnowledge}
      />
    </>
  )
}
