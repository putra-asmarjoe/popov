import { Link, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ChevronsUpDown, LogOut, FolderKanban } from "lucide-react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { NotifDropdown } from "@/components/layout/NotifDropdown"
import { ThemeSwitcher } from "@/components/ui/theme-switcher"
import { LocaleSwitcher } from "@/components/ui/locale-switcher"
import { useAuth } from "@/hooks/useAuth"
import { useProjects, useWorkspaces } from "@/hooks/useWorkspaces"
import { useWorkspaceStore } from "@/store/workspace.store"

/**
 * Topbar — project switcher (dari workspace aktif) + user menu.
 * Fallback ke workspace pertama bila store belum terhidrasi (mis. direct URL).
 * Notifikasi bell ditambahkan di FE-4.
 */
export function Topbar() {
  const { t } = useTranslation("common")
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { data: workspaces } = useWorkspaces()
  const { activeWorkspace, activeProject } = useWorkspaceStore()
  const workspace = activeWorkspace ?? workspaces?.[0] ?? null
  const { data: projects } = useProjects(workspace?.id ?? null)

  const initials = (user?.name ?? "?")
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-4">
      {/* Project switcher */}
      {workspace ? (
        <DropdownMenu>
          <DropdownMenuTrigger className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none hover:bg-muted">
            {activeProject ? (
              <>
                <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-xs font-semibold text-primary">
                  {activeProject.key}
                </span>
                <span className="max-w-40 truncate font-medium">{activeProject.name}</span>
              </>
            ) : (
              <span className="text-muted-foreground">{t("nav.pick_project")}</span>
            )}
            <ChevronsUpDown className="size-3.5 text-muted-foreground" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            <DropdownMenuLabel>Project · {workspace.name}</DropdownMenuLabel>
            {projects?.map((p) => (
              <DropdownMenuItem key={p.id} onClick={() => navigate(`/w/${workspace.slug}/${p.slug}`)}>
                <span className="w-9 shrink-0 rounded bg-muted px-1 py-0.5 text-center font-mono text-[10px] font-semibold">
                  {p.key}
                </span>
                <span className="truncate">{p.name}</span>
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to={`/w/${workspace.slug}`}>
                <FolderKanban className="size-4" /> {t("nav.all_projects")}
              </Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <div className="flex items-center gap-1.5 md:hidden">
          <img
            src="/logo-48.png"
            alt="Popov logo"
            className="size-5 rounded object-contain"
            draggable={false}
          />
          <span className="text-sm font-semibold">Popov</span>
        </div>
      )}

      <div className="ml-auto flex items-center gap-2">
        <LocaleSwitcher />
        <ThemeSwitcher />
        <NotifDropdown />
        <DropdownMenu>
          <DropdownMenuTrigger className="cursor-pointer rounded-full outline-none ring-ring focus-visible:ring-2">
            <Avatar className="size-8">
              <AvatarFallback className="text-xs">{initials}</AvatarFallback>
            </Avatar>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>
              <div className="flex flex-col">
                <span className="text-sm font-medium">{user?.name}</span>
                <span className="text-xs font-normal text-muted-foreground">{user?.email}</span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="gap-2">
              {t("nav.role")}
              <Badge variant="secondary" className="ml-auto capitalize">
                {user?.role}
              </Badge>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              className="gap-2"
              onClick={() => {
                logout()
                navigate("/login", { replace: true })
              }}
            >
              <LogOut className="size-4" /> {t("nav.logout")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
