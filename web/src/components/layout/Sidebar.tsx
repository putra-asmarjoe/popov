import { useEffect, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import {
  ChevronsUpDown,
  Plus,
  Settings,
  Settings2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { CreateProjectDialog } from "@/components/workspace/CreateProjectDialog"
import { CreateWorkspaceDialog } from "@/components/workspace/CreateWorkspaceDialog"
import { useAuth } from "@/hooks/useAuth"
import { useProjects, useWorkspaces } from "@/hooks/useWorkspaces"
import { cn } from "@/lib/utils"
import { useWorkspaceStore } from "@/store/workspace.store"

/**
 * Sidebar — workspace switcher + daftar project workspace aktif.
 * Management (FE-6) tampil untuk admin global.
 */
export function Sidebar({ className }: { className?: string }) {
  const { t } = useTranslation("common")
  const location = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"
  const { data: workspaces, isLoading } = useWorkspaces()
  const { activeWorkspace, setActiveWorkspace } = useWorkspaceStore()
  const [projectDialogOpen, setProjectDialogOpen] = useState(false)
  const [wsDialogOpen, setWsDialogOpen] = useState(false)

  const current = activeWorkspace ?? workspaces?.[0] ?? null

  // Fix: direct-load ke /management dkk — store kosong → auto-pilih workspace pertama
  // agar query project jalan (dulu pakai activeWorkspace?.id sehingga list project hilang).
  useEffect(() => {
    if (!activeWorkspace && workspaces && workspaces.length > 0) {
      setActiveWorkspace(workspaces[0])
    }
  }, [activeWorkspace, workspaces, setActiveWorkspace])
  const { data: projects } = useProjects(current?.id ?? null)

  return (
    <aside
      className={cn(
        "flex w-60 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground",
        className,
      )}
    >
      {/* Workspace switcher */}
      <div className="border-b border-sidebar-border p-2">
        <DropdownMenu>
          <DropdownMenuTrigger className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm outline-none hover:bg-sidebar-accent/60">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sidebar-primary text-sm font-bold text-sidebar-primary-foreground">
              {(current?.name ?? "P").charAt(0).toUpperCase()}
            </div>
            <span className="min-w-0 flex-1 truncate text-left font-medium">
              {current?.name ?? (isLoading ? t("status.loading") : "Popov")}
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-sidebar-foreground/60" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuLabel>{t("sidebar.workspace_label")}</DropdownMenuLabel>
            {workspaces?.map((ws) => (
              <DropdownMenuItem
                key={ws.id}
                onClick={() => {
                  setActiveWorkspace(ws)
                  navigate(`/w/${ws.slug}`)
                }}
                className={cn(ws.id === current?.id && "font-medium")}
              >
                <span className="truncate">{ws.name}</span>
                {ws.id === current?.id && <span className="ml-auto text-xs text-muted-foreground">✓</span>}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => setWsDialogOpen(true)}>
              <Plus className="size-4" /> {t("sidebar.new_workspace")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Projects */}
      <div className="flex-1 overflow-y-auto p-2">
        <div className="flex items-center justify-between px-2 pb-1 pt-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/50">
            {t("sidebar.projects")}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="size-5 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground"
            disabled={!current}
            onClick={() => setProjectDialogOpen(true)}
            title={t("sidebar.new_project")}
          >
            <Plus className="size-3.5" />
          </Button>
        </div>

        {isLoading ? (
          <div className="space-y-1 p-1">
            <Skeleton className="h-7 w-full bg-sidebar-accent/50" />
            <Skeleton className="h-7 w-3/4 bg-sidebar-accent/50" />
          </div>
        ) : projects && projects.length > 0 ? (
          <nav className="space-y-0.5">
            {projects.map((project) => {
              const href = `/w/${current?.slug}/${project.slug}`
              const active = location.pathname === href
              return (
                <Link
                  key={project.id}
                  to={href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                    active
                      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                  )}
                >
                  <span className="w-9 shrink-0 rounded bg-sidebar-primary/20 px-1 py-0.5 text-center font-mono text-[10px] font-semibold text-sidebar-primary-foreground/90">
                    {project.key}
                  </span>
                  <span className="truncate">{project.name}</span>
                </Link>
              )
            })}
          </nav>
        ) : (
          <p className="px-2 py-2 text-xs text-sidebar-foreground/50">
            {t("sidebar.empty_projects")}
          </p>
        )}
      </div>

      {/* Bottom nav */}
      <nav className="space-y-0.5 border-t border-sidebar-border p-2 text-sm">
        {current && (
          <Link
            to={`/w/${current.slug}/settings`}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
              location.pathname.endsWith("/settings") &&
                "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
            )}
          >
            <Settings className="size-4" /> {t("sidebar.workspace_settings")}
          </Link>
        )}
        {isAdmin ? (
          <Link
            to="/management"
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
              location.pathname.startsWith("/management") &&
                "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
            )}
          >
            <Settings2 className="size-4" /> Management
          </Link>
        ) : (
          <SidebarItemPlaceholder icon={<Settings2 className="size-4" />} label={t("nav.management")} hint="admin" />
        )}
        <div className="px-2.5 pb-1 pt-2 text-[10px] text-sidebar-foreground/40">
          Popov - Incident Response Agent v{__APP_VERSION__}
        </div>
      </nav>

      <CreateProjectDialog
        workspaceId={current?.id ?? null}
        open={projectDialogOpen}
        onOpenChange={setProjectDialogOpen}
        onCreated={(projSlug) => current && navigate(`/w/${current.slug}/${projSlug}`)}
      />
      <CreateWorkspaceDialog
        open={wsDialogOpen}
        onOpenChange={setWsDialogOpen}
        onCreated={(slug) => navigate(`/w/${slug}`)}
      />
    </aside>
  )
}

function SidebarItemPlaceholder({
  icon,
  label,
  hint,
}: {
  icon: React.ReactNode
  label: string
  hint: string
}) {
  const { t } = useTranslation("common")
  return (
    <div
      className="flex cursor-not-allowed items-center gap-2.5 rounded-md px-2.5 py-2 text-sidebar-foreground/40"
      title={t("sidebar.phase_hint", { phase: hint })}
    >
      {icon}
      <span>{label}</span>
      <span className="ml-auto text-[10px]">{hint}</span>
    </div>
  )
}
