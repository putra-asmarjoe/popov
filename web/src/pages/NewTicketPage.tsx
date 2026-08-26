import { Link, useNavigate, useParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { TicketForm, type TicketFormValues } from "@/components/ticket/TicketForm"
import { useCreateTicket } from "@/hooks/useTickets"
import { useProjects, useWorkspaces } from "@/hooks/useWorkspaces"
import type { Ticket } from "@/types/ticket"

/** NewTicketPage (/w/:wsSlug/:projSlug/new) — form tiket penuh. */
export function NewTicketPage() {
  const { t } = useTranslation("project")
  const { wsSlug, projSlug } = useParams<{ wsSlug: string; projSlug: string }>()
  const navigate = useNavigate()
  const { data: workspaces } = useWorkspaces()
  const workspace = workspaces?.find((w) => w.slug === wsSlug) ?? null
  const { data: projects } = useProjects(workspace?.id ?? null)
  const project = projects?.find((p) => p.slug === projSlug) ?? null
  const createTicket = useCreateTicket(project?.id ?? null)

  const onSubmit = async (values: TicketFormValues) => {
    if (!project) return
    const ticket = await createTicket.mutateAsync({
      title: values.title,
      description: values.description,
      kind: values.kind,
      severity: values.severity,
      traceId: values.traceId,
      tags: values.tags,
    })
    // Balik ke project + langsung buka tiket baru
    navigate(`/w/${wsSlug}/${projSlug}?ticket=${project.key}-${(ticket as Ticket).ticketNumber}`)
  }

  return (
    <div className="mx-auto max-w-2xl p-6 md:p-8">
      <Button asChild variant="ghost" size="sm" className="-ml-2 mb-4">
        <Link to={`/w/${wsSlug}/${projSlug}`}>
          <ArrowLeft className="size-4" /> {t("page.back")}
        </Link>
      </Button>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("page.new_ticket_title")} {project && <span className="text-muted-foreground">· {project.key}</span>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <TicketForm
            submitting={createTicket.isPending}
            submitLabel={t("page.create_ticket")}
            onCancel={() => navigate(`/w/${wsSlug}/${projSlug}`)}
            onSubmit={onSubmit}
          />
        </CardContent>
      </Card>
    </div>
  )
}
