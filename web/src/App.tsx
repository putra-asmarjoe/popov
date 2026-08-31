import type { ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import { TooltipProvider } from "@/components/ui/tooltip"
import { AppShell } from "@/components/layout/AppShell"
import { LoginPage } from "@/pages/LoginPage"
import { WorkspacesPage } from "@/pages/WorkspacesPage"
import { WorkspaceSettingsPage } from "@/pages/WorkspaceSettingsPage"
import { ProjectPage } from "@/pages/ProjectPage"
import { NewTicketPage } from "@/pages/NewTicketPage"
import { NotificationsPage } from "@/pages/NotificationsPage"
import { ProjectOverview } from "@/pages/ProjectOverview"
import { ProjectChatPage } from "@/pages/ProjectChatPage"
import { ManagementPage } from "@/pages/management/ManagementPage"
import { useAuth } from "@/hooks/useAuth"
import { useWorkspaces } from "@/hooks/useWorkspaces"
import { useWorkspaceStore } from "@/store/workspace.store"
import { useParams } from "react-router-dom"

/** Fix G2: `/w/:ws/chats` tanpa id → workspace (kalau tidak, tertelan `:projSlug`). */
function ChatsRedirect() {
  const { wsSlug = "" } = useParams()
  return <Navigate to={`/w/${wsSlug}`} replace />
}

/** Guard: tunggu session check, redirect ke /login bila belum auth. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, sessionChecked } = useAuth()
  if (!sessionChecked) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        Memuat sesi…
      </div>
    )
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

/**
 * `/` → workspace terakhir (localStorage) atau workspace pertama.
 * GET /workspaces menjamin minimal 1 workspace (auto-create).
 */
function RootRedirect() {
  const { data: workspaces, isLoading } = useWorkspaces()
  const lastSlugs = useWorkspaceStore((s) => s.lastSlugs)

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Memuat workspace…
      </div>
    )
  }
  const { workspaceSlug } = lastSlugs()
  const target =
    workspaces?.find((w) => w.slug === workspaceSlug) ?? workspaces?.[0] ?? null
  if (!target) return <Navigate to="/login" replace />
  return <Navigate to={`/w/${target.slug}`} replace />
}

export default function App() {
  return (
    <TooltipProvider delayDuration={200}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/" element={<RootRedirect />} />
          <Route path="/w/:wsSlug" element={<WorkspacesPage />} />
          <Route path="/w/:wsSlug/settings" element={<WorkspaceSettingsPage />} />
          <Route path="/w/:wsSlug/chats" element={<ChatsRedirect />} />
          <Route path="/w/:wsSlug/chats/:sessionId" element={<ProjectChatPage />} />
          <Route path="/w/:wsSlug/:projSlug" element={<ProjectPage />} />
          <Route path="/w/:wsSlug/:projSlug/overview" element={<ProjectOverview />} />
          <Route path="/w/:wsSlug/:projSlug/new" element={<NewTicketPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/management" element={<ManagementPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </TooltipProvider>
  )
}
