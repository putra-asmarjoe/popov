import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { Link, useNavigate, useParams } from "react-router-dom"
import { FolderKanban, MoreVertical, Pencil, Plus, Settings, Users } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { CreateProjectDialog } from "@/components/workspace/CreateProjectDialog"
import { OnboardingChecklist } from "@/components/workspace/OnboardingChecklist"
import { RenameProjectDialog } from "@/components/workspace/RenameProjectDialog"
import type { Project } from "@/types/workspace"
import { useAuth } from "@/hooks/useAuth"
import { useProjects, useWorkspaceDetail, useWorkspaces } from "@/hooks/useWorkspaces"
import { formatDate } from "@/lib/utils"
import { useWorkspaceStore } from "@/store/workspace.store"

/**
 * WorkspacesPage (/w/:wsSlug) — daftar project dalam workspace.
 * Entry utama setelah login; klik project → ProjectPage.
 */
export function WorkspacesPage() {
  const { t } = useTranslation("workspace")
  const { wsSlug } = useParams<{ wsSlug: string }>()
  const navigate = useNavigate()
  const { data: workspaces, isLoading: wsLoading } = useWorkspaces()
  const { setActiveWorkspace } = useWorkspaceStore()
  const { user: me } = useAuth()
  const [createOpen, setCreateOpen] = useState(false)
  // Sumber dialog create-project — menentukan redirect pasca-create:
  // dari checklist → bawa from=onboarding agar strip "kembali" tampil di project page.
  const [createViaChecklist, setCreateViaChecklist] = useState(false)
  const [renameTarget, setRenameTarget] = useState<Project | null>(null)

  const workspace = useMemo(
    () => workspaces?.find((w) => w.slug === wsSlug) ?? null,
    [workspaces, wsSlug],
  )
  const { data: projects, isLoading: projLoading } = useProjects(workspace?.id ?? null)
  const { data: wsDetail } = useWorkspaceDetail(workspace?.id ?? null)
  // Rename project = aksi admin workspace (sama dengan aturan endpoint PATCH)
  const isAdmin =
    wsDetail?.isOwner === true ||
    wsDetail?.members.find((m) => m.userId === me?.id)?.wsRole === "admin"

  // Sinkronkan workspace aktif ke store (untuk Sidebar/Topbar)
  useEffect(() => {
    if (workspace) setActiveWorkspace(workspace)
  }, [workspace, setActiveWorkspace])

  // Loading selesai tapi slug tidak dikenal → tampil not-found
  if (!wsLoading && !workspace) {
    return (
      <div className="p-8">
        <div className="mx-auto max-w-md rounded-lg border border-dashed p-8 text-center">
          <p className="text-sm font-medium">{t("page.not_found")}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t("page.not_found_hint")}</p>
          <Button asChild variant="outline" size="sm" className="mt-4">
            <Link to="/">{t("page.go_first_workspace")}</Link>
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl p-6 md:p-8">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        {wsLoading || !workspace ? (
          <Skeleton className="h-8 w-56" />
        ) : (
          <>
            <h1 className="text-xl font-semibold tracking-tight">{workspace.name}</h1>
            <Badge variant="secondary" className="gap-1">
              <Users className="size-3" /> {t("page.member_count", { count: workspace.memberCount })}
            </Badge>
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button asChild variant="ghost" size="sm" disabled={!workspace}>
            <Link to={`/w/${wsSlug}/settings`}>
              <Settings className="size-4" /> {t("nav.settings", { ns: "common" })}
            </Link>
          </Button>
          <Button size="sm" disabled={!workspace} onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" /> {t("page.new_project")}
          </Button>
        </div>
      </div>

      {/* Onboarding checklist — auto-centang dari data nyata, dismiss per-user */}
      <OnboardingChecklist
        wsSlug={wsSlug ?? ""}
        workspaceId={workspace?.id ?? null}
        onCreateProject={() => {
          setCreateViaChecklist(true)
          setCreateOpen(true)
        }}
      />

      {/* Grid project */}
      <div className="mt-6">
        {projLoading || wsLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-28 w-full rounded-xl" />
            ))}
          </div>
        ) : projects && projects.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <Card
                key={project.id}
                className="group cursor-pointer p-5 transition-colors hover:border-primary/50 hover:bg-muted/40"
                onClick={() => navigate(`/w/${wsSlug}/${project.slug}`)}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="rounded-md bg-primary/10 px-2 py-1 font-mono text-xs font-semibold text-primary">
                    {project.key}
                  </span>
                  <div className="flex items-center gap-1">
                    {isAdmin && (
                      <DropdownMenu>
                        {/* stopPropagation: klik menu jangan memicu navigasi kartu */}
                        <div onClick={(e) => e.stopPropagation()}>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 data-[state=open]:opacity-100"
                              aria-label={t("page.project_menu", { name: project.name })}
                            >
                              <MoreVertical className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => setRenameTarget(project)}>
                              <Pencil className="size-3.5" /> {t("page.rename_project")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </div>
                      </DropdownMenu>
                    )}
                    <FolderKanban className="size-4 text-muted-foreground" />
                  </div>
                </div>
                <p className="mt-3 font-medium leading-tight">{project.name}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("page.created_at", { date: formatDate(project.createdAt) })}
                </p>
              </Card>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed p-10 text-center">
            <FolderKanban className="mx-auto size-8 text-muted-foreground/60" />
            <p className="mt-3 text-sm font-medium">{t("page.empty_title")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("page.empty_hint")}
            </p>
            <Button size="sm" className="mt-4" onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" /> {t("page.new_project")}
            </Button>
          </div>
        )}
      </div>

      <CreateProjectDialog
        workspaceId={workspace?.id ?? null}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(projSlug) =>
          navigate(
            `/w/${wsSlug}/${projSlug}${createViaChecklist ? "?from=onboarding" : ""}`,
          )
        }
      />

      <RenameProjectDialog
        workspaceId={workspace?.id ?? null}
        project={renameTarget}
        open={!!renameTarget}
        onOpenChange={(open) => !open && setRenameTarget(null)}
      />
    </div>
  )
}
