import { useEffect, useMemo, useState } from "react"
import { Link, Navigate, useNavigate, useParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { TicketDetailChatPanel } from "@/components/ticket/TicketDetailChatPanel"
import { TicketFilters } from "@/components/ticket/TicketFilters"
import { TicketTable } from "@/components/ticket/TicketTable"
import { FloatingPanel } from "@/components/panel/FloatingPanel"
import { WarRoomPanel } from "@/components/warroom/WarRoomPanel"
import { ProjectViewToggle } from "@/components/project/ProjectViewToggle"
import { OnboardingBackStrip } from "@/components/workspace/OnboardingBackStrip"
import { WidgetDataProvider } from "@/components/overview/WidgetDataContext"
import { WidgetShell } from "@/components/overview/WidgetShell"
import { WidgetCustomize } from "@/components/overview/WidgetCustomize"
import { DashboardDaysFilter } from "@/components/overview/DashboardDaysFilter"
import { OVERVIEW_WIDGETS } from "@/lib/overview-widgets"
import { useTickets } from "@/hooks/useTickets"
import { useProjectOverview } from "@/hooks/useProjectOverview"
import { useTicketSelection } from "@/hooks/useTicketSelection"
import { useTicketRealtime } from "@/hooks/useWebSocket"
import { useProjects, useWorkspaces, useWorkspaceDetail } from "@/hooks/useWorkspaces"
import { getProjectView, setProjectView } from "@/lib/project-view"
import { useWidgetPrefs, widgetsNeedOverview, DASHBOARD_WIDGET_IDS } from "@/lib/overview-widgets"
import { useTicketStore } from "@/store/ticket.store"
import { useWorkspaceStore } from "@/store/workspace.store"

/**
 * ProjectPage (/w/:wsSlug/:projSlug) — HALAMAN UTAMA.
 * Ticket list selalu full-width (tidak terdorong panel). Panel kanan (Detail | Chat)
 * adalah FloatingPanel draggable + resizable (≥md) atau drawer (<md).
 * Tiket aktif disinkronkan lewat URL ?ticket=KEY-N (shareable + refresh-safe).
 */
export function ProjectPage() {
  const { t } = useTranslation("project")
  const { wsSlug, projSlug } = useParams<{ wsSlug: string; projSlug: string }>()
  const navigate = useNavigate()
  const { data: workspaces, isLoading: wsLoading } = useWorkspaces()
  const workspace = useMemo(
    () => workspaces?.find((w) => w.slug === wsSlug) ?? null,
    [workspaces, wsSlug],
  )
  const { data: projects, isLoading: projLoading } = useProjects(workspace?.id ?? null)
  const project = useMemo(
    () => projects?.find((p) => p.slug === projSlug) ?? null,
    [projects, projSlug],
  )
  const { data: wsDetail } = useWorkspaceDetail(workspace?.id ?? null)
  const members = wsDetail?.members ?? []

  const { setActiveWorkspace, setActiveProject } = useWorkspaceStore()
  const { filters } = useTicketStore()
  const [page, setPage] = useState(1)

  // Dashboard widgets — gated by widget prefs (classic view)
  const { enabled, update, reset } = useWidgetPrefs(project?.id ?? null, "classic")
  const hasDashboardWidget = enabled.some((id) => DASHBOARD_WIDGET_IDS.includes(id))

  // Days filter — persist in localStorage
  const [days, setDays] = useState(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("popov:dashboard-days")
      return saved ? parseInt(saved, 10) || 1 : 1
    }
    return 1
  })

  const handleDaysChange = (value: number) => {
    setDays(value)
    localStorage.setItem("popov:dashboard-days", String(value))
  }

  const needOverview = widgetsNeedOverview(enabled)
  const { data: overview } = useProjectOverview(
    needOverview ? project?.id ?? null : null,
    days,
  )

  // Reset halaman saat filter berubah
  useEffect(() => {
    setPage(1)
  }, [filters])

  const { data: ticketsData, isLoading } = useTickets(project?.id ?? null, filters, page)
  // FE-4: realtime update list tiket via WebSocket
  useTicketRealtime(project?.id)

  // Sinkronkan store workspace/project (Sidebar/Topbar/chat context FE-5)
  useEffect(() => {
    if (workspace) setActiveWorkspace(workspace)
  }, [workspace, setActiveWorkspace])
  useEffect(() => {
    if (project) setActiveProject(project)
  }, [project, setActiveProject])

  // Seleksi tiket + detail fresh — SATU fungsi utk classic & warroom (DRY).
  const {
    detailTicket,
    activeTicketId,
    isWarroom,
    hasTicketParam,
    openTicket,
    closeTicket,
    openWarroom,
    exitWarroom,
  } = useTicketSelection({
    tickets: ticketsData?.tickets ?? [],
    projectKey: project?.key ?? "",
  })

  if (!wsLoading && !workspace)
    return <NotFoundBlock message={t("page.workspace_not_found")} />
  if (!projLoading && workspace && !project)
    return <NotFoundBlock message={t("page.project_not_found")} />

  // Mode War Room (preferensi session, default warroom): main URL tanpa konteks
  // tiket → redirect ke /overview. Ada `?ticket` → tetap classic (workflow
  // detail/chat tidak boleh putus).
  if (
    !isWarroom &&
    getProjectView() === "warroom" &&
    !hasTicketParam &&
    workspace &&
    project
  ) {
    return <Navigate to={`/w/${wsSlug}/${projSlug}/overview`} replace />
  }

  // War Room mode: full-width, ganti split Detail|Chat. Back → chat normal.
  if (isWarroom && detailTicket) {
    return (
      <div className="h-full min-h-0">
        <WarRoomPanel
          ticket={detailTicket}
          onBack={exitWarroom}
        />
      </div>
    )
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 grid-rows-1">
      <div className="flex min-w-0 min-h-0 flex-col">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1.5 border-b px-4 py-3 text-sm">
          {workspace && project ? (
            <>
              <OnboardingBackStrip backTo={`/w/${wsSlug}`} />
              <div className="ml-auto flex items-center gap-2">
                <ProjectViewToggle
                  value="classic"
                  onChange={(v) => {
                    setProjectView(v)
                    if (v === "warroom") {
                      navigate(`/w/${wsSlug}/${projSlug}/overview`)
                    }
                  }}
                />
                <WidgetCustomize
                  enabled={enabled}
                  onToggle={(id) =>
                    update(
                      enabled.includes(id) ? enabled.filter((x) => x !== id) : [...enabled, id],
                    )
                  }
                  onMove={(id, dir) => {
                    const from = enabled.indexOf(id)
                    const to = from + dir
                    if (from < 0 || to < 0 || to >= enabled.length) return
                    const next = [...enabled]
                    ;[next[from], next[to]] = [next[to], next[from]]
                    update(next)
                  }}
                  onReset={reset}
                  widgets={OVERVIEW_WIDGETS.filter((w) => DASHBOARD_WIDGET_IDS.includes(w.id))}
                />
                {hasDashboardWidget && overview && (
                   <DashboardDaysFilter value={days} onChange={handleDaysChange} />
                )}
                <Button asChild size="sm" className="h-8 gap-1">
                  <Link to={`/w/${wsSlug}/${projSlug}/new`}>
                    <Plus className="size-4" /> {t("page.new_ticket_title")}
                  </Link>
                </Button>
              </div>
            </>
          ) : (
            <Skeleton className="h-5 w-48" />
          )}
        </div>

        {/* 70/30 Split: Main (left) + Sidebar (right) */}
        {hasDashboardWidget && overview ? (
          <div className="flex min-h-0 flex-1 overflow-hidden p-4 gap-4">
            {/* ── LEFT 70% — Stat Cards + Trend + Ticket Table ── */}
            <div className="flex min-h-0 w-[70%] min-w-0 flex-col gap-4">
              <WidgetDataProvider
                value={{
                  projectId: project?.id ?? null,
                  overview,
                  tickets: ticketsData?.tickets ?? [],
                  ticketsLoading: isLoading,
                  members,
                  activeTicketId,
                  filters,
                  searchInput: "",
                  onSearchInput: () => {},
                  onFiltersChange: () => {},
                  onSelectTicket: openTicket,
                }}
              >
                {/* Stat Cards — full width */}
                {enabled.includes("dashboard_stat_cards") && (
                  <WidgetShell
                    def={OVERVIEW_WIDGETS.find((w) => w.id === "dashboard_stat_cards")!}
                    onRemove={(id) => update(enabled.filter((x) => x !== id))}
                  >
                    {(() => {
                      const def = OVERVIEW_WIDGETS.find((w) => w.id === "dashboard_stat_cards")
                      if (!def) return null
                      const Comp = def.component
                      return <Comp />
                    })()}
                  </WidgetShell>
                )}
                {/* Ticket Trend — full width */}
                {enabled.includes("ticket_trend") && (
                  <WidgetShell
                    def={OVERVIEW_WIDGETS.find((w) => w.id === "ticket_trend")!}
                    onRemove={(id) => update(enabled.filter((x) => x !== id))}
                  >
                    {(() => {
                      const def = OVERVIEW_WIDGETS.find((w) => w.id === "ticket_trend")
                      if (!def) return null
                      const Comp = def.component
                      return <Comp />
                    })()}
                  </WidgetShell>
                )}
              </WidgetDataProvider>
              {/* Ticket Table — sisa ruang dengan filter di dalam */}
              <div className="min-h-0 flex-1 overflow-auto rounded-xl border bg-card">
                <div className="border-b px-4 py-2.5">
                  <TicketFilters members={members} />
                </div>
                <TicketTable
                  projectKey={project?.key ?? ""}
                  tickets={ticketsData?.tickets ?? []}
                  meta={ticketsData?.meta}
                  page={page}
                  onPageChange={setPage}
                  isLoading={isLoading}
                  activeTicketId={activeTicketId}
                  onSelect={(t) => openTicket(t)}
                />
              </div>
            </div>

            {/* ── RIGHT 30% — Severity Donut + Top Alert Types + Top Services ── */}
            <div className="flex w-[30%] min-w-0 flex-col gap-4 overflow-auto">
              <WidgetDataProvider
                value={{
                  projectId: project?.id ?? null,
                  overview,
                  tickets: ticketsData?.tickets ?? [],
                  ticketsLoading: isLoading,
                  members,
                  activeTicketId,
                  filters,
                  searchInput: "",
                  onSearchInput: () => {},
                  onFiltersChange: () => {},
                  onSelectTicket: openTicket,
                }}
              >
                {enabled.includes("severity_donut") && (
                  <WidgetShell
                    def={OVERVIEW_WIDGETS.find((w) => w.id === "severity_donut")!}
                    onRemove={(id) => update(enabled.filter((x) => x !== id))}
                  >
                    {(() => {
                      const def = OVERVIEW_WIDGETS.find((w) => w.id === "severity_donut")
                      if (!def) return null
                      const Comp = def.component
                      return <Comp />
                    })()}
                  </WidgetShell>
                )}
                {enabled.includes("top_services") && (
                  <WidgetShell
                    def={OVERVIEW_WIDGETS.find((w) => w.id === "top_services")!}
                    onRemove={(id) => update(enabled.filter((x) => x !== id))}
                  >
                    {(() => {
                      const def = OVERVIEW_WIDGETS.find((w) => w.id === "top_services")
                      if (!def) return null
                      const Comp = def.component
                      return <Comp />
                    })()}
                  </WidgetShell>
                )}
                {enabled.includes("top_alert_types") && (
                  <WidgetShell
                    def={OVERVIEW_WIDGETS.find((w) => w.id === "top_alert_types")!}
                    onRemove={(id) => update(enabled.filter((x) => x !== id))}
                  >
                    {(() => {
                      const def = OVERVIEW_WIDGETS.find((w) => w.id === "top_alert_types")
                      if (!def) return null
                      const Comp = def.component
                      return <Comp />
                    })()}
                  </WidgetShell>
                )}
              </WidgetDataProvider>
            </div>
          </div>
        ) : (
          /* Tanpa dashboard — ticket table full width dengan filter di dalam */
          <div className="min-h-0 flex-1 overflow-auto rounded-xl border bg-card">
            <div className="border-b px-4 py-2.5">
              <TicketFilters members={members} />
            </div>
            <TicketTable
              projectKey={project?.key ?? ""}
              tickets={ticketsData?.tickets ?? []}
              meta={ticketsData?.meta}
              page={page}
              onPageChange={setPage}
              isLoading={isLoading}
              activeTicketId={activeTicketId}
              onSelect={(t) => openTicket(t)}
            />
          </div>
        )}
      </div>

      {/* Floating panel */}
      {project && (
        <FloatingPanel
          open={Boolean(detailTicket)}
          onClose={closeTicket}
          headerLeft={
            detailTicket ? (
              <span className="panel-no-drag max-w-40 truncate rounded-md bg-primary/10 px-2 py-1 font-mono text-xs font-semibold text-primary">
                {project.key}-{detailTicket.ticketNumber}
              </span>
            ) : undefined
          }
          title={t("page.panel_title")}
        >
          {detailTicket && (
            <TicketDetailChatPanel
              ticket={detailTicket}
              projectKey={project.key}
              projectId={project.id}
              members={members}
              onClose={closeTicket}
              onOpenWarroom={() => openWarroom(detailTicket)}
            />
          )}
        </FloatingPanel>
      )}
    </div>
  )
}

function NotFoundBlock({ message }: { message: string }) {
  const { t } = useTranslation("project")
  return (
    <div className="p-8">
      <div className="mx-auto max-w-md rounded-lg border border-dashed p-8 text-center">
        <p className="text-sm font-medium">{message}</p>
        <Button asChild variant="outline" size="sm" className="mt-4">
          <Link to="/">{t("page.go_home")}</Link>
        </Button>
      </div>
    </div>
  )
}
