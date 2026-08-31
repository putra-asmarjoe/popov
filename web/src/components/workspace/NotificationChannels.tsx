import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Eye, EyeOff, Pencil, PlugZap, Plus, Send, Trash2 } from "lucide-react"
import { apiErrorMessage } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
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
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  ChannelLinkedError,
  useChannelMutations,
  useTestChannelCredentials,
  useWorkspaceChannels,
  type ChannelCreateInput,
  type NotificationChannel,
} from "@/hooks/useNotificationChannels"
import { useNtfProjectLinks } from "@/hooks/useManagement"
import { useProjects } from "@/hooks/useWorkspaces"
import { useAuth } from "@/hooks/useAuth"

/**
 * Tab Notifikasi Workspace Settings (Fix #40) — channel milik workspace ini.
 * Multi-channel: Telegram (bot getMe) | Email (SMTP verify). Kredensial hanya
 * tampil tersamar. Channel tanpa project_ids = workspace-wide (melayani semua
 * project); channel ter-link hanya melayani project itu — broadcast = union.
 */
export function NotificationChannels({ wsId }: { wsId: string }) {
  const { t } = useTranslation("settings")
  const { data: channels, isLoading } = useWorkspaceChannels(wsId)
  const { create, update, remove, test } = useChannelMutations(wsId)
  const { data: projects } = useProjects(wsId ?? null)
  const { user: me } = useAuth()
  const canEdit = me?.role === "admin"
  const { link: ntfLink, unlink: ntfUnlink } = useNtfProjectLinks()
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<NotificationChannel | null>(null)
  const [deletingChannel, setDeletingChannel] = useState<NotificationChannel | null>(null)
  const [forceDeleteLinked, setForceDeleteLinked] = useState<{ channel: NotificationChannel; names: string } | null>(null)

  const onDelete = async (n: NotificationChannel) => {
    try {
      await remove.mutateAsync({ notif_id: n.notif_id })
    } catch (e) {
      if (e instanceof ChannelLinkedError && e.projects.length > 0) {
        const names = e.projects.map((p) => p.name).join(", ")
        setForceDeleteLinked({ channel: n, names })
      }
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {t("channels.description")}
        </p>
        <Button size="sm" onClick={() => setCreateOpen(true)} className="shrink-0">
          <Plus className="size-4" /> {t("channels.add_channel")}
        </Button>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("channels.col_name")}</TableHead>
              <TableHead>{t("channels.col_source")}</TableHead>
              <TableHead className="hidden md:table-cell">{t("channels.col_target")}</TableHead>
              <TableHead>{t("channels.col_project")}</TableHead>
              <TableHead>{t("channels.col_status")}</TableHead>
              <TableHead className="w-32" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [...Array(3)].map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6}><Skeleton className="h-8 w-full" /></TableCell>
                </TableRow>
              ))
            ) : (channels ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="py-6 text-center text-sm text-muted-foreground">
                  {t("channels.empty")}
                </TableCell>
              </TableRow>
            ) : (
              (channels ?? []).map((n) => {
                const tg = n.config?.telegram
                const em = n.config?.email
                const isEmail = n.channel === "email"
                return (
                  <TableRow key={n.notif_id}>
                    <TableCell>
                      <div className="font-medium">{n.name}</div>
                      <div className="font-mono text-xs text-muted-foreground">{n.notif_id}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{n.channel}</Badge>
                      {tg?.botUsername && (
                        <div className="mt-0.5 text-xs text-muted-foreground">@{tg.botUsername}</div>
                      )}
                      {tg?.bot_token_masked && (
                        <div className="font-mono text-[11px] text-muted-foreground">{tg.bot_token_masked}</div>
                      )}
                      {isEmail && (
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {em?.from_addr ? (
                            <span className="font-mono text-[11px]">{em.from_addr}</span>
                          ) : (
                            <span>—</span>
                          )}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="hidden font-mono text-xs md:table-cell">
                      {tg ? (tg.chat_id ?? "—") : isEmail ? (
                        <>
                          {em?.to_addrs && em.to_addrs.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              <span className="text-[10px] text-muted-foreground">To:</span>
                              {em.to_addrs.map((addr, i) => (
                                <span key={i} className="font-mono text-[11px] bg-muted px-1 rounded">{addr}</span>
                              ))}
                            </div>
                          )}
                          {em?.cc_addrs && em.cc_addrs.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              <span className="text-[10px] text-muted-foreground">CC:</span>
                              {em.cc_addrs.map((addr, i) => (
                                <span key={i} className="font-mono text-[11px] bg-muted px-1 rounded">{addr}</span>
                              ))}
                            </div>
                          )}
                          {em?.bcc_addrs && em.bcc_addrs.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              <span className="text-[10px] text-muted-foreground">BCC:</span>
                              {em.bcc_addrs.map((addr, i) => (
                                <span key={i} className="font-mono text-[11px] bg-muted px-1 rounded">{addr}</span>
                              ))}
                            </div>
                          )}
                          {(!em?.to_addrs?.length && !em?.cc_addrs?.length && !em?.bcc_addrs?.length) && (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </>
                      ) : "—"}
                    </TableCell>
                    <TableCell className="max-w-[240px]">
                      <div className="flex flex-wrap items-center gap-1">
                        {(projects ?? [])
                          .filter((p) => n.project_ids.includes(p.id))
                          .map((p) => (
                            <button
                              key={p.id}
                              type="button"
                              disabled={!canEdit || ntfLink.isPending || ntfUnlink.isPending}
                              title={t("channels.unlink_project_title")}
                              className="rounded-full border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary hover:bg-primary/20 disabled:opacity-50"
                              onClick={() => ntfUnlink.mutate({ notif_id: n.notif_id, project_id: p.id })}
                            >
                              {p.name} ✕
                            </button>
                          ))}
                        {canEdit &&
                          (projects ?? [])
                            .filter((p) => !n.project_ids.includes(p.id))
                            .map((p) => (
                              <button
                                key={`add-${p.id}`}
                                type="button"
                                disabled={ntfLink.isPending || ntfUnlink.isPending}
                                title={t("channels.link_project_title", { name: p.name })}
                                className="rounded-full border border-dashed px-1.5 py-0.5 text-[10px] text-muted-foreground hover:border-primary/40 hover:bg-primary/10 hover:text-primary disabled:opacity-50"
                                onClick={() => ntfLink.mutate({ notif_id: n.notif_id, project_id: p.id })}
                              >
                                + {p.name}
                              </button>
                            ))}
                        {(projects ?? []).length === 0 && (
                          <span className="text-xs text-muted-foreground">{t("channels.all_projects_hint")}</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <button
                        type="button"
                        title={t("channels.toggle_title")}
                        disabled={update.isPending}
                        onClick={() => update.mutate({ notif_id: n.notif_id, enabled: !n.enabled })}
                        className="inline-flex"
                      >
                        <Badge variant={n.enabled ? "default" : "outline"}>
                          {n.enabled ? t("channels.active") : t("channels.inactive")}
                        </Badge>
                      </button>
                      {((tg?.health_status ?? em?.health_status) === "error") && (
                        <div className="mt-0.5 text-[11px] text-destructive">{t("channels.health_error")}</div>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost" size="sm" className="h-7 text-xs"
                          disabled={test.isPending}
                          onClick={() => test.mutate(n.notif_id)}
                        >
                          <Send className="mr-1 size-3" /> {t("channels.test_btn")}
                        </Button>
                        <Button
                          variant="ghost" size="icon" className="size-7"
                          onClick={() => setEditing(n)}
                          title={t("channels.edit_title_attr")}
                        >
                          <Pencil className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7 text-destructive hover:text-destructive"
                           onClick={() => setDeletingChannel(n)}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </div>

      <CreateChannelDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        submitting={create.isPending}
        workspaceId={wsId}
        onCreate={async (input) => {
          try {
            await create.mutateAsync(input)
            return true
          } catch {
            return false // biarkan dialog tetap terbuka saat validasi gagal
          }
        }}
      />

      <EditChannelDialog
        channel={editing}
        onOpenChange={(open) => !open && setEditing(null)}
        submitting={update.isPending}
        onUpdate={async (notifId, input) => {
          try {
            await update.mutateAsync({ notif_id: notifId, ...input })
            return true
          } catch {
            return false
          }
        }}
      />

      <AlertDialog open={!!deletingChannel} onOpenChange={(open) => !open && setDeletingChannel(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("channels.delete_channel_confirm", { name: deletingChannel?.name ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>{t("channels.delete_channel_desc")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("channels.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (deletingChannel) void onDelete(deletingChannel)
                setDeletingChannel(null)
              }}
            >
              {t("channels.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={!!forceDeleteLinked} onOpenChange={(open) => !open && setForceDeleteLinked(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("channels.still_linked_confirm", { names: forceDeleteLinked?.names ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>{t("channels.still_linked_desc")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("channels.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (forceDeleteLinked) {
                  remove.mutate({ notif_id: forceDeleteLinked.channel.notif_id, confirm: true })
                  setForceDeleteLinked(null)
                }
              }}
            >
              {t("channels.force_delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// ── Shared field helpers ──────────────────────────────────────────────────────

function parseCsv(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean)
}

function PasswordInput({
  id,
  value,
  onChange,
  placeholder,
}: {
  id: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const [show, setShow] = useState(false)
  const { t } = useTranslation("settings")
  return (
    <div className="relative">
      <Input
        id={id}
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="pr-9 font-mono text-xs"
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute inset-y-0 right-2 flex items-center text-muted-foreground hover:text-foreground"
        aria-label={show ? t("channels.password_hide") : t("channels.password_show")}
      >
        {show ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
      </button>
    </div>
  )
}

// ── Dialog create ─────────────────────────────────────────────────────────────

function CreateChannelDialog({
  open,
  onOpenChange,
  submitting,
  onCreate,
  workspaceId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  submitting: boolean
  onCreate: (input: ChannelCreateInput) => Promise<boolean>
  workspaceId?: string
}) {
  const { t } = useTranslation("settings")
  const { data: allProjects } = useProjects(workspaceId ?? null)
  const [channel, setChannel] = useState<"telegram" | "email">("telegram")
  const [name, setName] = useState("")
  // telegram
  const [botToken, setBotToken] = useState("")
  const [chatId, setChatId] = useState("")
  // email
  const [smtpHost, setSmtpHost] = useState("")
  const [smtpPort, setSmtpPort] = useState(587)
  const [security, setSecurity] = useState<"starttls" | "ssl" | "none">("starttls")
  const [ignoreTls, setIgnoreTls] = useState(false)
  const [disableStartTls, setDisableStartTls] = useState(false)
  const [smtpUser, setSmtpUser] = useState("")
  const [smtpPass, setSmtpPass] = useState("")
  const [fromAddr, setFromAddr] = useState("")
  const [toAddrs, setToAddrs] = useState("")
  const [ccAddrs, setCcAddrs] = useState("")
  const [bccAddrs, setBccAddrs] = useState("")
  // Project linking: default all projects selected
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set())

  const testCreds = useTestChannelCredentials()
  const [check, setCheck] = useState<"idle" | "pending" | "ok" | "fail">("idle")
  const [checkMsg, setCheckMsg] = useState("")

  // Update selectedProjectIds when projects load
  const prevProjectsRef = useRef<string[]>([])
  useEffect(() => {
    if (allProjects && prevProjectsRef.current.length === 0 && allProjects.length > 0) {
      setSelectedProjectIds(new Set(allProjects.map((p) => p.id)))
    }
    prevProjectsRef.current = allProjects?.map((p) => p.id) ?? []
  }, [allProjects])

  const reset = () => {
    setChannel("telegram")
    setName(""); setBotToken(""); setChatId("")
    setSmtpHost(""); setSmtpPort(587); setSecurity("starttls")
    setIgnoreTls(false); setDisableStartTls(false)
    setSmtpUser(""); setSmtpPass(""); setFromAddr(""); setToAddrs(""); setCcAddrs(""); setBccAddrs("")
    setCheck("idle"); setCheckMsg("")
  }

  const valid =
    name.length >= 3 &&
    (channel === "telegram"
      ? botToken.length > 20 && chatId.length >= 1
      : smtpHost.trim().length > 0 &&
        fromAddr.includes("@") &&
        parseCsv(toAddrs).length > 0)

  const runCheck = async () => {
    setCheck("pending")
    try {
      if (channel === "telegram") {
        const r = await testCreds.mutateAsync({ channel: "telegram", bot_token: botToken, chat_id: chatId })
        if (r.getMe?.ok) {
          setCheck("ok")
          setCheckMsg(r.getMe?.username ? `@${r.getMe.username}` : "OK")
        } else {
          setCheck("fail")
          setCheckMsg(r.getMe?.error ?? r.error ?? "Unknown error")
        }
      } else {
        const r = await testCreds.mutateAsync({
          channel: "email", smtp_host: smtpHost, smtp_port: smtpPort, security,
          ignore_tls_error: ignoreTls, disable_starttls: disableStartTls,
          smtp_user: smtpUser || undefined, smtp_pass: smtpPass || undefined,
        })
        if (r.smtp?.ok) {
          setCheck("ok")
          setCheckMsg(r.smtp.banner ?? "OK")
        } else {
          setCheck("fail")
          setCheckMsg(r.smtp?.error ?? r.error ?? "Unknown error")
        }
      }
    } catch (e) {
      setCheck("fail")
      setCheckMsg(apiErrorMessage(e, "Connection failed"))
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("channels.create_title")}</DialogTitle>
          <DialogDescription>
            {channel === "telegram"
              ? t("channels.create_desc_telegram")
              : t("channels.create_desc_email")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>{t("channels.channel_label")}</Label>
            <div className="flex gap-1.5">
              {(["telegram", "email"] as const).map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setChannel(c)}
                  className={
                    "rounded-full border px-3 py-1 text-xs capitalize " +
                    (channel === c
                      ? "border-primary bg-primary font-medium text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted")
                  }
                >
                  {c === "telegram" ? "Telegram" : "Email"}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ch-name">{t("channels.name_label")}</Label>
            <Input id="ch-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ops Alerts Group A" />
          </div>

          {channel === "telegram" ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="ch-chat">{t("channels.chat_label")}</Label>
                <Input id="ch-chat" value={chatId} onChange={(e) => setChatId(e.target.value)} placeholder={`-100xxxxxxxxxx (${t("channels.chat_placeholder_hint")})`} className="font-mono text-xs" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ch-token">{t("channels.token_label")}</Label>
                <Input id="ch-token" type="password" value={botToken} onChange={(e) => { setBotToken(e.target.value); setCheck("idle") }} placeholder="123456789:AA…" className="font-mono text-xs" />
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  disabled={botToken.length < 20 || check === "pending" || testCreds.isPending}
                  onClick={() => void runCheck()}
                >
                  <PlugZap className={`size-3.5 ${check === "pending" ? "animate-pulse" : ""}`} />
                  {check === "pending" ? t("channels.checking") : t("channels.check_connection")}
                </Button>
              </div>
              {check !== "idle" && check !== "pending" && (
                <p className={`text-xs ${check === "ok" ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}`}>
                  {checkMsg}
                </p>
              )}
            </>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 space-y-1.5">
                  <Label htmlFor="em-host">{t("channels.email_host_label")}</Label>
                  <Input id="em-host" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} placeholder="smtp.example.com" className="font-mono text-xs" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="em-port">{t("channels.email_port_label")}</Label>
                  <Input id="em-port" type="number" min={1} max={65535} value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value) || 587)} className="font-mono text-xs" />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>{t("channels.email_security_label")}</Label>
                <div className="flex flex-wrap gap-1.5">
                  {([
                    ["starttls", t("channels.email_security_starttls")],
                    ["ssl", t("channels.email_security_ssl")],
                    ["none", t("channels.email_security_none")],
                  ] as const).map(([val, label]) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setSecurity(val)}
                      className={
                        "rounded-full border px-2.5 py-1 text-[11px] " +
                        (security === val
                          ? "border-primary bg-primary font-medium text-primary-foreground"
                          : "text-muted-foreground hover:bg-muted")
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap gap-4">
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input type="checkbox" checked={ignoreTls} onChange={(e) => setIgnoreTls(e.target.checked)} />
                  {t("channels.email_ignore_tls")}
                </label>
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input type="checkbox" checked={disableStartTls} onChange={(e) => setDisableStartTls(e.target.checked)} />
                  {t("channels.email_disable_starttls")}
                </label>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label htmlFor="em-user">{t("channels.email_username_label")}</Label>
                  <Input id="em-user" value={smtpUser} onChange={(e) => setSmtpUser(e.target.value)} className="font-mono text-xs" autoComplete="off" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="em-pass">{t("channels.email_password_label")}</Label>
                  <PasswordInput id="em-pass" value={smtpPass} onChange={setSmtpPass} placeholder="••••••••" />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="em-from">{t("channels.email_from_label")}</Label>
                <Input id="em-from" value={fromAddr} onChange={(e) => setFromAddr(e.target.value)} placeholder={'"Popov Alert" <alert@popov.test>'} className="font-mono text-xs" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="em-to">{t("channels.email_to_label")}</Label>
                <Input id="em-to" value={toAddrs} onChange={(e) => setToAddrs(e.target.value)} placeholder="ops@popov.test, oncall@popov.test" className="font-mono text-xs" />
                <p className="text-[11px] text-muted-foreground">{t("channels.email_recipients_hint")}</p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label htmlFor="em-cc">{t("channels.email_cc_label")}</Label>
                  <Input id="em-cc" value={ccAddrs} onChange={(e) => setCcAddrs(e.target.value)} placeholder="manager@popov.test" className="font-mono text-xs" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="em-bcc">{t("channels.email_bcc_label")}</Label>
                  <Input id="em-bcc" value={bccAddrs} onChange={(e) => setBccAddrs(e.target.value)} placeholder="audit@popov.test" className="font-mono text-xs" />
                </div>
              </div>
            </>
          )}
          {/* Project linking */}
          {(allProjects ?? []).length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label>{t("observability.link_projects_label")}</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 text-xs text-muted-foreground"
                  onClick={() => {
                    const allIds = allProjects?.map((p) => p.id) ?? []
                    const allSelected = allIds.length === selectedProjectIds.size
                    setSelectedProjectIds(allSelected ? new Set() : new Set(allIds))
                  }}
                >
                  {selectedProjectIds.size === (allProjects?.length ?? 0)
                    ? t("observability.deselect_all")
                    : t("observability.select_all")}
                </Button>
              </div>
              <div className="max-h-40 overflow-y-auto rounded-lg border p-2 space-y-0.5">
                {allProjects?.map((p) => (
                  <label
                    key={p.id}
                    className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-muted"
                  >
                    <input
                      type="checkbox"
                      className="size-3.5 accent-primary"
                      checked={selectedProjectIds.has(p.id)}
                      onChange={(e) => {
                        setSelectedProjectIds((prev) => {
                          const next = new Set(prev)
                          if (e.target.checked) next.add(p.id)
                          else next.delete(p.id)
                          return next
                        })
                      }}
                    />
                    <span className="font-medium">{p.name}</span>
                  </label>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground">
                {t("observability.link_projects_hint", { count: selectedProjectIds.size })}
              </p>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("channels.cancel")}</Button>
          <Button
            disabled={!valid || submitting}
            onClick={async () => {
              const projectIds = Array.from(selectedProjectIds)
              const input: ChannelCreateInput =
                channel === "telegram"
                  ? { channel: "telegram", name, bot_token: botToken, chat_id: chatId, project_ids: projectIds }
                  : {
                      channel: "email", name,
                      smtp_host: smtpHost.trim(), smtp_port: smtpPort,
                      security, ignore_tls_error: ignoreTls, disable_starttls: disableStartTls,
                      smtp_user: smtpUser.trim() || null, smtp_pass: smtpPass.trim() || null,
                      from_addr: fromAddr.trim(),
                      to_addrs: parseCsv(toAddrs),
                      cc_addrs: parseCsv(ccAddrs),
                      bcc_addrs: parseCsv(bccAddrs),
                      project_ids: projectIds,
                    }
              const ok = await onCreate(input)
              if (ok) { onOpenChange(false); reset() }
            }}
          >
            {submitting ? t("channels.validating") : t("channels.create_submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Dialog edit (conditional telegram/email) ─────────────────────────────────

function EditChannelDialog({
  channel,
  onOpenChange,
  submitting,
  onUpdate,
}: {
  channel: NotificationChannel | null
  onOpenChange: (open: boolean) => void
  submitting: boolean
  onUpdate: (notifId: string, input: Record<string, unknown>) => Promise<boolean>
}) {
  const { t } = useTranslation("settings")
  const isEmail = channel?.channel === "email"
  const tg = channel?.config?.telegram
  const em = channel?.config?.email

  const [name, setName] = useState(channel?.name ?? "")
  const [chatId, setChatId] = useState(tg?.chat_id ?? "")
  const [botToken, setBotToken] = useState("")
  const [smtpHost, setSmtpHost] = useState(em?.smtp_host ?? "")
  const [smtpPort, setSmtpPort] = useState(em?.smtp_port ?? 587)
  const [security, setSecurity] = useState(em?.security ?? "starttls")
  const [ignoreTls, setIgnoreTls] = useState(em?.ignore_tls_error ?? false)
  const [disableStartTls, setDisableStartTls] = useState(em?.disable_starttls ?? false)
  const [smtpUser, setSmtpUser] = useState(em?.smtp_user ?? "")
  const [smtpPass, setSmtpPass] = useState("")
  const [fromAddr, setFromAddr] = useState(em?.from_addr ?? "")
  const [toAddrs, setToAddrs] = useState((em?.to_addrs ?? []).join(", "))
  const [ccAddrs, setCcAddrs] = useState((em?.cc_addrs ?? []).join(", "))
  const [bccAddrs, setBccAddrs] = useState((em?.bcc_addrs ?? []).join(", "))
  // reset form saat channel target berubah
  const [seenId, setSeenId] = useState<string | null>(channel?.notif_id ?? null)
  if (channel && channel.notif_id !== seenId) {
    setSeenId(channel.notif_id)
    setName(channel.name)
    setChatId(channel.config?.telegram?.chat_id ?? "")
    setBotToken("")
    const e2 = channel.config?.email
    setSmtpHost(e2?.smtp_host ?? ""); setSmtpPort(e2?.smtp_port ?? 587)
    setSecurity(e2?.security ?? "starttls"); setIgnoreTls(e2?.ignore_tls_error ?? false)
    setDisableStartTls(e2?.disable_starttls ?? false); setSmtpUser(e2?.smtp_user ?? "")
    setSmtpPass(""); setFromAddr(e2?.from_addr ?? "")
    setToAddrs((e2?.to_addrs ?? []).join(", "))
    setCcAddrs((e2?.cc_addrs ?? []).join(", "))
    setBccAddrs((e2?.bcc_addrs ?? []).join(", "))
  }

  const valid = name.length >= 3 && (isEmail ? fromAddr.includes("@") && parseCsv(toAddrs).length > 0 : chatId.length >= 1)

  return (
    <Dialog open={!!channel} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("channels.edit_dialog_title")}</DialogTitle>
          <DialogDescription>
            {isEmail
              ? t("channels.edit_desc_email")
              : t("channels.edit_desc_telegram")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ech-name">{t("channels.name_label")}</Label>
            <Input id="ech-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          {isEmail ? (
            <>
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 space-y-1.5">
                  <Label htmlFor="ee-host">{t("channels.email_host_label")}</Label>
                  <Input id="ee-host" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} className="font-mono text-xs" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ee-port">{t("channels.email_port_label")}</Label>
                  <Input id="ee-port" type="number" min={1} max={65535} value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value) || 587)} className="font-mono text-xs" />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>{t("channels.email_security_label")}</Label>
                <div className="flex flex-wrap gap-1.5">
                  {([
                    ["starttls", t("channels.email_security_starttls")],
                    ["ssl", t("channels.email_security_ssl")],
                    ["none", t("channels.email_security_none")],
                  ] as const).map(([val, label]) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setSecurity(val)}
                      className={
                        "rounded-full border px-2.5 py-1 text-[11px] " +
                        (security === val
                          ? "border-primary bg-primary font-medium text-primary-foreground"
                          : "text-muted-foreground hover:bg-muted")
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap gap-4">
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input type="checkbox" checked={ignoreTls} onChange={(e) => setIgnoreTls(e.target.checked)} />
                  {t("channels.email_ignore_tls")}
                </label>
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input type="checkbox" checked={disableStartTls} onChange={(e) => setDisableStartTls(e.target.checked)} />
                  {t("channels.email_disable_starttls")}
                </label>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label htmlFor="ee-user">{t("channels.email_username_label")}</Label>
                  <Input id="ee-user" value={smtpUser} onChange={(e) => setSmtpUser(e.target.value)} className="font-mono text-xs" autoComplete="off" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ee-pass">{t("channels.email_password_label")}</Label>
                   <PasswordInput id="ee-pass" value={smtpPass} onChange={setSmtpPass} placeholder={em?.smtp_pass_masked ? `•••••••• (${t("channels.email_password_keep_hint")})` : "••••••••"} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ee-from">{t("channels.email_from_label")}</Label>
                <Input id="ee-from" value={fromAddr} onChange={(e) => setFromAddr(e.target.value)} className="font-mono text-xs" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ee-to">{t("channels.email_to_label")}</Label>
                <Input id="ee-to" value={toAddrs} onChange={(e) => setToAddrs(e.target.value)} className="font-mono text-xs" />
                <p className="text-[11px] text-muted-foreground">{t("channels.email_recipients_hint")}</p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label htmlFor="ee-cc">{t("channels.email_cc_label")}</Label>
                  <Input id="ee-cc" value={ccAddrs} onChange={(e) => setCcAddrs(e.target.value)} className="font-mono text-xs" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ee-bcc">{t("channels.email_bcc_label")}</Label>
                  <Input id="ee-bcc" value={bccAddrs} onChange={(e) => setBccAddrs(e.target.value)} className="font-mono text-xs" />
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="ech-chat">{t("channels.chat_label")}</Label>
                <Input id="ech-chat" value={chatId} onChange={(e) => setChatId(e.target.value)} className="font-mono text-xs" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ech-token">{t("channels.new_token_label")}</Label>
                <Input id="ech-token" type="password" value={botToken} onChange={(e) => setBotToken(e.target.value)} placeholder={t("channels.telegram_token_keep_hint")} className="font-mono text-xs" />
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("channels.cancel")}</Button>
          <Button
            disabled={submitting || !valid}
            onClick={async () => {
              if (!channel) return
              const input: Record<string, unknown> = { name }
              if (isEmail) {
                input.smtp_host = smtpHost.trim()
                input.smtp_port = smtpPort
                input.security = security
                input.ignore_tls_error = ignoreTls
                input.disable_starttls = disableStartTls
                input.smtp_user = smtpUser.trim() || null
                if (smtpPass.trim()) input.smtp_pass = smtpPass.trim()
                input.from_addr = fromAddr.trim()
                input.to_addrs = parseCsv(toAddrs)
                input.cc_addrs = parseCsv(ccAddrs)
                input.bcc_addrs = parseCsv(bccAddrs)
              } else {
                input.chat_id = chatId
                if (botToken.trim()) input.bot_token = botToken.trim()
              }
              const ok = await onUpdate(channel.notif_id, input)
              if (ok) onOpenChange(false)
            }}
          >
            {submitting ? t("channels.saving") : t("channels.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
