import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Check, ChevronsUpDown, ExternalLink, Pencil, RotateCcw, X } from "lucide-react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Separator } from "@/components/ui/separator"
import { SeverityBadge, StatusBadge } from "@/components/ticket/Badges"
import { LinkedAlerts } from "@/components/ticket/LinkedAlerts"
import { ProgressLog } from "@/components/ticket/ProgressLog"
import { TicketForm, type TicketFormValues } from "@/components/ticket/TicketForm"
import {
  useAddProgress,
  useAssignTicket,
  useChangeStatus,
  useReopenTicket,
  useUpdateTicket,
} from "@/hooks/useTickets"
import { useTicketAlerts } from "@/hooks/useTicketAlerts"
import { cn, formatDate } from "@/lib/utils"
import { nextStatuses, type Ticket } from "@/types/ticket"
import type { WorkspaceMember } from "@/types/workspace"

/** Panel detail tiket — semua field + aksi status/assign/edit + progress log. */
export function TicketDetail({
  ticket,
  projectKey,
  members,
  onClose,
}: {
  ticket: Ticket
  projectKey: string
  members: WorkspaceMember[]
  onClose: () => void
}) {
  const { t } = useTranslation("project")
  const [editOpen, setEditOpen] = useState(false)
  const changeStatus = useChangeStatus()
  const reopen = useReopenTicket()
  const assign = useAssignTicket()
  const update = useUpdateTicket()
  const addProgress = useAddProgress()
  const alertsQuery = useTicketAlerts(ticket.id)

  const displayNumber = `${projectKey}-${ticket.ticketNumber}`
  const validNext = nextStatuses(ticket.status)
  const canReopen = ticket.status === "resolved" || ticket.status === "closed"
  const assignedIds = new Set(ticket.assignees)
  // Deep-link Grafana Tempo (FE-6) — kosong = tampil teks biasa
  const traceBaseUrl = (import.meta.env.VITE_TRACE_ID_BASE_URL as string | undefined) ?? ""

  const toggleAssignee = (userId: string) => {
    const next = assignedIds.has(userId)
      ? ticket.assignees.filter((id) => id !== userId)
      : [...ticket.assignees, userId]
    assign.mutate({ id: ticket.id, userIds: next })
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="flex min-w-0 items-start gap-2 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-bold">{displayNumber}</span>
            <SeverityBadge severity={ticket.severity} />
            <StatusBadge status={ticket.status} />
            {ticket.source === "watchdog" && (
              <Badge variant="secondary" className="gap-1">🤖 Auto</Badge>
            )}
            {ticket.serviceName && (
              <Badge variant="outline" className="font-mono text-[10px]">{ticket.serviceName}</Badge>
            )}
          </div>
          <h2 className="mt-1.5 truncate text-sm font-semibold leading-snug">{ticket.title}</h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {t("detail.created_by", {
              name: ticket.createdByName || "—",
              date: formatDate(ticket.createdAt),
            })}
            {ticket.resolvedByName && (
              <> · {t("detail.resolved_by", { name: ticket.resolvedByName })}</>
            )}
          </p>
        </div>
        <Button variant="ghost" size="icon" className="size-7 shrink-0" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>

      {/* Body */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {/* Meta grid */}
        <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
          <Meta label="Kind" value={t(`ticket.kind.${ticket.kind}`)} />
          <div className="col-span-2">
            <p className="text-muted-foreground">Trace ID</p>
            {ticket.traceId ? (
              traceBaseUrl ? (
                <a
                  href={`${traceBaseUrl}${ticket.traceId}`}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-0.5 inline-flex items-center gap-1 break-all font-mono text-[11px] text-primary hover:underline"
                  title={t("detail.open_in_tempo")}
                >
                  {ticket.traceId}
                  <ExternalLink className="size-3 shrink-0" />
                </a>
              ) : (
                <p className="mt-0.5 break-all font-mono text-[11px]">{ticket.traceId}</p>
              )
            ) : (
              <p className="mt-0.5 text-muted-foreground/70">—</p>
            )}
          </div>
          {ticket.tags.length > 0 && (
            <div className="col-span-2">
              <p className="text-muted-foreground">{t("detail.section_tags")}</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {ticket.tags.map((tag) => (
                  <Badge key={tag} variant="outline" className="text-[10px]">{tag}</Badge>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Deskripsi */}
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">{t("detail.section_description")}</p>
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{ticket.description}</p>
        </div>

        <Separator />

        {/* Assignee */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-medium text-muted-foreground">Assignee</p>
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="h-7 gap-1 text-xs">
                  <ChevronsUpDown className="size-3" /> {t("detail.assign_button")}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-52 p-1.5">
                {members.length === 0 ? (
                  <p className="px-2 py-1.5 text-xs text-muted-foreground">
                    {t("detail.members_empty")}
                  </p>
                ) : (
                  members.map((m) => (
                    <button
                      key={m.userId}
                      type="button"
                      onClick={() => toggleAssignee(m.userId)}
                      className="flex w-full cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
                    >
                      <Avatar className="size-6">
                        <AvatarFallback className="text-[10px]">
                          {m.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
                        </AvatarFallback>
                      </Avatar>
                      <span className="min-w-0 flex-1 truncate">{m.name}</span>
                      <span className={cn("text-primary", !assignedIds.has(m.userId) && "invisible")}>
                        <Check className="size-4" />
                      </span>
                    </button>
                  ))
                )}
              </PopoverContent>
            </Popover>
          </div>
          {ticket.assigneesDetail.length ? (
            <div className="flex flex-wrap gap-1.5">
              {ticket.assigneesDetail.map((a) => (
                <span key={a.userId} className="flex items-center gap-1.5 rounded-full bg-muted py-0.5 pl-0.5 pr-2.5">
                  <Avatar className="size-5">
                    <AvatarFallback className="text-[9px]">
                      {a.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  <span className="text-xs">{a.name}</span>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground/70">{t("detail.no_assignees")}</p>
          )}
        </div>

        <Separator />

        {/* Progress log */}
        <div>
          <p className="mb-2 text-xs font-medium text-muted-foreground">{t("detail.section_progress")}</p>
          <ProgressLog
            entries={[...ticket.progressLog].reverse()}
            onAdd={(note) => addProgress.mutate({ id: ticket.id, note })}
            adding={addProgress.isPending}
          />
        </div>

        <Separator />

        {/* Linked alerts (Fix #86) — alert notifikasi ter-link, di bawah Progress Log */}
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            {t("detail.section_alerts")}
            {ticket.alertsCount > 0 && (
              <Badge variant="outline" className="h-4 px-1.5 font-mono text-[9px]">
                {ticket.alertsCount}
              </Badge>
            )}
          </p>
          {alertsQuery.isLoading ? (
            <p className="text-xs text-muted-foreground">{t("detail.loading_alerts")}</p>
          ) : (
            <LinkedAlerts alerts={alertsQuery.data?.alerts ?? []} />
          )}
        </div>
      </div>

      {/* Action bar */}
      <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3">
        {validNext.map((status) => (
          <Button
            key={status}
            size="sm"
            variant={status === "resolved" || status === "closed" ? "default" : "outline"}
            className="h-8 text-xs"
            disabled={changeStatus.isPending}
            onClick={() => changeStatus.mutate({ id: ticket.id, status })}
          >
            → {t(`ticket.status.${status}`)}
          </Button>
        ))}
        {canReopen && (
          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-1 text-xs"
            disabled={reopen.isPending}
            onClick={() => reopen.mutate(ticket.id)}
          >
            <RotateCcw className="size-3.5" /> {t("detail.reopen")}
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto h-8 gap-1 text-xs"
          onClick={() => setEditOpen(true)}
        >
          <Pencil className="size-3.5" /> {t("detail.edit")}
        </Button>
      </div>

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("detail.edit_dialog_title", { number: displayNumber })}</DialogTitle>
            <DialogDescription>{t("detail.edit_dialog_description")}</DialogDescription>
          </DialogHeader>
          <TicketForm
            initial={ticket}
            submitting={update.isPending}
            submitLabel={t("detail.save_changes")}
            onCancel={() => setEditOpen(false)}
            onSubmit={(values: TicketFormValues) => {
              update.mutate(
                {
                  id: ticket.id,
                  title: values.title,
                  description: values.description,
                  severity: values.severity,
                  kind: values.kind,
                  traceId: values.traceId ?? "",
                  tags: values.tags,
                },
                { onSuccess: () => setEditOpen(false) },
              )
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-muted-foreground">{label}</p>
      <p className="mt-0.5 capitalize">{value}</p>
    </div>
  )
}
