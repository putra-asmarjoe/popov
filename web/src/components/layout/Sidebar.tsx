import { useEffect, useMemo, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import {
  ChevronsUpDown,
  Loader2,
  MessageSquare,
  MoreVertical,
  Plus,
  Settings,
  Settings2,
  Trash2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
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
import {
  useChatSessions,
  useCreateChatSession,
  useDeleteChatSession,
} from "@/hooks/useChatStream"
import type { ChatSession } from "@/types/chat"
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

  // ── Chat by Project: daftar sesi chat project (flat, max 5 terbaru) ───────
  const { t: tChat } = useTranslation("pchat")
  const { data: allSessions } = useChatSessions(null, 100) // Fix G1: limit 20 default bisa menyingkirkan sesi project oleh sesi tiket
  const createSession = useCreateChatSession(null)
  const deleteSession = useDeleteChatSession()
  const [chatPickerOpen, setChatPickerOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<{ id: string; title: string } | null>(null)

  const projectById = useMemo(() => {
    const map = new Map<string, { key: string; name: string; slug: string }>()
    for (const p of projects ?? []) map.set(p.id, p)
    return map
  }, [projects])

  const projectChats = useMemo(() => {
    return (allSessions ?? [])
      .filter((s: ChatSession) => s.projectId && !s.ticketId)
      .sort((a, b) => (b.updatedAt ?? "").localeCompare(a.updatedAt ?? ""))
      .slice(0, 5)
  }, [allSessions])


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

        {/* ── Chat by Project: daftar sesi + tombol baru ── */}
        <div className="mt-3 border-t border-sidebar-border pt-2">
          <div className="flex items-center justify-between px-2 pb-1 pt-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/50">
              {tChat("sidebar_title")}
            </span>
            <DropdownMenu open={chatPickerOpen} onOpenChange={setChatPickerOpen}>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-5 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                  disabled={!current || (projects?.length ?? 0) === 0}
                  title={tChat("new_chat")}
                >
                  <Plus className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-52">
                <DropdownMenuLabel>{tChat("pick_project")}</DropdownMenuLabel>
                {(projects ?? []).map((p) => (
                  <DropdownMenuItem
                    key={p.id}
                    onClick={() =>
                      createSession.mutate(
                        { projectId: p.id, title: "" },
                        {
                          onSuccess: (session) =>
                            navigate(`/w/${current?.slug}/chats/${session.id}`),
                        },
                      )
                    }
                  >
                    <span className="w-9 shrink-0 rounded bg-sidebar-primary/20 px-1 py-0.5 text-center font-mono text-[10px] font-semibold text-sidebar-primary-foreground/90">
                      {p.key}
                    </span>
                    <span className="truncate">{p.name}</span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {projectChats.length > 0 ? (
            <nav className="space-y-0.5">
              {projectChats.map((s) => {
                const proj = s.projectId ? projectById.get(s.projectId) : undefined
                const href = `/w/${current?.slug}/chats/${s.id}`
                const active = location.pathname === href
                return (
                  <div
                    key={s.id}
                    className={cn(
                      "group/chat relative flex items-center gap-1 rounded-md",
                      active
                        ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                        : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                    )}
                  >
                    <Link
                      to={href}
                      title={s.title}
                      className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-sm"
                    >
                      <MessageSquare className="size-3.5 shrink-0 text-sidebar-foreground/50" />
                      <span className="min-w-0 flex-1 truncate">{s.title}</span>
                      {proj && (
                        <span className="shrink-0 rounded bg-sidebar-primary/20 px-1 py-0.5 text-center font-mono text-[10px] font-semibold text-sidebar-primary-foreground/90">
                          {proj.key}
                        </span>
                      )}
                    </Link>
                    {/* Fix #118: three-dots per sesi project (bukan tiket) → soft-delete */}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-6 opacity-0 transition-opacity group-hover/chat:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
                          aria-label={tChat("delete_session_aria")}
                          onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()
                          }}
                        >
                          <MoreVertical className="size-3.5" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="z-[70] w-44">
                        <DropdownMenuItem
                          className="whitespace-nowrap text-destructive focus:text-destructive"
                          onSelect={(e) => {
                            e.preventDefault()
                            setConfirmDelete({ id: s.id, title: s.title })
                          }}
                        >
                          <Trash2 className="size-4" /> {tChat("delete_session")}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                )
              })}
            </nav>
          ) : (
            <p className="px-2 py-2 text-xs text-sidebar-foreground/50">{tChat("sidebar_empty")}</p>
          )}
        </div>
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

      {/* Fix #118: konfirmasi hapus sesi chat project (paritas Fix #95). */}
      <AlertDialog
        open={confirmDelete !== null}
        onOpenChange={(o) => !o && setConfirmDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{tChat("delete_confirm_title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {tChat("delete_confirm_description", { title: confirmDelete?.title ?? "" })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteSession.isPending}>
              {tChat("delete_confirm_cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteSession.isPending || !confirmDelete}
              onClick={() => {
                if (!confirmDelete) return
                const targetId = confirmDelete.id
                deleteSession.mutate(targetId, {
                  onSuccess: () => {
                    // Redirect bila user sedang membuka sesi yang dihapus
                    if (location.pathname.includes(targetId)) {
                      navigate(`/w/${current?.slug ?? ""}`)
                    }
                    setConfirmDelete(null)
                  },
                  onError: () => setConfirmDelete(null),
                })
              }}
            >
              {deleteSession.isPending && (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              )}
              {tChat("delete_confirm_action")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
