import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Pencil, Plus, Send, Trash2 } from "lucide-react"
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
  useWorkspaceChannels,
  type NotificationChannel,
} from "@/hooks/useNotificationChannels"
import { useNtfProjectLinks } from "@/hooks/useManagement"
import { useProjects } from "@/hooks/useWorkspaces"
import { useAuth } from "@/hooks/useAuth"

/**
 * Tab Notifikasi Workspace Settings (Fix #40) — channel milik workspace ini.
 * Multi-bot Telegram: create/update selalu divalidasi getMe; token hanya tampil
 * tersamar. Channel tanpa project_ids = workspace-wide (melayani semua project);
 * channel ter-link hanya melayani project itu — broadcast = union keduanya.
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

  const onDelete = async (n: NotificationChannel) => {
    if (!confirm(t("channels.delete_channel_confirm", { name: n.name }))) return
    try {
      await remove.mutateAsync({ notif_id: n.notif_id })
    } catch (e) {
      if (e instanceof ChannelLinkedError && e.projects.length > 0) {
        const names = e.projects.map((p) => p.name).join(", ")
        if (
          confirm(
            t("channels.still_linked_confirm", { names }),
          )
        ) {
          remove.mutate({ notif_id: n.notif_id, confirm: true })
        }
      }
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Bot Telegram milik workspace — laporan insiden dikirim ke semua channel yang match
          (channel ter-link project ∪ channel workspace-wide). Token disimpan di database dan
          tidak pernah ditampilkan kembali.
        </p>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> {t("channels.add_channel")}
        </Button>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("channels.col_name")}</TableHead>
              <TableHead>{t("channels.col_bot")}</TableHead>
              <TableHead className="hidden md:table-cell">Chat ID</TableHead>
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
                    </TableCell>
                    <TableCell className="hidden font-mono text-xs md:table-cell">
                      {tg?.chat_id ?? "—"}
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
                      {tg?.health_status === "error" && (
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
                          onClick={() => void onDelete(n)}
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
        onCreate={async (input) => {
          try {
            await create.mutateAsync(input)
            return true
          } catch {
            return false // biarkan dialog tetap terbuka saat validasi token gagal
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
    </div>
  )
}

// ── Dialog create ─────────────────────────────────────────────────────────────

function CreateChannelDialog({
  open,
  onOpenChange,
  submitting,
  onCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  submitting: boolean
  onCreate: (input: { name: string; bot_token: string; chat_id: string }) => Promise<boolean>
}) {
  const { t } = useTranslation("settings")
  const [name, setName] = useState("")
  const [botToken, setBotToken] = useState("")
  const [chatId, setChatId] = useState("")

  const valid = name.length >= 3 && botToken.length > 20 && chatId.length >= 1

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("channels.create_title")}</DialogTitle>
          <DialogDescription>
            Token langsung divalidasi getMe ke Telegram — bot harus valid sebelum disimpan.
            Setelah dibuat, link channel ke project lewat bar atas halaman project.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ch-name">{t("channels.name_label")}</Label>
            <Input id="ch-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ops Alerts Group A" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ch-token">{t("channels.token_label")}</Label>
            <Input id="ch-token" type="password" value={botToken} onChange={(e) => setBotToken(e.target.value)} placeholder="123456789:AA…" className="font-mono text-xs" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ch-chat">{t("channels.chat_label")}</Label>
            <Input id="ch-chat" value={chatId} onChange={(e) => setChatId(e.target.value)} placeholder="-100xxxxxxxxxx (bot harus join chat)" className="font-mono text-xs" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("channels.cancel")}</Button>
          <Button
            disabled={!valid || submitting}
            onClick={async () => {
              const ok = await onCreate({ name, bot_token: botToken, chat_id: chatId })
              if (ok) {
                onOpenChange(false)
                setName(""); setBotToken(""); setChatId("")
              }
            }}
          >
            {submitting ? t("channels.validating") : t("channels.create_submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Dialog edit (nama / chat_id / token opsional) ────────────────────────────

function EditChannelDialog({
  channel,
  onOpenChange,
  submitting,
  onUpdate,
}: {
  channel: NotificationChannel | null
  onOpenChange: (open: boolean) => void
  submitting: boolean
  onUpdate: (notifId: string, input: { name?: string; chat_id?: string; bot_token?: string }) => Promise<boolean>
}) {
  const { t } = useTranslation("settings")
  const [name, setName] = useState(channel?.name ?? "")
  const [chatId, setChatId] = useState(channel?.config?.telegram?.chat_id ?? "")
  const [botToken, setBotToken] = useState("")
  // reset form saat channel target berubah
  const [seenId, setSeenId] = useState<string | null>(channel?.notif_id ?? null)
  if (channel && channel.notif_id !== seenId) {
    setSeenId(channel.notif_id)
    setName(channel.name)
    setChatId(channel.config?.telegram?.chat_id ?? "")
    setBotToken("")
  }

  return (
    <Dialog open={!!channel} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("channels.edit_dialog_title")}</DialogTitle>
          <DialogDescription>
            Biarkan token kosong untuk mempertahankan token lama.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ech-name">{t("channels.name_label")}</Label>
            <Input id="ech-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ech-chat">{t("channels.chat_label")}</Label>
            <Input id="ech-chat" value={chatId} onChange={(e) => setChatId(e.target.value)} className="font-mono text-xs" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ech-token">{t("channels.new_token_label")}</Label>
            <Input id="ech-token" type="password" value={botToken} onChange={(e) => setBotToken(e.target.value)} placeholder="kosongkan = tetap pakai token lama" className="font-mono text-xs" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("channels.cancel")}</Button>
          <Button
            disabled={submitting || name.length < 3 || chatId.length < 1}
            onClick={async () => {
              if (!channel) return
              const ok = await onUpdate(channel.notif_id, {
                name,
                chat_id: chatId,
                ...(botToken.trim() ? { bot_token: botToken.trim() } : {}),
              })
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
