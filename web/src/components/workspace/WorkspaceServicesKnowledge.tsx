import { useEffect, useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { Boxes, Link2, Pencil, X } from "lucide-react"
import { toast } from "sonner"
import { api, apiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  useCreateService,
  useLinkServiceFlexible,
  useMyServices,
  useUnlinkServiceFlexible,
  useWorkspaceServiceGroups,
} from "@/hooks/useServicesLib"
import { useWsRegistryList } from "@/hooks/useManagement"
import { useDeleteProject, useProjects } from "@/hooks/useWorkspaces"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { RenameProjectDialog } from "@/components/workspace/RenameProjectDialog"
import type { Project } from "@/types/workspace"

/**
 * WorkspaceServicesKnowledge — FE-8.6 v2.
 * Tab Projects (sederhana): project → daftar service ter-link.
 * Detail RAG & knowledge ada di tab Service (WorkspaceServiceHierarchy).
 */
export function WorkspaceServicesKnowledge({ wsId, isAdmin }: { wsId: string; isAdmin: boolean }) {
  const { t } = useTranslation("workspace")
  const qc = useQueryClient()
  const { data: groups, isLoading } = useWorkspaceServiceGroups(wsId)
  const { data: myServices } = useMyServices()
  const link = useLinkServiceFlexible()
  const unlinkSvc = useUnlinkServiceFlexible()
  const createSvc = useCreateService()
  const deleteProject = useDeleteProject()
  const { data: wsProjects } = useProjects(wsId)
  const [renameTarget, setRenameTarget] = useState<Project | null>(null)

  const [addOpenFor, setAddOpenFor] = useState<string | null>(null)
  const [addMode, setAddMode] = useState<"picker" | "create">("picker")
  const [newSvcId, setNewSvcId] = useState("")
  const [newLabel, setNewLabel] = useState("")
  const [confirmRemoveSvc, setConfirmRemoveSvc] = useState<{ projectId: string; refId: string; serviceId: string } | null>(null)
  const [confirmDeleteProject, setConfirmDeleteProject] = useState<{ projectId: string; projectName: string; svcCount: number } | null>(null)

  const { data: wsRegistry } = useWsRegistryList(wsId)

  // FE-8.7: opsi picker gabungan — library pribadi + registry workspace (milik siapa pun)
  interface PickOption {
    key: string
    serviceId: string
    label?: string
    source: "library" | "registry"
    libraryId?: string
    registryId?: string
  }
  const pickOptions: PickOption[] = useMemo(() => {
    if (!addOpenFor) return []
    const linkedHere = new Set(
      groups?.find((g) => g.projectId === addOpenFor)?.services.map((x) => x.libraryServiceId) ?? [],
    )
    const linkedSvcIds = new Set(
      groups?.find((g) => g.projectId === addOpenFor)?.services.map((x) => x.serviceId) ?? [],
    )
    const out: PickOption[] = []
    for (const sv of myServices ?? []) {
      if (!linkedHere.has(sv.id)) {
        out.push({ key: `lib-${sv.id}`, serviceId: sv.serviceId, label: sv.label, source: "library", libraryId: sv.id })
      }
    }
    for (const r of wsRegistry ?? []) {
      if (linkedSvcIds.has(r.service_id)) continue
      if (out.some((o) => o.serviceId === r.service_id)) continue // sudah ditawarkan lewat library
      out.push({ key: `reg-${r.registry_id}`, serviceId: r.service_id, label: r.label, source: "registry", registryId: r.registry_id })
    }
    return out
  }, [groups, myServices, wsRegistry, addOpenFor])

  const linkableFor = useMemo(() => {
    if (!addOpenFor) return []
    const linked = new Set(
      groups?.find((g) => g.projectId === addOpenFor)?.services.map((s) => s.libraryServiceId) ?? [],
    )
    return (myServices ?? []).filter((s) => !linked.has(s.id))
  }, [groups, myServices, addOpenFor])

  useEffect(() => {
    if (addOpenFor) setAddMode(linkableFor.length === 0 ? "create" : "picker")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addOpenFor])

  async function handlePick(option: PickOption) {
    if (!addOpenFor) return
    if (option.source === "library" && option.libraryId) {
      link.mutate(
        { projectId: addOpenFor, libraryServiceId: option.libraryId },
        { onSuccess: () => setAddOpenFor(null) },
      )
      return
    }
    // registry-asal: pastikan ada entri library milik saya, lalu link
    try {
      let libId: string | undefined = (myServices ?? []).find(
        (m) => m.serviceId === option.serviceId,
      )?.id
      if (!libId) {
        const { data } = await api.post("/services/library", {
          service_id: option.serviceId,
          label: option.label ?? "",
        })
        libId = data.id as string
        toast.success(t("services_knowledge.activated_toast", { id: option.serviceId }))
      }
      link.mutate(
        { projectId: addOpenFor, libraryServiceId: libId! },
        { onSuccess: () => setAddOpenFor(null) },
      )
    } catch (e) {
      toast.error(apiErrorMessage(e, t("services_knowledge.prepare_failed")))
    }
  }

  function closeAddDialog() {
    setAddOpenFor(null)
    setNewSvcId("")
    setNewLabel("")
  }

  return (
    <div>
      <div className="mb-4">
        <p className="text-sm text-muted-foreground">
          <span dangerouslySetInnerHTML={{ __html: t("services_knowledge.intro") }} />
        </p>
      </div>

      {isLoading ? (
        <Skeleton className="h-24 w-full rounded-lg" />
      ) : !groups || groups.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-xs text-muted-foreground">
          {t("services_knowledge.no_projects")}
        </p>
      ) : (
        <div className="space-y-3">
          {groups.map((g) => (
            <div key={g.projectId} className="rounded-lg border">
              <div className="flex flex-wrap items-center justify-between gap-1 border-b px-3 py-2">
                <p className="text-xs font-semibold">{g.projectName}</p>
                {isAdmin && (
                  <div className="flex items-center gap-1">
                    <Button size="sm" variant="ghost" className="h-6 gap-1 px-2 text-[11px]"
                      onClick={() => setAddOpenFor(g.projectId)}>
                      <Link2 className="size-3" /> {t("services_knowledge.add_service")}
                    </Button>
                    <Button size="sm" variant="ghost" className="h-6 gap-1 px-2 text-[11px]"
                      title={t("page.rename_project")}
                      onClick={() => {
                        const proj = wsProjects?.find((p) => p.id === g.projectId) ?? null
                        setRenameTarget(proj)
                      }}>
                      <Pencil className="size-3" /> {t("services_knowledge.rename")}
                    </Button>
                    <Button size="sm" variant="ghost"
                      className="h-6 gap-1 px-2 text-[11px] text-destructive hover:text-destructive"
                      onClick={() => setConfirmDeleteProject({
                        projectId: g.projectId,
                        projectName: g.projectName,
                        svcCount: g.services.length,
                      })}>
                      {t("services_knowledge.delete_project")}
                    </Button>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5 px-3 py-2.5">
                {g.services.length === 0 ? (
                  <span className="text-xs text-muted-foreground">{t("services_knowledge.no_services")}</span>
                ) : (
                  g.services.map((ref) => (
                    <Badge key={ref.id} variant="secondary" className="gap-1 font-mono text-[11px]"
                      title={ref.description || ref.label || ref.serviceId}>
                      <Boxes className="size-3 opacity-60" />
                      {ref.serviceId}
                      {isAdmin && (
                        <button className="rounded-full hover:bg-destructive/15 hover:text-destructive"
                          title={t("services_knowledge.unlink_service")}
                          onClick={() => setConfirmRemoveSvc({ projectId: g.projectId, refId: ref.id, serviceId: ref.serviceId })}>
                          <X className="size-3" />
                        </button>
                      )}
                    </Badge>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* __DIALOGS__ */}

      {/* Tambah service: picker / buat baru */}
      <Dialog open={!!addOpenFor} onOpenChange={(o) => { if (!o) closeAddDialog() }}>
        <DialogContent className="max-w-md overflow-y-auto max-h-[88vh]">
          <DialogHeader>
            <DialogTitle>{t("services_knowledge.dialog_title")}</DialogTitle>
            <DialogDescription>{t("services_knowledge.dialog_description")}</DialogDescription>
          </DialogHeader>

          <div className="flex rounded-md border p-0.5 text-xs">
            {(["picker", "create"] as const).map((m) => (
              <button key={m} type="button"
                className={cn(
                  "flex-1 rounded px-2 py-1 transition-colors",
                  addMode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                )}
                onClick={() => setAddMode(m)}>
                {m === "picker" ? t("services_knowledge.mode_picker") : t("services_knowledge.mode_create")}
              </button>
            ))}
          </div>

          {addMode === "picker" ? (
            pickOptions.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                {t("services_knowledge.picker_empty")}
              </p>
            ) : (
              <div className="max-h-64 space-y-1 overflow-y-auto">
                {pickOptions.map((opt) => (
                  <button key={opt.key}
                    className="flex w-full items-center gap-2 rounded-lg border px-3 py-1.5 text-left hover:bg-accent disabled:opacity-50"
                    disabled={link.isPending}
                    onClick={() => handlePick(opt)}>
                    <Boxes className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">{opt.serviceId}</span>
                    <Badge variant="outline" className="shrink-0 text-[9px]">
                      {opt.source === "registry" ? t("services_knowledge.badge_registry") : t("services_knowledge.badge_library")}
                    </Badge>
                  </button>
                ))}
              </div>
            )
          ) : (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs">{t("services_knowledge.service_id_label")}</Label>
                <Input
                  className="h-9 font-mono text-xs"
                  placeholder="your-service-name"
                  value={newSvcId}
                  onChange={(e) =>
                    setNewSvcId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))
                  }
                />
                <p className="text-[11px] text-muted-foreground">
                  {t("services_knowledge.service_id_hint")}
                </p>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">{t("services_knowledge.label_optional")}</Label>
                <Input className="h-8 text-xs" placeholder={t("services_knowledge.label_placeholder")}
                  value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
              </div>
              <Button
                size="sm"
                className="w-full"
                disabled={createSvc.isPending || link.isPending || newSvcId.trim().length < 2}
                onClick={() => {
                  createSvc.mutate(
                    {
                      service_id: newSvcId.trim(),
                      label: newLabel.trim(),
                    },
                    {
                    onSuccess: (created) => {
                      // Auto-register the new service into the workspace registry
                      // (mirror library → registry) so it also appears in the Services
                      // tab hierarchy. Best-effort: a duplicate service_id is ignored.
                      api
                        .post(`/config/workspaces/${wsId}/service-registry`, {
                          service_id: created.serviceId,
                          label: created.label ?? newLabel.trim(),
                        })
                        .then(() =>
                          qc.invalidateQueries({ queryKey: ["config", "ws-registry", wsId] }),
                        )
                        .catch(() => {
                          // Already registered (or not permitted) — service still works
                          // via its library entry, so this is non-fatal.
                        })
                      link.mutate(
                          { projectId: addOpenFor!, libraryServiceId: created.id },
                          {
                            onSuccess: () => {
                              toast.success(t("services_knowledge.created_linked_toast", { id: created.serviceId }))
                              closeAddDialog()
                            },
                            onError: () => {
                              toast.info(t("services_knowledge.saved_unlinked_toast"))
                              closeAddDialog()
                            },
                          },
                        )
                      },
                      onError: (e) => toast.error(apiErrorMessage(e)),
                    },
                  )
                }}
              >
                {createSvc.isPending || link.isPending ? t("services_knowledge.saving") : t("services_knowledge.submit_create_link")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Lepas service dari project */}
      <AlertDialog open={!!confirmRemoveSvc} onOpenChange={(o) => !o && setConfirmRemoveSvc(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("services_knowledge.unlink_title", { id: confirmRemoveSvc?.serviceId ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("services_knowledge.unlink_description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmRemoveSvc) unlinkSvc.mutate(confirmRemoveSvc)
                setConfirmRemoveSvc(null)
              }}
            >
              {t("services_knowledge.unlink_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Rename project */}
      <RenameProjectDialog
        workspaceId={wsId}
        project={renameTarget}
        open={!!renameTarget}
        onOpenChange={(open) => !open && setRenameTarget(null)}
      />

      {/* Soft-delete project */}
      <AlertDialog open={!!confirmDeleteProject} onOpenChange={(o) => !o && setConfirmDeleteProject(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("services_knowledge.delete_title", { name: confirmDeleteProject?.projectName ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              • {t("services_knowledge.delete_bullet_services", { count: confirmDeleteProject?.svcCount ?? 0 })}
              <br />• {t("services_knowledge.delete_bullet_archive")}
              <br />• {t("services_knowledge.delete_bullet_slug")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteProject.isPending}
              onClick={() => {
                if (confirmDeleteProject)
                  deleteProject.mutate(
                    { wsId, projectId: confirmDeleteProject.projectId },
                    {
                      onSuccess: () => {
                        if (window.location.pathname.includes(confirmDeleteProject.projectId)) {
                          window.location.assign("/")
                        }
                      },
                    },
                  )
                setConfirmDeleteProject(null)
              }}
            >
              {t("services_knowledge.delete_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
