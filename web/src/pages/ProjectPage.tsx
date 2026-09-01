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
import { useTickets } from "@/hooks/useTickets"
import { useTicketSelection } from "@/hooks/useTicketSelection"
import { useTicketRealtime } from "@/hooks/useWebSocket"
import { useProjects, useWorkspaces, useWorkspaceDetail } from "@/hooks/useWorkspaces"
import { getProjectView, setProjectView } from "@/lib/project-view"
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
      {/* ── Ticket list — selalu full-width, tidak terdorong panel ── */}
      <div className="flex min-w-0 min-h-0 flex-col">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1.5 border-b px-4 py-3 text-sm">
          {workspace && project ? (
            <>
              {/* Jalur pulang ke checklist bila masuk halaman ini dari onboarding */}
              <OnboardingBackStrip backTo={`/w/${wsSlug}`} />
              {/* Fase D8 + Fix #37: pilih Observability Stack & channel Notifikasi (admin) */}
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

        {/* Filter bar */}
        <div className="border-b px-4 py-2.5">
          {wsLoading || projLoading ? <Skeleton className="h-8 w-full" /> : <TicketFilters members={members} />}
        </div>

        {/* Table */}
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

      {/* Floating panel: Detail (kiri 30%) + Chat terikat tiket (kanan 70%) — tampil bersamaan.
          Drag/resize di desktop, drawer di mobile. */}
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
