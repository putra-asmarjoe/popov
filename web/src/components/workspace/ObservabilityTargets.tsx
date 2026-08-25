import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { Copy, KeyRound, PlugZap, Plus, Trash2, X } from "lucide-react"
import { apiErrorMessage } from "@/lib/api"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import {
  useObservabilityTargetMutations,
  useObservabilityTargets,
  useTestTargetUrl,
  type ObservabilityTarget,
  useTestTargetConnection,
  useStackProjectLinks,
} from "@/hooks/useManagement"
import { useAuth } from "@/hooks/useAuth"
import { useProjects } from "@/hooks/useWorkspaces"

/** Jenis endpoint observability yang bisa didaftarkan per stack (dropdown create dialog). */
const OBS_KINDS = [
  { id: "prometheus", label: "Prometheus", placeholder: "http://prometheus:9090" },
  { id: "alertmanager", label: "Alertmanager", placeholder: "http://alertmanager:9093" },
  { id: "tempo", label: "Tempo", placeholder: "http://tempo:3200" },
  { id: "loki", label: "Loki", placeholder: "http://loki:3100" },
] as const

type ObsKind = (typeof OBS_KINDS)[number]["id"]

function kindLabel(id: string): string {
  return OBS_KINDS.find((k) => k.id === id)?.label ?? id
}

function ProjectLinkCell({
  target,
  workspaceId,
}: {
  target: ObservabilityTarget
  workspaceId?: string
}) {
  const { t } = useTranslation("settings")
  const { user } = useAuth()
  const { data: projects } = useProjects(workspaceId ?? null)
  const { link, unlink } = useStackProjectLinks()

  const unlinkedProjects = useMemo(
    () => (projects ?? []).filter((p) => !target.project_ids.includes(p.id)),
    [projects, target.project_ids],
  )
  const canEdit = !!user && (user.role === "admin" || !!workspaceId) // ws-admin di settings; global admin di management

  return (
    <div className="flex flex-wrap items-center gap-1">
      {(projects ?? [])
        .filter((p) => target.project_ids.includes(p.id))
        .map((p) => (
          <button
            key={p.id}
            type="button"
            disabled={!canEdit || link.isPending || unlink.isPending}
            title={t("observability.unlink_project_title")}
            className="rounded-full border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary hover:bg-primary/20 disabled:opacity-50"
            onClick={() => unlink.mutate({ observ_id: target.observ_id, project_id: p.id })}
          >
            {p.name} ✕
          </button>
        ))}
      {canEdit &&
        unlinkedProjects.map((p) => (
          <button
            key={p.id}
            type="button"
            disabled={link.isPending || unlink.isPending}
            title={t("observability.link_project_title", { name: p.name })}
            className="rounded-full border border-dashed px-1.5 py-0.5 text-[10px] text-muted-foreground hover:border-primary/40 hover:bg-primary/10 hover:text-primary disabled:opacity-50"
            onClick={() => link.mutate({ observ_id: target.observ_id, project_id: p.id })}
          >
            + {p.name}
          </button>
        ))}
      {(projects ?? []).length === 0 && (
        <span className="text-xs text-muted-foreground">—</span>
      )}
    </div>
  )
}

/**
 * ObservabilityTargets — SCALE Layer 2 (multi-stack + webhook per-tenant).
 * FE-8.3: dipindah ke Workspace Settings — dengan prop workspaceId komponen
 * ter-scope ke satu workspace (list difilter, create otomatis ter-bind);
 * tanpa prop = mode lama (semua stack, utk Monitoring Global).
 */
export function ObservabilityTargets({ workspaceId }: { workspaceId?: string }) {
  const { t } = useTranslation("settings")
  const { data: allTargets, isLoading } = useObservabilityTargets()
  const targets = workspaceId
    ? allTargets?.filter((t) => t.workspace_id === workspaceId)
    : allTargets
  const { create, remove, rotateToken } = useObservabilityTargetMutations()
  const testUrl = useTestTargetConnection()
  const [createOpen, setCreateOpen] = useState(false)
  const [snippetView, setSnippetView] = useState<{ name: string; snippet: string; token: string } | null>(null)
  // FE-UX: ganti confirm() native dengan modal — rotate | delete
  const [confirmAct, setConfirmAct] = useState<
    { type: "rotate" | "delete"; observId: string; name: string } | null
  >(null)
  const [acting, setActing] = useState(false)

  async function runConfirmed() {
    if (!confirmAct || acting) return
    setActing(true)
    try {
      if (confirmAct.type === "rotate") {
        const r = await rotateToken.mutateAsync(confirmAct.observId)
        setSnippetView({ name: confirmAct.name, snippet: r.alertmanager_snippet, token: r.webhook_token })
      } else {
        remove.mutate(confirmAct.observId)
      }
    } finally {
      setActing(false)
      setConfirmAct(null)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          <span dangerouslySetInnerHTML={{ __html: t("observability.intro") }} />
        </p>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> {t("observability.add")}
        </Button>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Stack</TableHead>
              {!workspaceId && <TableHead className="hidden sm:table-cell">Workspace</TableHead>}
              <TableHead>Kind</TableHead>
              <TableHead>Projects</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead className="hidden md:table-cell">Health</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [...Array(3)].map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={workspaceId ? 4 : 5}><Skeleton className="h-8 w-full" /></TableCell>
                </TableRow>
              ))
            ) : (targets ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-6 text-center text-sm text-muted-foreground">
                  {t("observability.empty")}
                </TableCell>
              </TableRow>
            ) : (
              (targets ?? []).map((tg) => (
                <TableRow key={tg.observ_id}>
                  <TableCell>
                    <div className="font-medium">{tg.name}</div>
                    <div className="font-mono text-xs text-muted-foreground">{tg.observ_id}</div>
                  </TableCell>
                  {!workspaceId && (
                    <TableCell className="hidden text-xs sm:table-cell">
                      {tg.workspace_id ?? <span className="text-muted-foreground">{t("observability.global")}</span>}
                    </TableCell>
                  )}
                  <TableCell>
                    <Badge variant="outline" className="font-mono text-[10px]">{tg.kind ?? "—"}</Badge>
                  </TableCell>
                  <TableCell>
                    <ProjectLinkCell
                      target={tg}
                      workspaceId={workspaceId}
                    />
                  </TableCell>
                  <TableCell>
                    {tg.webhook_mode ? (
                      <Badge variant="default">push/webhook</Badge>
                    ) : (
                      <Badge variant="secondary">poll/{Math.round(tg.poll_interval_seconds / 60)}m</Badge>
                    )}
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    {tg.health_status ? (
                      tg.health_status === "ok" || tg.health_status === "webhook_ok" ? (
                        <Badge variant="secondary">ok</Badge>
                      ) : (
                        <Badge variant="destructive">{tg.health_status}</Badge>
                      )
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={testUrl.isPending}
                        title={t("observability.probe_title")}
                        onClick={async () => {
                          await testUrl.mutateAsync(tg.observ_id)
                        }}
                      >
                        {testUrl.isPending ? "…" : "Test"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7"
                        title={t("observability.rotate_token_title")}
                        onClick={() => setConfirmAct({ type: "rotate", observId: tg.observ_id, name: tg.name })}
                      >
                        <KeyRound className="size-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7 text-destructive hover:text-destructive"
                        onClick={() => setConfirmAct({ type: "delete", observId: tg.observ_id, name: tg.name })}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <CreateStackDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        submitting={create.isPending}
        fixedWorkspaceId={workspaceId}
        onCreated={(r) => {
          if (r.target.webhook_mode) {
            setSnippetView({ name: r.target.name, snippet: r.alertmanager_snippet, token: r.webhook_token })
          }
          // mode poll: tidak perlu YAML apapun — agent otomatis cek via URL
        }}
      />

      <SnippetDialog view={snippetView} onClose={() => setSnippetView(null)} />

      {/* Modal konfirmasi rotate/delete (pengganti confirm() native) */}
      <AlertDialog open={!!confirmAct} onOpenChange={(o) => !o && setConfirmAct(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            {confirmAct?.type === "rotate" ? (
              <>
                <AlertDialogTitle>{t("observability.rotate_confirm_title", { name: confirmAct.name })}</AlertDialogTitle>
                <AlertDialogDescription>
                  <span dangerouslySetInnerHTML={{ __html: t("observability.rotate_confirm_desc") }} />
                </AlertDialogDescription>
              </>
            ) : (
              <>
                <AlertDialogTitle>{t("observability.delete_confirm_title", { name: confirmAct?.name ?? "" })}</AlertDialogTitle>
                <AlertDialogDescription>
                  {t("observability.delete_confirm_desc")}
                </AlertDialogDescription>
              </>
            )}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={acting}>{t("observability.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className={
                confirmAct?.type === "delete"
                  ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  : "bg-primary text-primary-foreground hover:bg-primary/90"
              }
              disabled={acting}
              onClick={(e) => {
                e.preventDefault() // jangan tutup modal sebelum aksi async selesai
                runConfirmed()
              }}
            >
              {acting ? t("observability.processing") : confirmAct?.type === "rotate" ? t("observability.confirm_rotate") : t("observability.confirm_delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function CreateStackDialog({
  open,
  onOpenChange,
  submitting,
  onCreated,
  fixedWorkspaceId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  submitting: boolean
  onCreated: (r: { target: ObservabilityTarget; webhook_token: string; alertmanager_snippet: string }) => void
  fixedWorkspaceId?: string
}) {
  const { t } = useTranslation("settings")
  const { create } = useObservabilityTargetMutations()
  const testUrl = useTestTargetUrl()
  const [name, setName] = useState("")
  const [workspaceId, setWorkspaceId] = useState("")
  const [kind, setKind] = useState<ObsKind>("prometheus")
  const [urls, setUrls] = useState<Record<ObsKind, string>>({ prometheus: "", alertmanager: "", tempo: "", loki: "" })
  const [webhookMode, setWebhookMode] = useState(false)
  // Hasil cek koneksi terakhir, terikat ke kind yang dicek
  const [check, setCheck] = useState<{ kind: ObsKind; status: "pending" | "ok" | "fail"; msg?: string } | null>(null)

  const currentMeta = OBS_KINDS.find((k) => k.id === kind)!
  const hasUrl = Object.values(urls).some((v) => v.trim().startsWith("http"))
  const valid = name.trim().length >= 3 && hasUrl

  const setUrl = (k: ObsKind, v: string) => {
    setUrls((prev) => ({ ...prev, [k]: v }))
    setCheck(null)
  }

  const runCheck = async () => {
    const url = urls[kind].trim()
    if (!/^https?:\/\//.test(url)) {
      setCheck({ kind, status: "fail", msg: t("observability.url_prefix_hint") })
      return
    }
    setCheck({ kind, status: "pending" })
    try {
      const r = await testUrl.mutateAsync({ kind, url })
      if (r.status === "ok") setCheck({ kind, status: "ok", msg: t("observability.check_ok", { kind: kindLabel(kind) }) })
      else setCheck({ kind, status: "fail", msg: t("observability.check_fail", { status: r.status }) })
    } catch (e) {
      setCheck({ kind, status: "fail", msg: apiErrorMessage(e, t("observability.check_failed_fallback")) })
    }
  }

  const configuredKinds = OBS_KINDS.filter((k) => urls[k.id].trim() !== "")

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("observability.create_title")}</DialogTitle>
          <DialogDescription>{t("observability.create_description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="obs-name">{t("observability.name_label")}</Label>
            <Input id="obs-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="client-prod-monitoring" />
          </div>
          {!fixedWorkspaceId && (
            <div className="space-y-1.5">
              <Label htmlFor="obs-ws">{t("observability.workspace_id_label")}</Label>
              <Input
                id="obs-ws"
                value={workspaceId}
                onChange={(e) => setWorkspaceId(e.target.value)}
                placeholder={t("observability.workspace_id_placeholder")}
                className="font-mono text-xs"
              />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="obs-url">{t("observability.endpoint_label")}</Label>
            <div className="flex gap-2">
              <Select
                value={kind}
                onValueChange={(v) => { setKind(v as ObsKind); setCheck(null) }}
              >
                <SelectTrigger id="obs-kind" className="w-40 shrink-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {OBS_KINDS.map((k) => (
                    <SelectItem key={k.id} value={k.id}>{k.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                id="obs-url"
                value={urls[kind]}
                onChange={(e) => setUrl(kind, e.target.value)}
                placeholder={currentMeta.placeholder}
                className="min-w-0 flex-1 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                disabled={!urls[kind].trim() || check?.status === "pending" || testUrl.isPending}
                onClick={runCheck}
                className="shrink-0"
              >
                <PlugZap className={`size-3.5 ${check?.status === "pending" ? "animate-pulse" : ""}`} />
                {check?.status === "pending" ? t("observability.checking") : t("observability.check_connection")}
              </Button>
            </div>
            {check?.kind === kind && check.status !== "pending" && (
              <p className={`text-xs ${check.status === "ok" ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}`}>
                {check.msg}
              </p>
            )}
            {configuredKinds.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-0.5">
                {configuredKinds.map((k) => (
                  <Badge key={k.id} variant="secondary" className="gap-1 py-0.5 pr-1 font-normal">
                    <span className="font-medium">{k.label}</span>
                    <span className="max-w-36 truncate font-mono text-[10px] opacity-70">{urls[k.id]}</span>
                    <button
                      type="button"
                      aria-label={t("action.delete", { ns: "common" })}
                      className="rounded-full p-0.5 hover:bg-foreground/10"
                      onClick={() => setUrl(k.id, "")}
                    >
                      <X className="size-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}
          </div>
          <Label className="flex cursor-pointer items-center gap-2 text-sm font-normal">
            <input type="checkbox" checked={webhookMode} onChange={(e) => setWebhookMode(e.target.checked)} className="size-4 accent-primary" />
            Webhook push real-time (opsional — butuh copy snippet ke alertmanager.yml klien;
            tanpa ini polling otomatis tetap berjalan)
          </Label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("observability.cancel")}</Button>
          <Button
            disabled={!valid || submitting}
            title={!hasUrl ? t("observability.add_endpoint_hint") : name.trim().length < 3 ? t("observability.name_min_hint") : undefined}
            onClick={async () => {
              const r = await create.mutateAsync({
                name,
                workspace_id: fixedWorkspaceId || workspaceId || undefined,
                prometheus_url: urls.prometheus.trim(),
                tempo_url: urls.tempo.trim(),
                alertmanager_url: urls.alertmanager.trim(),
                loki_url: urls.loki.trim(),
                webhook_mode: webhookMode,
              })
              onOpenChange(false)
              setName(""); setWorkspaceId(""); setKind("prometheus"); setCheck(null)
              setUrls({ prometheus: "", alertmanager: "", tempo: "", loki: "" })
              onCreated(r)
            }}
          >
            {submitting ? t("observability.creating") : t("observability.create_submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SnippetDialog({ view, onClose }: { view: { name: string; snippet: string; token: string } | null; onClose: () => void }) {
  const { t } = useTranslation("settings")
  return (
    <Dialog open={!!view} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("snippet.title", { name: view?.name ?? "" })}</DialogTitle>
          <DialogDescription>
            <span dangerouslySetInnerHTML={{ __html: t("snippet.description") }} />
          </DialogDescription>
        </DialogHeader>
        {view && (
          <>
            <Textarea readOnly rows={14} value={view.snippet} className="font-mono text-xs" />
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => navigator.clipboard.writeText(view.snippet)}
              >
                <Copy className="mr-1 size-3.5" /> Copy snippet
              </Button>
              <Button onClick={onClose}>Selesai</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}