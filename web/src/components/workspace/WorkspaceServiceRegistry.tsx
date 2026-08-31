import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Database, Pencil, Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { WsRegistryItem } from "@/hooks/useManagement"
import { useWsRegistryMutations, useWsServiceRegistry } from "@/hooks/useManagement"
import { useProjects } from "@/hooks/useWorkspaces"

/**
 * WorkspaceServiceRegistry (Fix #41) — migrasi ⚙️ Monitoring Global ke level workspace.
 * Service di sini langsung dipakai supervisor routing & db_loader (log transaksi),
 * menggantikan ketergantungan .env/service_db_configs.json (yang jadi fallback).
 */
export function WorkspaceServiceRegistry({ workspaceId }: { workspaceId: string }) {
  const { t } = useTranslation("workspace")
  const { data: items, isLoading } = useWsServiceRegistry(workspaceId)
  const { create, update, remove, testConnection } = useWsRegistryMutations(workspaceId)
  const [editor, setEditor] = useState<EditorState | null>(null)

  // Project selection
  const { data: allProjects } = useProjects(workspaceId)
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set())
  const prevProjectsRef = useRef<string[]>([])
  useEffect(() => {
    if (allProjects && prevProjectsRef.current.length === 0 && allProjects.length > 0) {
      setSelectedProjectIds(new Set(allProjects.map((p) => p.id)))
    }
    prevProjectsRef.current = allProjects?.map((p) => p.id) ?? []
  }, [allProjects])

  const openCreate = () =>
    setEditor({
      item: null, service_id: "", label: "",
      db_enabled: false, db_type: "mongodb", db_uri: "", db_dbname: "", db_collection: "",
    })
  const openEdit = (item: WsRegistryItem) =>
    setEditor({
      item,
      service_id: item.service_id,
      label: item.label ?? "",
      db_enabled: !!item.db_config,
      db_type: (item.db_config?.type as "mongodb" | "mysql") ?? "mongodb",
      db_uri: "", // masked — isi ulang hanya bila ingin mengganti
      db_dbname: item.db_config?.db ?? "",
      db_collection: item.db_config?.collection ?? "",
    })

  const save = () => {
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
          ? { db_type: undefined as unknown as string | undefined, db_uri: undefined as unknown as string | undefined, db_name: undefined as unknown as string | undefined, db_collection: undefined as unknown as string | undefined }
          : {}
    if (editor.item) {
      update.mutate(
        { registry_id: editor.item.registry_id, label: editor.label, ...dbPayload },
        { onSuccess: () => setEditor(null) },
      )
    } else {
      create.mutate(
        {
          service_id: editor.service_id,
          label: editor.label,
          ...dbPayload,
          project_ids: Array.from(selectedProjectIds),
        },
        { onSuccess: () => setEditor(null) },
      )
    }
  }

  const valid =
    !!editor &&
    (editor.item ? true : /^[a-z0-9_-]{2,64}$/.test(editor.service_id)) &&
    (!editor.db_enabled || (editor.db_uri.length > 4 && editor.db_dbname.length >= 1))

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {t("registry.intro")}
        </p>
        <Button size="sm" onClick={openCreate}>
          <Plus className="size-4" /> {t("registry.add")}
        </Button>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("registry.col_service")}</TableHead>
              <TableHead className="hidden sm:table-cell">{t("registry.col_log_db")}</TableHead>
              <TableHead>{t("registry.col_status")}</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [...Array(3)].map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={4}><Skeleton className="h-8 w-full" /></TableCell>
                </TableRow>
              ))
            ) : (items ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-sm text-muted-foreground">
                  {t("registry.empty")}
                </TableCell>
              </TableRow>
            ) : (
              (items ?? []).map((it) => (
                <TableRow key={it.registry_id}>
                  <TableCell>
                    <div className="font-medium">{it.label || it.service_id}</div>
                    <div className="font-mono text-xs text-muted-foreground">{it.service_id}</div>
                  </TableCell>
                  <TableCell className="hidden text-xs sm:table-cell">
                    {it.db_config ? (
                      <span className="flex items-center gap-1">
                        <Database className="size-3.5" /> {it.db_config.type} · {it.db_config.db}
                        {it.db_config.collection ? ` · ${it.db_config.collection}` : ""}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {it.enabled !== false ? (
                      <Badge variant="secondary">{t("registry.active")}</Badge>
                    ) : (
                      <Badge variant="outline">{t("registry.inactive")}</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={!it.db_config || testConnection.isPending}
                        title={it.db_config ? t("registry.test_connection_title") : t("registry.fill_db_first")}
                        onClick={() => testConnection.mutate(it.registry_id)}
                      >
                        Test
                      </Button>
                      <Button variant="ghost" size="icon" className="size-7" onClick={() => openEdit(it)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7 text-destructive hover:text-destructive"
                        onClick={() => { if (confirm(t("registry.delete_confirm", { id: it.service_id }))) remove.mutate(it.registry_id) }}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Create/Edit dialog */}
      <Dialog open={!!editor} onOpenChange={(open) => !open && setEditor(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editor?.item ? t("registry.edit_title", { id: editor.item.service_id }) : t("registry.create_title")}</DialogTitle>
            <DialogDescription>{t("registry.dialog_description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>{t("registry.service_id_label")}</Label>
              <Input
                placeholder={t("registry.service_id_placeholder", { ns: "workspace" })}
                value={editor?.service_id ?? ""}
                onChange={(e) =>
                  editor && !editor.item &&
                  setEditor({ ...editor, service_id: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })
                }
                disabled={!!editor?.item}
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t("registry.label_optional")}</Label>
              <Input
                placeholder="Production Core API"
                value={editor?.label ?? ""}
                onChange={(e) => editor && setEditor({ ...editor, label: e.target.value })}
              />
            </div>
            <div className="rounded-lg border p-3">
              <Label className="flex cursor-pointer items-center gap-2 text-sm font-normal">
                <input
                  type="checkbox"
                  checked={editor?.db_enabled ?? false}
                  onChange={(e) => editor && setEditor({ ...editor, db_enabled: e.target.checked })}
                  className="size-4 accent-primary"
                />
                {t("registry.db_checkbox")}
              </Label>
              {editor?.db_enabled && (
                <div className="mt-3 space-y-3">
                  <div className="grid grid-cols-[110px_1fr] gap-2">
                    <Select
                      value={editor.db_type}
                      onValueChange={(v) => setEditor({ ...editor, db_type: v as "mongodb" | "mysql" })}
                    >
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="mongodb">MongoDB</SelectItem>
                        <SelectItem value="mysql">MySQL</SelectItem>
                      </SelectContent>
                    </Select>
                    <Input
                      placeholder={editor.item?.db_config?.uri || "mongodb://…"}
                      value={editor.db_uri}
                      onChange={(e) => setEditor({ ...editor, db_uri: e.target.value })}
                      className="font-mono text-xs"
                    />
                  </div>
                  {editor.item?.db_config?.uri && !editor.db_uri && (
                    <p className="text-xs text-muted-foreground">
                      {t("registry.saved_uri_hint", { uri: editor.item.db_config.uri })}
                    </p>
                  )}
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Input
                      placeholder={t("registry.dbname_placeholder")}
                      value={editor.db_dbname}
                      onChange={(e) => setEditor({ ...editor, db_dbname: e.target.value })}
                      className="font-mono text-xs"
                    />
                    <Input
                      placeholder={t("registry.collection_placeholder")}
                      value={editor.db_collection}
                      onChange={(e) => setEditor({ ...editor, db_collection: e.target.value })}
                      className="font-mono text-xs"
                    />
                  </div>
                </div>
              )}
            </div>
            {/* Project selection — only on create, not edit */}
            {!editor?.item && allProjects && allProjects.length > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">{t("registry.link_projects_label")}</Label>
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
                      ? t("registry.deselect_all")
                      : t("registry.select_all")}
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
                  {t("registry.link_projects_hint", { count: selectedProjectIds.size })}
                </p>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditor(null)}>{t("action.cancel", { ns: "common" })}</Button>
            <Button onClick={save} disabled={create.isPending || update.isPending || !valid}>
              {create.isPending || update.isPending ? t("form.saving", { ns: "project" }) : t("action.save", { ns: "common" })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

interface EditorState {
  item: WsRegistryItem | null // null = create
  service_id: string
  label: string
  db_enabled: boolean
  db_type: "mongodb" | "mysql"
  db_uri: string
  db_dbname: string
  db_collection: string
}