import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  CircleCheck,
  CircleDashed,
  Database,
  FilePlus2,
  FileText,
  Pencil,
  PlugZap,
  Plus,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"
import { api, apiErrorMessage } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  useWsRegistryMutations,
  useWsServiceRegistry,
  type WsRegistryItem,
} from "@/hooks/useManagement"
import { useWorkspaceServiceGroups } from "@/hooks/useServicesLib"
import { useAuth } from "@/hooks/useAuth"
import { useProjects } from "@/hooks/useWorkspaces"

const ServiceKnowledgeDialogLazy = lazy(() =>
  import("@/components/shared/ServiceKnowledgeDialog").then((m) => ({
    default: m.ServiceKnowledgeDialog,
  })),
)

interface KnowledgeEntry {
  refId: string
  knowledgeLibraryId: string
  name: string
  folder: string
  ownerId: string
  libraryServiceId: string // item library pemilik link ini
}

interface RegistryEditorState {
  item: WsRegistryItem | null
  service_id: string
  label: string
  db_enabled: boolean
  db_type: "mongodb" | "mysql"
  db_uri: string
  db_dbname: string
  db_collection: string
}

/**
 * WorkspaceServiceHierarchy — FE-8.6.
 * Tab Service direstrukturisasi jadi hierarki:
 *   service registry → RAG Log DB (db_config) → knowledge terhubung.
 * Knowledge digabung dari semua project workspace via kecocokan `service_id`.
 * Kepemilikan ketat: edit/hapus dokumen & link = owner masing-masing (🔒 lainnya).
 */
export function WorkspaceServiceHierarchy({
  workspaceId,
  isAdmin,
}: {
  workspaceId: string
  isAdmin: boolean
}) {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  const { user: me } = useAuth()
  const meId = me?.id ?? ""
  const { data: items, isLoading } = useWsServiceRegistry(workspaceId)
  const { data: groups } = useWorkspaceServiceGroups(workspaceId)
  const { create, update, remove, testConnection } = useWsRegistryMutations(workspaceId)

  const [editor, setEditor] = useState<RegistryEditorState | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<WsRegistryItem | null>(null)
  const [knowledgeFor, setKnowledgeFor] = useState<{
    libraryServiceId: string
    serviceId: string
    autoCreate?: boolean
    initialEditId?: string
    initialEditName?: string
    initialEditFolder?: string
  } | null>(null)

  // Project selection for create dialog
  const { data: allProjects } = useProjects(workspaceId)
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set())
  const prevProjectsRef = useRef<string[]>([])
  useEffect(() => {
    if (allProjects && prevProjectsRef.current.length === 0 && allProjects.length > 0) {
      setSelectedProjectIds(new Set(allProjects.map((p) => p.id)))
    }
    prevProjectsRef.current = allProjects?.map((p) => p.id) ?? []
  }, [allProjects])

  const [activatingFor, setActivatingFor] = useState<string | null>(null)
  // FE-8.6 fix v2: satu tombol pintar — entri library dibuat OTOMATIS bila belum ada,
  // lalu panel kelola langsung terbuka (tidak ada langkah "Aktifkan" manual lagi).
  async function openKnowledgeManager(serviceId: string) {
    const existing = ownLibSvcByServiceId[serviceId]
    if (existing) {
      setKnowledgeFor({ libraryServiceId: existing, serviceId })
      return
    }
    // FIX: cek apakah service sudah ada di library global (bukan punya kita)
    // sebelum coba buat baru — hindari error "sudah ada"
    try {
      const { data: myServices } = await api.get("/services/library")
      const found = (myServices.items ?? []).find((s: any) => s.serviceId === serviceId)
      if (found) {
        qc.invalidateQueries({ queryKey: ["services"] })
        setKnowledgeFor({ libraryServiceId: found.id, serviceId })
        return
      }
    } catch {
      // lanjut buat baru
    }
    try {
      setActivatingFor(serviceId)
      const { data } = await api.post("/services/library", { service_id: serviceId })
      qc.invalidateQueries({ queryKey: ["services"] })
      setKnowledgeFor({ libraryServiceId: data.id, serviceId })
    } catch (e) {
      toast.error(apiErrorMessage(e, t("hierarchy.prepare_failed")))
    } finally {
      setActivatingFor(null)
    }
  }

  // Join: knowledge per service_id dari semua project (grouped endpoint)
  const knowledgeByServiceId = useMemo(() => {
    const map: Record<string, KnowledgeEntry[]> = {}
    for (const g of groups ?? []) {
      for (const s of g.services) {
        for (const k of s.knowledge ?? []) {
          const list = map[s.serviceId] ?? (map[s.serviceId] = [])
          if (!list.some((x) => x.knowledgeLibraryId === k.knowledgeLibraryId)) {
            map[s.serviceId].push({
              refId: k.refId,
              knowledgeLibraryId: k.knowledgeLibraryId,
              name: k.name,
              folder: k.folder,
              ownerId: k.ownerId,
              libraryServiceId: s.libraryServiceId,
            })
          }
        }
      }
    }
    return map
  }, [groups])

  // library service milikku per service_id — untuk tombol kelola/tulis baru
  const ownLibSvcByServiceId = useMemo(() => {
    const map: Record<string, string> = {}
    for (const g of groups ?? []) {
      for (const s of g.services) {
        if (s.ownerId === meId && s.serviceId) map[s.serviceId] = s.libraryServiceId
      }
    }
    return map
  }, [groups, meId])

  function openEdit(item: WsRegistryItem) {
    setEditor({
      item,
      service_id: item.service_id,
      label: item.label ?? "",
      db_enabled: !!item.db_config,
      db_type: (item.db_config?.type as "mongodb" | "mysql") ?? "mongodb",
      db_uri: "",
      db_dbname: item.db_config?.db ?? "",
      db_collection: item.db_config?.collection ?? "",
    })
  }

  function openCreate() {
    setEditor({
      item: null,
      service_id: "",
      label: "",
      db_enabled: false,
      db_type: "mongodb",
      db_uri: "",
      db_dbname: "",
      db_collection: "",
    })
  }

  function saveEditor() {
    if (!editor || !editor.service_id) return
    const dbPayload =
      editor.db_enabled && editor.db_uri && editor.db_dbname
        ? {
            db_type: editor.db_type,
            db_uri: editor.db_uri,
            db_name: editor.db_dbname,
            ...(editor.db_collection ? { db_collection: editor.db_collection } : {}),
          }
        : !editor.db_enabled
          ? {
              db_type: undefined as unknown as string | undefined,
              db_uri: undefined as unknown as string | undefined,
              db_name: undefined as unknown as string | undefined,
              db_collection: undefined as unknown as string | undefined,
            }
          : {}
    if (editor.item) {
      update.mutate(
        { registry_id: editor.item.registry_id, label: editor.label, ...dbPayload },
        { onSuccess: () => setEditor(null) },
      )
    } else {
      create.mutate(
        { service_id: editor.service_id, label: editor.label, ...dbPayload, project_ids: Array.from(selectedProjectIds) },
        { onSuccess: () => setEditor(null) },
      )
    }
  }

  const editorValid =
    !!editor &&
    (editor.item ? true : /^[a-z0-9_-]{2,64}$/.test(editor.service_id)) &&
    (!editor.db_enabled || (editor.db_uri.length > 4 && editor.db_dbname.length >= 1))

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          <span dangerouslySetInnerHTML={{ __html: t("hierarchy.intro_strong") }} />
        </p>
        {isAdmin && (
          <Button size="sm" onClick={openCreate}>
            <Plus className="size-4" /> {t("hierarchy.add")}
          </Button>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="h-32 w-full rounded-lg" />
      ) : (items ?? []).length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          {t("hierarchy.empty")}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-[11px]">{t("hierarchy.col_service")}</TableHead>
                <TableHead className="hidden text-[11px] sm:table-cell">{t("hierarchy.col_log_db")}</TableHead>
                <TableHead className="text-right text-[11px]">{t("hierarchy.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(items ?? []).map((it) => {
                const knowledge = dedupe(knowledgeByServiceId[it.service_id] ?? [])
                return (
                  <TableRow key={it.registry_id} className="align-middle hover:bg-accent/40">
                    <TableCell className="py-2">
                      <div className="flex min-w-48 flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="truncate text-sm font-medium" title={it.label || it.service_id}>
                            {it.label || it.service_id}
                          </span>
                          <Badge variant="outline" className="shrink-0 gap-1 px-1 text-[9px]" title={t("hierarchy.manage_knowledge_title")}>
                            <FileText className="size-2.5" />
                            {knowledge.length}
                          </Badge>
                        </div>
                        <span className="text-[11px] text-muted-foreground">
                          {it.db_config ? (
                            <span className="flex items-center gap-1.5">
                              <Database className="size-3 shrink-0 text-emerald-600 dark:text-emerald-400" />
                              <span className="truncate font-mono text-[10px]">
                                {it.db_config.type} · {it.db_config.db}
                                {it.db_config.collection ? ` · ${it.db_config.collection}` : ""}
                              </span>
                            </span>
                          ) : (
                            <span className="flex items-center gap-1">
                              <CircleDashed className="size-3 shrink-0" />
                              {t("hierarchy.db_not_set")}
                            </span>
                          )}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden py-2 sm:table-cell">
                      {it.db_config ? (
                        it.health_status === "ok" ? (
                          <Badge
                            variant="outline"
                            className="shrink-0 gap-1 border-emerald-600/40 bg-emerald-500/10 px-1.5 py-0 text-[10px] font-medium text-emerald-700 dark:border-emerald-400/30 dark:text-emerald-400"
                          >
                            <CircleCheck className="size-2.5" /> {t("hierarchy.connected_badge")}
                          </Badge>
                        ) : it.health_status && it.health_status.startsWith("error") ? (
                          <Badge
                            variant="outline"
                            className="shrink-0 gap-1 border-red-600/40 bg-red-500/10 px-1.5 py-0 text-[10px] font-medium text-red-700 dark:border-red-400/30 dark:text-red-400"
                            title={it.health_status}
                          >
                            <CircleDashed className="size-2.5" /> {t("hierarchy.conn_error_badge")}
                          </Badge>
                        ) : (
                          <Badge
                            variant="outline"
                            className="shrink-0 gap-1 px-1.5 py-0 text-[10px] font-medium text-muted-foreground"
                            title={t("hierarchy.conn_untested_title")}
                          >
                            <CircleDashed className="size-2.5" /> {t("hierarchy.conn_untested_badge")}
                          </Badge>
                        )
                      ) : (
                        <span className="text-xs text-muted-foreground">{t("hierarchy.db_not_set")}</span>
                      )}
                    </TableCell>
                    <TableCell className="py-2">
                      <div className="flex flex-wrap items-center justify-end gap-1">
                        <Button size="sm" variant="outline" className="h-6 gap-1 px-2 text-[11px]"
                          disabled={activatingFor === it.service_id}
                          title={t("hierarchy.manage_knowledge_title")}
                          onClick={() => openKnowledgeManager(it.service_id)}>
                          <FilePlus2 className="size-3" />
                          {activatingFor === it.service_id
                            ? t("hierarchy.preparing")
                            : knowledge.length > 0
                              ? t("hierarchy.manage_knowledge")
                              : t("hierarchy.add_knowledge")}
                        </Button>
                        <Button
                          variant="ghost" size="sm" className="h-6 px-1.5 text-[11px]"
                          disabled={!it.db_config || testConnection.isPending}
                          title={it.db_config ? t("hierarchy.test_connection_title") : t("hierarchy.fill_db_first")}
                          onClick={() => testConnection.mutate(it.registry_id)}
                        >
                          <PlugZap className="mr-1 size-3" />
                          {testConnection.isPending ? "…" : "Test"}
                        </Button>
                        {isAdmin && (
                          <>
                            <Button variant="ghost" size="icon" className="size-6" title="Edit service"
                              onClick={() => openEdit(it)}>
                              <Pencil className="size-3" />
                            </Button>
                            <Button
                              variant="ghost" size="icon"
                              className="size-6 text-destructive hover:text-destructive"
                              title={t("hierarchy.delete_from_registry")}
                              onClick={() => setConfirmDelete(it)}
                            >
                              <Trash2 className="size-3" />
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Registry create/edit dialog */}
      <Dialog open={!!editor} onOpenChange={(o) => !o && setEditor(null)}>
        <DialogContent className="max-w-lg overflow-y-auto max-h-[88vh]">
          <DialogHeader>
            <DialogTitle>{editor?.item ? t("hierarchy.edit_service_title", { id: editor.item.service_id }) : t("hierarchy.create_service_title")}</DialogTitle>
            <DialogDescription>{t("hierarchy.dialog_description")}</DialogDescription>
          </DialogHeader>
          {editor && (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label>{t("hierarchy.service_id_label")}</Label>
                <Input
                  placeholder={t("hierarchy.service_id_placeholder", { ns: "workspace" })}
                  value={editor.service_id}
                  onChange={(e) =>
                    !editor.item &&
                    setEditor({
                      ...editor,
                      service_id: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""),
                    })
                  }
                  disabled={!!editor.item}
                  className="font-mono text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("hierarchy.label_optional")}</Label>
                <Input placeholder="Production Core API" value={editor.label}
                  onChange={(e) => setEditor({ ...editor, label: e.target.value })} />
              </div>
              <div className="rounded-lg border p-3">
                <Label className="flex cursor-pointer items-center gap-2 text-sm font-normal">
                  <input type="checkbox" checked={editor.db_enabled}
                    onChange={(e) => setEditor({ ...editor, db_enabled: e.target.checked })}
                    className="size-4 accent-primary" />
                  {t("hierarchy.db_checkbox")}
                </Label>
                {editor.db_enabled && (
                  <div className="mt-3 space-y-3">
                    <div className="grid grid-cols-[110px_1fr] gap-2">
                      <Select value={editor.db_type}
                        onValueChange={(v) => setEditor({ ...editor, db_type: v as "mongodb" | "mysql" })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="mongodb">MongoDB</SelectItem>
                          <SelectItem value="mysql">MySQL</SelectItem>
                        </SelectContent>
                      </Select>
                      <Input placeholder={editor.item?.db_config?.uri || "mongodb://…"}
                        value={editor.db_uri}
                        onChange={(e) => setEditor({ ...editor, db_uri: e.target.value })}
                        className="font-mono text-xs" />
                    </div>
                    {editor.item?.db_config?.uri && !editor.db_uri && (
                      <p className="text-xs text-muted-foreground">
                        {t("hierarchy.saved_uri_hint", { uri: editor.item.db_config.uri })}
                      </p>
                    )}
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Input placeholder={t("hierarchy.dbname_placeholder")} value={editor.db_dbname}
                        onChange={(e) => setEditor({ ...editor, db_dbname: e.target.value })}
                        className="font-mono text-xs" />
                      <Input placeholder={t("hierarchy.collection_placeholder")} value={editor.db_collection}
                        onChange={(e) => setEditor({ ...editor, db_collection: e.target.value })}
                        className="font-mono text-xs" />
                    </div>
                  </div>
                )}
              </div>
              {/* Project selection — only on create */}
              {!editor?.item && allProjects && allProjects.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs">{t("hierarchy.link_projects_label")}</Label>
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
                        ? t("hierarchy.deselect_all")
                        : t("hierarchy.select_all")}
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
                    {t("hierarchy.link_projects_hint", { count: selectedProjectIds.size })}
                  </p>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditor(null)}>{t("action.cancel", { ns: "common" })}</Button>
            <Button onClick={saveEditor} disabled={create.isPending || update.isPending || !editorValid}>
              {create.isPending || update.isPending ? t("form.saving", { ns: "project" }) : t("action.save", { ns: "common" })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirm hapus registry */}
      <AlertDialog open={!!confirmDelete} onOpenChange={(o) => !o && setConfirmDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("hierarchy.delete_confirm_title", { id: confirmDelete?.service_id ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("hierarchy.delete_confirm_desc")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmDelete) remove.mutate(confirmDelete.registry_id)
                setConfirmDelete(null)
              }}
            >
              {t("hierarchy.delete_from_registry")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Panel kelola knowledge (shared — tulis baru auto-link + picker + view/edit) */}
      {knowledgeFor && (
        <Suspense fallback={<Skeleton className="h-64 w-full" />}>
          <ServiceKnowledgeDialogLazy
            serviceId={knowledgeFor.libraryServiceId}
            serviceLabel={knowledgeFor.serviceId}
            meId={meId}
            isAdmin={isAdmin}
            onClose={() => setKnowledgeFor(null)}
            initialEditId={knowledgeFor.initialEditId}
            initialEditName={knowledgeFor.initialEditName}
            initialEditFolder={knowledgeFor.initialEditFolder}
            workspaceId={workspaceId}
          />
        </Suspense>
      )}
    </div>
  )
}

function dedupe(list: KnowledgeEntry[]): KnowledgeEntry[] {
  const seen = new Set<string>()
  return list.filter((k) =>
    seen.has(k.knowledgeLibraryId) ? false : (seen.add(k.knowledgeLibraryId), true),
  )
}
