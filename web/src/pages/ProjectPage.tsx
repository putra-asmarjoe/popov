import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ChevronRight, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ChatPanel } from "@/components/chat/ChatPanel"
import { TicketDetail } from "@/components/ticket/TicketDetail"
import { TicketFilters } from "@/components/ticket/TicketFilters"
import { TicketTable } from "@/components/ticket/TicketTable"
import { FloatingPanel } from "@/components/panel/FloatingPanel"
import { OnboardingBackStrip } from "@/components/workspace/OnboardingBackStrip"
import { useTicket, useTickets, useOpenTicket } from "@/hooks/useTickets"
import { useTicketRealtime } from "@/hooks/useWebSocket"
import { useProjects, useWorkspaces, useWorkspaceDetail } from "@/hooks/useWorkspaces"
import { useTicketStore } from "@/store/ticket.store"
import { useWorkspaceStore } from "@/store/workspace.store"
import type { TicketContext } from "@/types/chat"

/**
 * ProjectPage (/w/:wsSlug/:projSlug) — HALAMAN UTAMA.
 * Ticket list selalu full-width (tidak terdorong panel). Panel kanan (Detail | Chat)
 * adalah FloatingPanel draggable + resizable (≥md) atau drawer (<md).
 * Tiket aktif disinkronkan lewat URL ?ticket=KEY-N (shareable + refresh-safe).
 */
export function ProjectPage() {
  const { t } = useTranslation("project")
  const { wsSlug, projSlug } = useParams<{ wsSlug: string; projSlug: string }>()
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
  const { filters, activeTicket, setActiveTicket } = useTicketStore()
  const [page, setPage] = useState(1)
  const [searchParams, setSearchParams] = useSearchParams()

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

  // URL → activeTicket (?ticket=KEY-N sebagai single source of truth)
  const ticketParam = searchParams.get("ticket")
  useEffect(() => {
    if (!ticketParam) {
      if (activeTicket) setActiveTicket(null)
      return
    }
    const num = parseInt(ticketParam.split("-")[1] ?? "", 10)
    if (Number.isNaN(num)) return
    const found = ticketsData?.tickets.find((t) => t.ticketNumber === num)
    if (found && found.id !== activeTicket?.id) setActiveTicket(found)
  }, [ticketParam, ticketsData, activeTicket?.id, activeTicket, setActiveTicket])

  const selectTicket = (number: number | null) => {
    if (number === null) {
      setSearchParams({}, { replace: true })
    } else {
      setSearchParams({ ticket: `${project?.key ?? ""}-${number}` }, { replace: true })
    }
  }

  const { data: freshTicket } = useTicket(
    activeTicket?.id ?? null,
    activeTicket,
  )
  // Detail selalu pakai data termutakhir (optimistic/invalidate langsung terlihat)
  const detailTicket = freshTicket ?? activeTicket

  // Status "new" → "open" saat detail tiket dibuka (auto-open-on-view, silent).
  // Guard ref: sekali per tiket — optimistic update membuat status bukan lagi "new".
  const openedRef = useRef<Set<string>>(new Set())
  const openTicket = useOpenTicket()
  useEffect(() => {
    if (!detailTicket || detailTicket.status !== "new") return
    if (openedRef.current.has(detailTicket.id)) return
    openedRef.current.add(detailTicket.id)
    openTicket.mutate(detailTicket.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailTicket?.id, detailTicket?.status])

  // Konteks tiket untuk chat — 1 sesi chat = 1 tiket (bawaan panel split Detail | Chat)
  const chatCtx = useMemo<TicketContext | null>(() => {
    if (!detailTicket) return null
    return {
      ticketId: detailTicket.id,
      ticketNumber: `${project?.key ?? ""}-${detailTicket.ticketNumber}`,
      title: detailTicket.title,
      traceId: detailTicket.traceId,
      serviceName: detailTicket.serviceName ?? null, // Fix #49
    }
  }, [detailTicket, project?.key])

  if (!wsLoading && !workspace)
    return <NotFoundBlock message={t("page.workspace_not_found")} />
  if (!projLoading && workspace && !project)
    return <NotFoundBlock message={t("page.project_not_found")} />

  return (
    <div className="grid h-full min-h-0 grid-cols-1 grid-rows-1">
      {/* ── Ticket list — selalu full-width, tidak terdorong panel ── */}
      <div className="flex min-w-0 min-h-0 flex-col">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1.5 border-b px-4 py-3 text-sm">
          {workspace && project ? (
            <>
              <Link to={`/w/${wsSlug}`} className="text-muted-foreground hover:text-foreground">
                {workspace.name}
              </Link>
              <ChevronRight className="size-3.5 text-muted-foreground" />
              <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-xs font-semibold text-primary">
                {project.key}
              </span>
              {/* Jalur pulang ke checklist bila masuk halaman ini dari onboarding */}
              <OnboardingBackStrip backTo={`/w/${wsSlug}`} />
              <span className="font-medium">{project.name}</span>
              {/* Fase D8 + Fix #37: pilih Observability Stack & channel Notifikasi (admin) */}
              <div className="ml-auto flex items-center gap-2">
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
          activeTicketId={activeTicket?.id ?? null}
          onSelect={(t) => selectTicket(t.ticketNumber)}
        />
      </div>

      {/* Floating panel: Detail (kiri 30%) + Chat terikat tiket (kanan 70%) — tampil bersamaan.
          Drag/resize di desktop, drawer di mobile. */}
      {project && (
        <FloatingPanel
          open={Boolean(detailTicket)}
          onClose={() => selectTicket(null)}
          headerLeft={
            detailTicket ? (
              <span className="panel-no-drag max-w-40 truncate rounded-md bg-primary/10 px-2 py-1 font-mono text-xs font-semibold text-primary">
                {project.key}-{detailTicket.ticketNumber}
              </span>
            ) : undefined
          }
          title={t("page.panel_title")}
        >
          <div className="flex h-full min-h-0 min-w-0">
            {/* 30% kiri: detail tiket */}
            <div className="flex h-full min-w-0 w-[30%] shrink-0 flex-col border-r">
              {detailTicket && (
                <TicketDetail
                  ticket={detailTicket}
                  projectKey={project.key}
                  members={members}
                  onClose={() => selectTicket(null)}
                />
              )}
            </div>
            {/* 70% kanan: chat yang terikat tiket ini */}
            <div className="flex h-full min-w-0 flex-1 flex-col">
              <ChatPanel key={project.id} projectId={project.id} ticket={chatCtx} />
            </div>
          </div>
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
