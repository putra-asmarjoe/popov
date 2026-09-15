import type { ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { TooltipProvider } from "@/components/ui/tooltip"
import { AppShell } from "@/components/layout/AppShell"
import { LoginPage } from "@/pages/LoginPage"
import { WorkspacesPage } from "@/pages/WorkspacesPage"
import { WorkspaceSettingsPage } from "@/pages/WorkspaceSettingsPage"
import { ProjectPage } from "@/pages/ProjectPage"
import { NewTicketPage } from "@/pages/NewTicketPage"
import { NotificationsPage } from "@/pages/NotificationsPage"
import { AccountPreferencesPage } from "@/pages/AccountPreferencesPage"
import { ProjectOverview } from "@/pages/ProjectOverview"
import { ProjectChatPage } from "@/pages/ProjectChatPage"
import { ManagementPage } from "@/pages/management/ManagementPage"
import { useAuth } from "@/hooks/useAuth"
import { useWorkspaces } from "@/hooks/useWorkspaces"
import { useSetupStatus } from "@/hooks/useSetupStatus"
import { SetupWizard } from "@/pages/SetupWizard"
import { SetupErrorScreen } from "@/pages/SetupErrorScreen"
import { useWorkspaceStore } from "@/store/workspace.store"
import { useParams } from "react-router-dom"

/** Fix G2: `/w/:ws/chats` tanpa id → workspace (kalau tidak, tertelan `:projSlug`). */
function ChatsRedirect() {
  const { wsSlug = "" } = useParams()
  return <Navigate to={`/w/${wsSlug}`} replace />
}

/** Guard: tunggu session check, redirect ke /login bila belum auth. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { t } = useTranslation("common")
  const { isAuthenticated, sessionChecked } = useAuth()
  if (!sessionChecked) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        {t("status.loading")}
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
  const { t } = useTranslation("common")
  const { data: workspaces, isLoading } = useWorkspaces()
  const lastSlugs = useWorkspaceStore((s) => s.lastSlugs)

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("status.loading")}
      </div>
    )
  }
  const { workspaceSlug } = lastSlugs()
  const target =
    workspaces?.find((w) => w.slug === workspaceSlug) ?? workspaces?.[0] ?? null
  if (!target) return <Navigate to="/login" replace />
  return <Navigate to={`/w/${target.slug}`} replace />
}

/**
 * Fix #294: SetupGate — intercept sebelum router. 3-tier logic:
 * 1. Server unreachable → error screen (fallback)
 * 2. .env missing/invalid → configure form (fill → write .env → reload)
 * 3. .env valid, no admin user → wizard starting from admin step
 * 4. Everything ready → normal app
 */
function SetupGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation("common")
  const { data: setup, isLoading, isError, refetch } = useSetupStatus()

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        {t("status.loading")}
      </div>
    )
  }
  if (isError || !setup) {
    return <SetupErrorScreen kind="unreachable" status={null} onRetry={() => void refetch()} />
  }
  // Tier 2: .env missing/invalid — show configure form
  if (setup.needs_configuration) {
    return <SetupWizard status={setup} initialStep="configure" />
  }
  // Tier 3: .env valid, no admin user — skip configure, start from admin
  if (setup.needs_setup) {
    return <SetupWizard status={setup} initialStep="admin" />
  }
  // Tier 4: everything ready
  return <>{children}</>
}

export default function App() {
  return (
    <TooltipProvider delayDuration={200}>
      <SetupGate>
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
          <Route path="/account/preferences" element={<AccountPreferencesPage />} />
          <Route path="/management" element={<ManagementPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
        </Routes>
      </SetupGate>
    </TooltipProvider>
  )
}
