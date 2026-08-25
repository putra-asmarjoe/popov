import { lazy, Suspense, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"
import { Boxes, Database, Eye, FilePlus2, FileText, Lock, Pencil, Trash2 } from "lucide-react"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/hooks/useAuth"
import {
  fetchServiceUsage,
  type ServiceInput,
  useCreateService,
  useDeleteService,
  useMyServices,
  useServiceKnowledge,
  useServiceRegistry,
  useUnlinkServiceKnowledge,
  useUpdateService,
} from "@/hooks/useServicesLib"
import { ServiceKnowledgeDialog } from "@/components/shared/ServiceKnowledgeDialog"
import type { ServiceKnowledgeLink, ServiceLibraryItem, ServiceUsage } from "@/types/service"

const MarkdownView = lazy(() =>
  import("@/components/shared/MarkdownView").then((m) => ({ default: m.MarkdownView })),
)

const KB_FOLDERS = ["general", "services", "playbooks", "schemas", "connections", "observability"]

interface EditorState {
  item: ServiceLibraryItem | null // null = create
  service_id: string
  label: string
  description: string
  db_enabled: boolean
  db_type: "mongodb" | "mysql"
  db_uri: string
  db_dbname: string
  db_collection: string
}

/**
 * ServiceLibraryCard — kartu hierarki service (mengikuti UI Workspace Settings → Service):
 * header service → RAG log DB → Knowledge Service (daftar ter-link + kelola).
 * Data dari library GENERAL (service_store) — knowledge per-service via useServiceKnowledge.
 */
function ServiceLibraryCard({
  item,
  meId,
  isAdmin,
  onEdit,
  onDelete,
  onManage,
}: {
  item: ServiceLibraryItem
  meId: string
  isAdmin?: boolean
  onEdit: (i: ServiceLibraryItem) => void
  onDelete: (i: ServiceLibraryItem) => void
  onManage: (i: ServiceLibraryItem) => void
}) {
  const { t } = useTranslation("management")
  const { data: links } = useServiceKnowledge(item.id)
  const unlink = useUnlinkServiceKnowledge(item.id)
  const qc = useQueryClient()
  const [viewDoc, setViewDoc] = useState<{ name: string; content: string } | null>(null)
  const [editDoc, setEditDoc] = useState<{ id: string; name: string; folder: string; content: string } | null>(null)

  const knowledge: ServiceKnowledgeLink[] = links ?? []
  // Admin global dipercaya penuh di panel management — bypass cek kepemilikan UI.
  const kbMine = (k: ServiceKnowledgeLink) => !!isAdmin || k.ownerId === meId

  const openView = async (k: ServiceKnowledgeLink) => {
    try {
      const { data } = await api.get(`/knowledge/library/${k.knowledgeLibraryId}`)
      setViewDoc({ name: k.name, content: data.content ?? "" })
    } catch (e) {
      toast.error(apiErrorMessage(e, t("service_library.owner_only_read_error")))
    }
  }

  const openEditDoc = async (k: ServiceKnowledgeLink) => {
    try {
      const { data } = await api.get(`/knowledge/library/${k.knowledgeLibraryId}`)
      setEditDoc({
        id: k.knowledgeLibraryId,
        name: data.name ?? k.name,
        folder: data.folder ?? k.folder,
        content: data.content ?? "",
      })
    } catch (e) {
      toast.error(apiErrorMessage(e, t("service_library.owner_only_edit_error")))
    }
  }

  const saveEditDoc = () => {
    if (!editDoc || !editDoc.name.trim() || !editDoc.content.trim()) return
    api
      .patch(`/knowledge/library/${editDoc.id}`, {
        name: editDoc.name,
        folder: editDoc.folder,
        content: editDoc.content,
      })
      .then(() => {
        setEditDoc(null)
        qc.invalidateQueries({ queryKey: ["services"] })
      })
      .catch((e) => toast.error(apiErrorMessage(e, t("service_library.update_failed"))))
  }

  return (
    <div className="rounded-lg border">
      {/* ── Header service ── */}
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.label || item.serviceId}</span>
        <Button variant="ghost" size="icon" className="size-7" title={t("hierarchy.edit_doc", { ns: "workspace" })} onClick={() => onEdit(item)}>
          <Pencil className="size-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-7 text-destructive hover:text-destructive"
          title={t("service_library.delete_from_library")}
          onClick={() => onDelete(item)}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>

      {/* ── RAG Log DB (hanya tampil bila terisi) ── */}
      {item.dbConfig && (
        <div className="flex items-center gap-1.5 px-3 py-1.5">
          <Database className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="font-mono text-xs">
            {item.dbConfig.type} · {item.dbConfig.db}
            {item.dbConfig.collection ? ` · ${item.dbConfig.collection}` : ""}
            {item.dbConfig.has_uri && <span className="ml-1 text-muted-foreground">(URI tersamar)</span>}
          </span>
        </div>
      )}

      {/* ── Knowledge Service (tenant, knowledge_library) ── */}
      <div className="border-t px-3 py-2">
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {t("service_library.knowledge_section", { count: knowledge.length })}
        </p>
        {knowledge.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("service_library.knowledge_empty")}</p>
        ) : (
          <div className="space-y-1">
            {knowledge.map((k) => (
              <div
                key={k.id}
                className="flex items-center gap-1.5 rounded px-1.5 py-0.5 hover:bg-accent/40"
              >
                <FileText className="size-3 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate font-mono text-[11px]">{k.name}</span>
                <Badge variant="secondary" className="shrink-0 text-[9px]">{k.folder}</Badge>
                {!kbMine(k) && <Lock className="size-2.5 shrink-0 text-muted-foreground" />}
                <Button variant="ghost" size="icon" className="size-6" title="Baca" onClick={() => openView(k)}>
                  <Eye className="size-3" />
                </Button>
                {kbMine(k) && (
                  <>
                    <Button variant="ghost" size="icon" className="size-6" title="Edit dokumen" onClick={() => openEditDoc(k)}>
                      <Pencil className="size-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6 text-destructive hover:text-destructive"
                      title={t("service_library.unlink_from_service")}
                      onClick={() => unlink.mutate(k.id)}
                    >
                      <Trash2 className="size-3" />
                    </Button>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
        <Button
          size="sm"
          variant="outline"
          className="mt-2 h-6 gap-1 px-2 text-[11px]"
          title={t("service_library.manage_knowledge_title")}
          onClick={() => onManage(item)}
        >
          <FilePlus2 className="size-3" /> {t("service_library.manage_knowledge")}
        </Button>
      </div>

      {/* View dokumen */}
      <Dialog open={!!viewDoc} onOpenChange={(o) => !o && setViewDoc(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{viewDoc?.name}</DialogTitle>
          </DialogHeader>
          <Suspense fallback={<Skeleton className="h-48 w-full" />}>
            <div className="min-h-24 rounded-md border bg-muted/30 p-4">
              <MarkdownView content={viewDoc?.content ?? ""} />
            </div>
          </Suspense>
        </DialogContent>
      </Dialog>

      {/* Edit dokumen */}
      <Dialog open={!!editDoc} onOpenChange={(o) => !o && setEditDoc(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("service_library.edit_doc_title")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>{t("service_library.doc_name_label")}</Label>
                <Input
                  value={editDoc?.name ?? ""}
                  onChange={(e) => editDoc && setEditDoc({ ...editDoc, name: e.target.value })}
                  className="font-mono text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("service_library.category_label")}</Label>
                <Select
                  value={editDoc?.folder ?? "general"}
                  onValueChange={(v) => editDoc && setEditDoc({ ...editDoc, folder: v })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {KB_FOLDERS.map((f) => (
                      <SelectItem key={f} value={f}>{f}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>{t("service_library.content_label")}</Label>
              <Textarea
                rows={10}
                value={editDoc?.content ?? ""}
                onChange={(e) => editDoc && setEditDoc({ ...editDoc, content: e.target.value })}
                className="min-h-48 resize-y font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditDoc(null)}>{t("apikeys.cancel")}</Button>
            <Button onClick={saveEditDoc}>{t("apikeys.save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/**
 * Tab Services (/management) — FE-8: Library Service pribadi.
 * Fix #38: service_id BEBAS dibuat (analogi deployment K8s) + koneksi log DB opsional.
 * Kelola knowledge per-service (1 service : N knowledge) di sini.
 */
export function ServiceLibrary() {
  const { t } = useTranslation("management")
  const { data: items, isLoading } = useMyServices()
  const { data: registry } = useServiceRegistry()
  const { user: me } = useAuth()
  const isAdmin = me?.role === "admin"
  const create = useCreateService()
  const update = useUpdateService()
  const remove = useDeleteService()
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<{ item: ServiceLibraryItem; projects?: ServiceUsage[] } | null>(null)
  const [manageKnowledge, setManageKnowledge] = useState<ServiceLibraryItem | null>(null)
  const [quickCreate, setQuickCreate] = useState(false) // jalan pintas: buka editor knowledge baru

  const openCreate = () => setEditor({ item: null, service_id: "", label: "", description: "", db_enabled: false, db_type: "mongodb", db_uri: "", db_dbname: "", db_collection: "" })
  const openEdit = (item: ServiceLibraryItem) =>
    setEditor({
      item,
      service_id: item.serviceId,
      label: item.label ?? "",
      description: item.description ?? "",
      db_enabled: !!item.dbConfig,
      db_type: (item.dbConfig?.type as "mongodb" | "mysql") ?? "mongodb",
      db_uri: "", // URI di-mask — isi ulang hanya bila mau mengganti
      db_dbname: item.dbConfig?.db ?? "",
      db_collection: item.dbConfig?.collection ?? "",
    })

  const save = () => {
    if (!editor || !editor.service_id) return
    // db_config hanya dikirim bila diaktifkan & cukup field
    const dbConfig =
      editor.db_enabled && editor.db_uri && editor.db_dbname
        ? {
            type: editor.db_type,
            uri: editor.db_uri,
            db: editor.db_dbname,
            ...(editor.db_collection ? { collection: editor.db_collection } : {}),
          }
        : editor.item?.dbConfig && !editor.db_enabled
          ? null // eksplisit hapus koneksi (backend: db_config kosong/null = hapus)
          : undefined
    if (editor.item) {
      update.mutate(
        {
          id: editor.item.id,
          label: editor.label,
          description: editor.description,
          ...(dbConfig !== undefined ? { db_config: dbConfig as unknown as NonNullable<ServiceInput['db_config']> } : {}),
        },
        { onSuccess: () => setEditor(null) },
      )
    } else {
      create.mutate(
        {
          service_id: editor.service_id,
          label: editor.label,
          description: editor.description,
          ...(dbConfig ? { db_config: dbConfig } : {}),
        },
        { onSuccess: () => setEditor(null) },
      )
    }
  }

  const askDelete = async (item: ServiceLibraryItem) => {
    let projects: ServiceUsage[] | undefined
    try {
      projects = await fetchServiceUsage(item.id)
    } catch {
      projects = undefined
    }
    setConfirmDelete({ item, projects })
  }

  // service global yang belum ada di library saya → bisa ditambahkan
  const available = useMemo(() => {
    const owned = new Set((items ?? []).map((i) => i.serviceId))
    return (registry ?? []).filter((r) => !owned.has(r.service_id))
  }, [items, registry])

  if (isLoading) return <Skeleton className="h-64 w-full rounded-lg" />

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Service — General</h2>
          <p className="text-xs text-muted-foreground">
            <span dangerouslySetInnerHTML={{ __html: t("service_library.intro_strong") }} />
          </p>
        </div>
        <Button size="sm" className="gap-1.5" onClick={openCreate}>
          <Boxes className="size-4" /> {t("service_library.add_service")}
        </Button>
      </div>

      <div className="space-y-3">
        {(items ?? []).length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-lg border p-10 text-center text-muted-foreground">
            <Boxes className="size-8 opacity-40" />
            <p className="text-sm">
              {t("service_library.empty_services")}
              {available.length === 0 && t("service_library.all_registered_suffix")}
            </p>
          </div>
        ) : (
          (items ?? []).map((item) => (
            <ServiceLibraryCard
              key={item.id}
              item={item}
              meId={me?.id ?? ""}
              isAdmin={isAdmin}
              onEdit={openEdit}
              onDelete={askDelete}
              onManage={(i) => { setQuickCreate(false); setManageKnowledge(i) }}
            />
          ))
        )}
      </div>

      {/* Create/Edit dialog */}
      <Dialog open={!!editor} onOpenChange={(open) => !open && setEditor(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editor?.item ? t("service_library.edit_dialog_title", { id: editor.item.serviceId }) : t("service_library.create_dialog_title")}</DialogTitle>
            <DialogDescription>
              <span dangerouslySetInnerHTML={{ __html: t("service_library.create_dialog_description") }} />
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>{t("hierarchy.service_id_label", { ns: "workspace" })}</Label>
              <Input
                placeholder="nama-deployment-k8s"
                value={editor?.service_id ?? ""}
                onChange={(e) =>
                  editor &&
                  !editor.item &&
                  setEditor({ ...editor, service_id: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })
                }
                disabled={!!editor?.item}
                className="font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                {editor?.item && editor.item.globallyRegistered === false
                  ? t("service_library.custom_service_hint")
                  : t("service_library.global_service_hint")}
              </p>
            </div>
            {registry && registry.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {(registry ?? []).slice(0, 8).map((r) => (
                  <button
                    key={r.service_id}
                    type="button"
                    disabled={!!editor?.item}
                    className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                      editor?.service_id === r.service_id
                        ? "border-primary bg-primary/10 text-primary"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                    onClick={() => editor && !editor.item && setEditor({ ...editor, service_id: r.service_id })}
                  >
                    {r.service_id}
                  </button>
                ))}
              </div>
            )}
            <div className="space-y-1.5">
              <Label>{t("service_library.label_optional")}</Label>
              <Input
                placeholder={t("service_library.label_placeholder")}
                value={editor?.label ?? ""}
                onChange={(e) => editor && setEditor({ ...editor, label: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t("service_library.description_optional")}</Label>
              <Textarea
                rows={2}
                placeholder={t("service_library.description_placeholder")}
                value={editor?.description ?? ""}
                onChange={(e) => editor && setEditor({ ...editor, description: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditor(null)}>{t("apikeys.cancel")}</Button>
            <Button onClick={save} disabled={create.isPending || update.isPending || !editor?.service_id}>
              {t("apikeys.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manage knowledge dialog (shared FE-8.1) */}
      {manageKnowledge && (
        <ServiceKnowledgeDialog
          serviceId={manageKnowledge.id}
          serviceLabel={manageKnowledge.serviceId}
          meId={me?.id ?? ""}
          onClose={() => { setManageKnowledge(null); setQuickCreate(false) }}
          autoOpenCreate={quickCreate}
        />
      )}

      {/* Delete confirm (+ warning cascade) */}
      <AlertDialog open={!!confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("service_library.delete_confirm_title", { id: confirmDelete?.item.serviceId ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmDelete?.projects?.length ? (
                <>
                  {t("service_library.delete_in_use_desc", {
                    projects: confirmDelete.projects.map((p) => p.name).join(", "),
                  })}
                </>
              ) : (
                t("service_library.delete_simple_desc")
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("apikeys.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmDelete)
                  remove.mutate({ id: confirmDelete.item.id, confirm: !!confirmDelete.projects?.length })
                setConfirmDelete(null)
              }}
            >
              {t("service_library.delete_confirm_btn")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
