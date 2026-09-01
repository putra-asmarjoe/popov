import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { FloatingPanel } from "@/components/panel/FloatingPanel"
import { TicketDetailChatPanel } from "@/components/ticket/TicketDetailChatPanel"
import { ProjectViewToggle } from "@/components/project/ProjectViewToggle"
import { WidgetDataProvider } from "@/components/overview/WidgetDataContext"
import { WidgetGrid } from "@/components/overview/WidgetGrid"
import { WidgetCustomize } from "@/components/overview/WidgetCustomize"
import { useProjectOverview } from "@/hooks/useProjectOverview"
import { useTickets, useOpenTicket } from "@/hooks/useTickets"
import { useProjects, useWorkspaceDetail, useWorkspaces } from "@/hooks/useWorkspaces"
import { useTicketRealtime } from "@/hooks/useWebSocket"
import { WarRoomPanel } from "@/components/warroom/WarRoomPanel"
import { setProjectView } from "@/lib/project-view"
import { useWidgetPrefs, widgetsNeedOverview, widgetsNeedTickets } from "@/lib/overview-widgets"
import type { TicketFilters } from "@/store/ticket.store"
import type { Ticket } from "@/types/ticket"

const DEFAULT_FILTERS: TicketFilters = { status: ["open", "new"], severity: [], assignee: null, search: "" }

/** Project Overview — health project sekilas (War Room mode).
 *  Klik tiket → overlay Detail|Chat TETAP di warroom (URL ?ticket=KEY-N, mode tidak pindah).
 *  Grid = widget plug-and-play (registry + localStorage prefs per project). */
export function ProjectOverview() {
  const { t } = useTranslation("project")
  const { wsSlug, projSlug } = useParams<{ wsSlug: string; projSlug: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const ticketParam = searchParams.get("ticket")
  const viewParam = searchParams.get("view")

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

  // Realtime: ticket baru / berubah → invalidate list + overview (sama seperti classic)
  useTicketRealtime(project?.id ?? null)

  // Widget prefs — localStorage per project (default = widget defaultEnabled)
  const { enabled, update, reset } = useWidgetPrefs(project?.id ?? null)

  // Data fetch GATED by widget enabled — widget di-disable tidak fetch.
  // Overview (4 collection) hanya bila ada widget dataKey; tickets hanya bila ada needsTickets.
  const needOverview = widgetsNeedOverview(enabled)
  const needTickets = widgetsNeedTickets(enabled)
  const { data: overview, isLoading: ovLoading } = useProjectOverview(
    needOverview ? project?.id ?? null : null,
  )

  // Filter tiket — state lokal di halaman ini (default open)
  const [filters, setFilters] = useState<TicketFilters>(DEFAULT_FILTERS)
  const [searchInput, setSearchInput] = useState("")
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== filters.search) setFilters((f) => ({ ...f, search: searchInput }))
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])
  const ticketsQuery = useTickets(needTickets ? project?.id ?? null : null, filters, 1)
  const tickets = ticketsQuery.data?.tickets ?? []

  // Tiket terpilih — dari URL ?ticket=KEY-N (deep-link) atau klik row
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null)
  useEffect(() => {
    if (!ticketParam || !tickets.length) return
    const num = parseInt(ticketParam.split("-").pop() ?? "", 10)
    if (Number.isNaN(num)) return
    const found = tickets.find((tk) => tk.ticketNumber === num)
    if (found && found.id !== selectedTicket?.id) setSelectedTicket(found)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketParam, tickets])

  const selectTicket = (tk: Ticket) => {
    setSelectedTicket(tk)
    setSearchParams({ ticket: `${project?.key ?? ""}-${tk.ticketNumber}` }, { replace: true })
  }

  // Status "new" → "open" saat tiket dibuka dari warroom (sama seperti classic:
  // idempotent + silent, progress entry "Status changed" dicatat backend). Guard ref
  // sekali per tiket — optimistic update membuat status bukan lagi "new".
  const openedRef = useRef<Set<string>>(new Set())
  const openTicket = useOpenTicket()
  useEffect(() => {
    if (!selectedTicket || selectedTicket.status !== "new") return
    if (openedRef.current.has(selectedTicket.id)) return
    openedRef.current.add(selectedTicket.id)
    openTicket.mutate(selectedTicket.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTicket?.id, selectedTicket?.status])
  const closeTicket = () => {
    setSelectedTicket(null)
    setSearchParams({}, { replace: true })
  }
  const openTicketWarroom = (tk: Ticket) => {
    setSelectedTicket(tk)
    setSearchParams(
      { ticket: `${project?.key ?? ""}-${tk.ticketNumber}`, view: "warroom" },
      { replace: true },
    )
  }
  const isTicketWarroom = viewParam === "warroom" && Boolean(selectedTicket)

  if (!wsLoading && !workspace)
    return <p className="p-8 text-sm text-muted-foreground">{t("page.workspace_not_found")}</p>
  if (!projLoading && workspace && !project)
    return <p className="p-8 text-sm text-muted-foreground">{t("page.project_not_found")}</p>

  // Per-ticket War Room — full-width, tetap di warroom mode. Back → overview?ticket=KEY-N
  if (isTicketWarroom && selectedTicket) {
    return (
      <div className="h-full min-h-0">
        <WarRoomPanel
          ticket={selectedTicket}
          onBack={() =>
            setSearchParams(
              { ticket: `${project?.key ?? ""}-${selectedTicket.ticketNumber}` },
              { replace: true },
            )
          }
        />
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header strip */}
      <div className="flex min-w-0 items-center gap-2 border-b px-4 py-2.5">
        <div className="ml-auto flex items-center gap-2">
          <ProjectViewToggle
            value="warroom"
            onChange={(v) => {
              setProjectView(v)
              if (v === "classic") {
                navigate(`/w/${wsSlug}/${projSlug}`)
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
          />
          <Button asChild size="sm" className="h-8 gap-1">
            <Link to={`/w/${wsSlug}/${projSlug}/new`}>
              <Plus className="size-4" /> {t("page.new_ticket_title")}
            </Link>
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {ovLoading && (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <Skeleton className="h-48 w-full" />
              <Skeleton className="h-48 w-full" />
              <Skeleton className="h-48 w-full" />
            </div>
          </div>
        )}

        {!ovLoading && (
          <WidgetDataProvider
            value={{
              projectId: project?.id ?? null,
              overview,
              tickets,
              ticketsLoading: ticketsQuery.isLoading,
              members,
              activeTicketId: selectedTicket?.id ?? null,
              filters,
              searchInput,
              onSearchInput: setSearchInput,
              onFiltersChange: setFilters,
              onSelectTicket: selectTicket,
            }}
          >
            <WidgetGrid enabled={enabled} onRemove={(id) => update(enabled.filter((x) => x !== id))} />
          </WidgetDataProvider>
        )}
      </div>

      {/* Overlay Detail|Chat — TETAP di warroom mode */}
      {project && (
        <FloatingPanel
          open={Boolean(selectedTicket)}
          onClose={closeTicket}
          headerLeft={
            selectedTicket ? (
              <span className="panel-no-drag max-w-40 truncate rounded-md bg-primary/10 px-2 py-1 font-mono text-xs font-semibold text-primary">
                {project.key}-{selectedTicket.ticketNumber}
              </span>
            ) : undefined
          }
          title={t("page.panel_title")}
        >
          {selectedTicket && (
            <TicketDetailChatPanel
              ticket={selectedTicket}
              projectKey={project.key}
              projectId={project.id}
              members={members}
              onClose={closeTicket}
              onOpenWarroom={() => openTicketWarroom(selectedTicket)}
            />
          )}
        </FloatingPanel>
      )}
    </div>
  )
}