import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { cn } from "@/lib/utils"
import type { AssigneeDetail } from "@/types/ticket"

/** Avatar stack multi-assignee dengan overflow +n. */
export function AssigneeList({
  assignees,
  max = 3,
  className,
}: {
  assignees: AssigneeDetail[]
  max?: number
  className?: string
}) {
  if (!assignees.length) {
    return <span className="text-xs text-muted-foreground">—</span>
  }
  const shown = assignees.slice(0, max)
  const overflow = assignees.length - shown.length
  return (
    <div className={cn("flex -space-x-1.5", className)}>
      {shown.map((a) => (
        <Avatar key={a.userId} className="size-6 border-2 border-background" title={`${a.name} (${a.email})`}>
          <AvatarFallback className="text-[9px] font-semibold">{initials(a.name)}</AvatarFallback>
        </Avatar>
      ))}
      {overflow > 0 && (
        <div className="flex size-6 items-center justify-center rounded-full border-2 border-background bg-muted text-[9px] font-semibold text-muted-foreground">
          +{overflow}
        </div>
      )}
    </div>
  )
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
}
