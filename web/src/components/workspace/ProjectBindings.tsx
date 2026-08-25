import { useMemo } from "react"
import { useTranslation } from "react-i18next"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useProjects } from "@/hooks/useWorkspaces"
import {
  useObservabilityTargetMutations,
  useObservabilityTargets,
} from "@/hooks/useManagement"
import {
  useLinkChannelMutations,
  useProjectChannels,
} from "@/hooks/useNotificationChannels"

/**
 * ProjectBindings — FE-8.8.
 * Pindahan dari halaman project (fokus ticketing): binding stack observability &
 * channel notifikasi kini dikelola terpusat di Settings, per project.
 */

// ── Binding Project → Observability Stack ─────────────────────────────────────

export function StackBindings({ workspaceId }: { workspaceId: string }) {
  const { t } = useTranslation("settings")
  const qc = useQueryClient()
  const { data: projects, isLoading: pLoading } = useProjects(workspaceId)
  const { data: targets, isLoading: tLoading } = useObservabilityTargets()
  const { update } = useObservabilityTargetMutations()

  const visible = useMemo(
    () => (targets ?? []).filter((t) => t.workspace_id === workspaceId),
    [targets, workspaceId],
  )
  const active = projects ?? []

  function bindStack(observId: string | "none", projectId: string) {
    let changed = 0
    for (const t of visible) {
      const had = t.project_ids.includes(projectId)
      const should = t.observ_id === observId
      if (had === should) continue
      const nextIds = should
        ? [...t.project_ids, projectId]
        : t.project_ids.filter((p) => p !== projectId)
      update.mutate({ observ_id: t.observ_id, project_ids: nextIds })
      changed++
    }
    if (changed) {
      qc.invalidateQueries({ queryKey: ["config", "observability-targets"] })
      toast(t("bindings.binding_updated_toast"))
    }
  }

  return (
    <div className="space-y-2">
      <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Binding Project → Stack
      </Label>
      {pLoading || tLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : active.length === 0 ? (
        <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
          {t("bindings.no_active_projects")}
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          {active.map((p) => {
            const bound = visible.find((t) => t.project_ids.includes(p.id)) ?? null
            return (
              <div key={p.id}
                className="flex flex-wrap items-center gap-2 border-b px-3 py-2 last:border-b-0">
                <span className="min-w-40 flex-1 truncate text-xs">
                  <span className="mr-1.5 rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-primary">
                    {p.key}
                  </span>
                  {p.name}
                </span>
                {bound && (
                  <Badge variant="secondary" className="text-[10px]">{bound.name}</Badge>
                )}
                <Select
                  value={bound?.observ_id ?? "none"}
                  onValueChange={(v) => bindStack(v as string, p.id)}
                >
                  <SelectTrigger className="h-7 w-[190px] text-xs">
                    <SelectValue placeholder={t("bindings.pick_stack_placeholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">— tanpa stack (global fallback)</SelectItem>
                    {visible.map((t) => (
                      <SelectItem key={t.observ_id} value={t.observ_id}>
                        {t.name} · {t.webhook_mode ? "push" : "poll"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Binding Project → Channel Notifikasi ──────────────────────────────────────

function ChannelBindingRow({
  projectId,
  projectKey,
  projectName,
}: {
  projectId: string
  projectKey: string
  projectName: string
}) {
  const { t } = useTranslation("settings")
  const { data: channels, isLoading } = useProjectChannels(projectId)
  const { link, unlink } = useLinkChannelMutations(projectId)

  const list = channels ?? []
  const linkedCount = list.filter((c) => c.linked).length

  return (
    <div className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0">
      <span className="min-w-40 flex-1 truncate text-xs">
        <span className="mr-1.5 rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-primary">
          {projectKey}
        </span>
        {projectName}
      </span>
      {isLoading ? (
        <Skeleton className="h-6 w-40" />
      ) : list.length === 0 ? (
        <span className="text-[11px] text-muted-foreground">
          {t("bindings.no_channel_hint")}
        </span>
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="rounded-md border px-2 py-1 text-xs hover:bg-accent">
              {linkedCount > 0 ? t("bindings.linked_channels", { count: linkedCount }) : t("bindings.ws_wide")}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-64">
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
              {t("bindings.linked_only_hint")}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {list.map((ch) => (
              <DropdownMenuCheckboxItem
                key={ch.notif_id}
                checked={!!ch.linked}
                onCheckedChange={(next) =>
                  (next ? link.mutateAsync(ch.notif_id) : unlink.mutateAsync(ch.notif_id)).finally(
                    () => void 0,
                  )
                }
              >
                <span className="font-medium">{ch.name}</span>
                <span className="ml-auto text-[10px] text-muted-foreground">telegram</span>
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}

export function NotificationBindings({ workspaceId }: { workspaceId: string }) {
  const { t } = useTranslation("settings")
  const { data: projects, isLoading } = useProjects(workspaceId)
  const active = projects ?? []

  return (
    <div className="space-y-2">
      <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("bindings.binding_label")}
      </Label>
      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : active.length === 0 ? (
        <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
          {t("bindings.no_active_projects")}
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          {active.map((p) => (
            <ChannelBindingRow
              key={p.id}
              projectId={p.id}
              projectKey={p.key}
              projectName={p.name}
            />
          ))}
        </div>
      )}
    </div>
  )
}
