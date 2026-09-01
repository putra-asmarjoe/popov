import { useMemo } from "react"
import { ChatPanel } from "@/components/chat/ChatPanel"
import { TicketDetail } from "@/components/ticket/TicketDetail"
import { SplitHandle } from "@/components/shared/SplitHandle"
import { useDragResize } from "@/hooks/useDragResize"
import { buildTicketContext } from "@/lib/ticket-context"
import type { Ticket } from "@/types/ticket"
import type { WorkspaceMember } from "@/types/workspace"

/** Split Detail | Chat terikat tiket — dipakai classic & warroom overlay (DRY).
 *  Lebar Detail bisa di-resize user (drag divider), persist per user. */
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
  const { width: detailWidth, onPointerDown: detailResize } = useDragResize({
    initial: 300,
    min: 240,
    max: 520,
    storageKey: "popov:ticket-detail-width",
  })

  return (
    <div className="flex h-full min-h-0 min-w-0">
      <div className="flex h-full min-w-0 shrink-0 flex-col" style={{ width: detailWidth }}>
        <TicketDetail
          ticket={ticket}
          projectKey={projectKey}
          members={members}
          onClose={onClose}
          onOpenWarroom={onOpenWarroom}
        />
      </div>
      <SplitHandle onPointerDown={detailResize} />
      <div className="flex h-full min-w-0 flex-1 flex-col">
        <ChatPanel key={projectId} projectId={projectId} ticket={chatCtx} />
      </div>
    </div>
  )
}