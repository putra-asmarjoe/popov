import { useMemo } from "react"
import { ChatPanel } from "@/components/chat/ChatPanel"
import { TicketDetail } from "@/components/ticket/TicketDetail"
import { buildTicketContext } from "@/lib/ticket-context"
import type { Ticket } from "@/types/ticket"
import type { WorkspaceMember } from "@/types/workspace"

/** Split Detail (30%) | Chat (70%) terikat tiket — dipakai classic & warroom overlay (DRY). */
export function TicketDetailChatPanel({
  ticket,
  projectKey,
  projectId,
  members,
  onClose,
  onOpenWarroom,
}: {
  ticket: Ticket
  projectKey: string
  projectId: string
  members: WorkspaceMember[]
  onClose: () => void
  onOpenWarroom?: () => void
}) {
  const chatCtx = useMemo(() => buildTicketContext(ticket, projectKey), [ticket, projectKey])

  return (
    <div className="flex h-full min-h-0 min-w-0">
      <div className="flex h-full min-w-0 w-[30%] shrink-0 flex-col border-r">
        <TicketDetail
          ticket={ticket}
          projectKey={projectKey}
          members={members}
          onClose={onClose}
          onOpenWarroom={onOpenWarroom}
        />
      </div>
      <div className="flex h-full min-w-0 flex-1 flex-col">
        <ChatPanel key={projectId} projectId={projectId} ticket={chatCtx} />
      </div>
    </div>
  )
}