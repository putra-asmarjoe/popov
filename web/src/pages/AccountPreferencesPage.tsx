import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { Bot, Check, Clock, Eraser, History, Key, SlidersHorizontal, Sparkles, User, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
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
import { useAuth } from "@/hooks/useAuth"
import {
  useApproveSuggestion,
  useProfile,
  useRejectSuggestion,
  useResetCounters,
  useUpdateProfile,
} from "@/hooks/useProfile"
import { useWorkspaces } from "@/hooks/useWorkspaces"
import { useWorkspaceStore } from "@/store/workspace.store"
import { api } from "@/lib/api"
import type { FormatPreference, PendingSuggestion, Tone, Verbosity } from "@/types/profile"

/**
 * Account Preferences (/account/preferences) — USER_PROFILE_PLAN Phase 2.
 * Profil PER WORKSPACE (D6/D7) — copy wajib menjelaskan preferensi tidak global.
 * Manual fields (D3) + "Popov noticed" ringkas (Q4: top-3) + reset counter.
 * Tabs: Preferences (existing) | Account (username, email, password)
 */
export function AccountPreferencesPage() {
  const { t } = useTranslation("account")
  const { user, setUser } = useAuth()
  const { data: workspaces, isLoading: wsLoading } = useWorkspaces()
  const { activeWorkspace, setActiveWorkspace } = useWorkspaceStore()
  const workspace = activeWorkspace ?? workspaces?.[0] ?? null

  // Profil mengikuti workspace aktif — pindah ws = profil ws lain (bukan hilang).
  const { data: profile, isLoading } = useProfile(workspace?.id ?? null)
  const updateProfile = useUpdateProfile(workspace?.id ?? null)
  const resetCounters = useResetCounters(workspace?.id ?? null)
  const approveSuggestion = useApproveSuggestion(workspace?.id ?? null)
  const rejectSuggestion = useRejectSuggestion(workspace?.id ?? null)
  const [confirmReset, setConfirmReset] = useState(false)

  // Nilai form lokal — sync dari data profil saat berubah
  const [form, setForm] = useState<{
    verbosity: Verbosity | ""
    tone: Tone | ""
    format_preference: FormatPreference | ""
    default_chat_depth: number | ""
  }>({ verbosity: "", tone: "", format_preference: "", default_chat_depth: "" })

  useEffect(() => {
    if (profile) {
      setForm({
        verbosity: profile.verbosity ?? "",
        tone: profile.tone ?? "",
        format_preference: profile.format_preference ?? "",
        default_chat_depth: profile.default_chat_depth ?? "",
      })
    }
  }, [profile])

  // Simpan field saat user pilih (auto-save — langsung PATCH sekali, pola simpel)
  const saveField = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => {
    setForm((f) => ({ ...f, [key]: value }))
    const patch = { [key]: value === "" ? null : value }
    updateProfile.mutate(patch as Parameters<typeof updateProfile.mutate>[0])
  }

  /** Map chip key internal → label human-readable (fix: "investigate:mongo_agent"
   *  jangan tampil mentah di "Popov noticed"). */
  function chipLabel(key: string): string {
    const clean = key.replace(/^(investigate|suggestion):/, "")
    const map: Record<string, string> = {
      status: "Status check",
      reopen: "Reopen ticket",
      close: "Close ticket",
      check_ticket: "Check ticket",
      investigate: "Investigate",
    }
    return map[clean] ?? clean
  }

  // "Popov noticed" — top insight ringkas dari counter (Q4: ringkas, bukan dump)
  const noticed = useMemo(() => {
    if (!profile || profile.interaction_count < 10) return [] as string[]
    const svcs = Object.entries(profile.services_queried)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([s, c]) => t("noticed.service", { service: s, count: c }))
    const chips = Object.entries(profile.chips_clicked)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([k, c]) => t("noticed.chip", { chip: chipLabel(k), count: c }))
    return [...svcs, ...chips]
  }, [profile, t])

  return (
    <div className="mx-auto max-w-3xl p-6 md:p-8">
      {/* Header */}
      <div className="flex items-center gap-2">
        <SlidersHorizontal className="size-4 text-muted-foreground" />
        <h1 className="text-xl font-semibold tracking-tight">{t("title")}</h1>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{t("subtitle")}</p>

      {/* Tabs */}
      <Tabs defaultValue="preferences" className="mt-6">
        <TabsList>
          <TabsTrigger value="preferences" className="gap-1.5">
            <SlidersHorizontal className="size-3.5" />
            {t("tab_preferences")}
          </TabsTrigger>
          <TabsTrigger value="account" className="gap-1.5">
            <User className="size-3.5" />
            {t("tab_account")}
          </TabsTrigger>
        </TabsList>

        {/* Preferences Tab */}
        <TabsContent value="preferences">
          {/* Workspace scope — profil per workspace (D6/D7) */}
          <div className="mb-4 rounded-lg border bg-muted/30 px-4 py-3">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {t("workspace_scope")}
            </Label>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              {wsLoading ? (
                <Skeleton className="h-8 w-48" />
              ) : (
                <Select
                  value={workspace?.id ?? undefined}
                  onValueChange={(id) => {
                    const ws = workspaces?.find((w) => w.id === id)
                    if (ws) setActiveWorkspace(ws)
                  }}
                >
                  <SelectTrigger className="w-56">
                    <SelectValue placeholder={t("workspace_pick")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(workspaces ?? []).map((ws) => (
                      <SelectItem key={ws.id} value={ws.id}>
                        {ws.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">{t("workspace_hint")}</p>
          </div>

          {isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : (
            <>
              {/* Manual preferences */}
              <Card className="p-5">
                <div className="flex items-center gap-2">
                  <SlidersHorizontal className="size-4 text-primary" />
                  <h2 className="text-sm font-semibold">{t("manual_title")}</h2>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{t("manual_hint")}</p>

                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label>{t("field.verbosity")}</Label>
                    <Select value={form.verbosity} onValueChange={(v) => saveField("verbosity", v as Verbosity)}>
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder={t("default")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="concise">{t("verbosity.concise")}</SelectItem>
                        <SelectItem value="standard">{t("verbosity.standard")}</SelectItem>
                        <SelectItem value="detailed">{t("verbosity.detailed")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label>{t("field.tone")}</Label>
                    <Select value={form.tone} onValueChange={(v) => saveField("tone", v as Tone)}>
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder={t("default")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="casual">{t("tone.casual")}</SelectItem>
                        <SelectItem value="formal">{t("tone.formal")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label>{t("field.format_preference")}</Label>
                    <Select
                      value={form.format_preference}
                      onValueChange={(v) => saveField("format_preference", v as FormatPreference)}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder={t("default")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="list">{t("format.list")}</SelectItem>
                        <SelectItem value="paragraph">{t("format.paragraph")}</SelectItem>
                        <SelectItem value="mixed">{t("format.mixed")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label>{t("field.default_chat_depth")}</Label>
                    <Select
                      value={form.default_chat_depth === "" ? "" : String(form.default_chat_depth)}
                      onValueChange={(v) => saveField("default_chat_depth", Number(v))}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder={t("default")} />
                      </SelectTrigger>
                      <SelectContent>
                        {[1, 2, 3, 4, 5].map((n) => (
                          <SelectItem key={n} value={String(n)}>
                            {n} — {t(`depth.${n}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </Card>

              {/* Phase 4: saran batch inferensi — menunggu approve / auto-apply 24 jam */}
              {profile?.pending_suggestion?.status === "pending" && profile.pending_suggestion.fields && (
                <PendingSuggestionCard
                  pending={profile.pending_suggestion}
                  onApprove={() => approveSuggestion.mutate()}
                  onReject={() => rejectSuggestion.mutate()}
                  busy={approveSuggestion.isPending || rejectSuggestion.isPending}
                />
              )}

              {/* Popov noticed */}
              <Card className="mt-4 p-5">
                <div className="flex items-center gap-2">
                  <Bot className="size-4 text-primary" />
                  <h2 className="text-sm font-semibold">{t("noticed_title")}</h2>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{t("noticed_hint")}</p>
                <div className="mt-3">
                  {noticed.length > 0 ? (
                    <ul className="space-y-1.5">
                      {noticed.map((n) => (
                        <li key={n} className="flex items-center gap-2 text-sm">
                          <span className="size-1.5 rounded-full bg-primary/60" />
                          {n}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">{t("noticed_empty")}</p>
                  )}
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 border-t pt-4 sm:grid-cols-4">
                  <div>
                    <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      <History className="size-3" /> {t("stat.interactions")}
                    </p>
                    <p className="mt-0.5 text-xl font-bold tabular-nums">
                      {profile?.interaction_count ?? 0}
                    </p>
                  </div>
                  <div>
                    <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      <Bot className="size-3" /> {t("stat.investigations")}
                    </p>
                    <p className="mt-0.5 text-xl font-bold tabular-nums">
                      {profile?.investigation_count ?? 0}
                    </p>
                  </div>
                  <div>
                    <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      <Clock className="size-3" /> {t("stat.services")}
                    </p>
                    <p className="mt-0.5 text-xl font-bold tabular-nums">
                      {Object.keys(profile?.services_queried ?? {}).length}
                    </p>
                  </div>
                  <div>
                    <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      <SlidersHorizontal className="size-3" /> {t("stat.chips")}
                    </p>
                    <p className="mt-0.5 text-xl font-bold tabular-nums">
                      {Object.keys(profile?.chips_clicked ?? {}).length}
                    </p>
                  </div>
                </div>

                <div className="mt-4 border-t pt-4">
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5 text-muted-foreground"
                    onClick={() => setConfirmReset(true)}
                  >
                    <Eraser className="size-3.5" /> {t("reset_counters")}
                  </Button>
                </div>
              </Card>
            </>
          )}
        </TabsContent>

        {/* Account Tab */}
        <TabsContent value="account">
          <AccountTab user={user} setUser={setUser} />
        </TabsContent>
      </Tabs>

      <p className="mt-6 text-center text-xs text-muted-foreground">
        {t("footer", { email: user?.email ?? "" })}
      </p>

      <AlertDialog open={confirmReset} onOpenChange={(o) => !o && setConfirmReset(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("reset_confirm_title")}</AlertDialogTitle>
            <AlertDialogDescription>{t("reset_confirm_desc")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                resetCounters.mutate(undefined, { onSettled: () => setConfirmReset(false) })
              }}
            >
              {t("reset_confirm_action")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

/** Account tab — username, email, password change */
function AccountTab({
  user,
  setUser,
}: {
  user: { id: string; name: string; email: string } | null
  setUser: (user: any) => void
}) {
  const { t } = useTranslation("account")
  const [name, setName] = useState(user?.name ?? "")
  const [email, setEmail] = useState(user?.email ?? "")
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [saving, setSaving] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)

  // Sync from user when it changes
  useEffect(() => {
    if (user) {
      setName(user.name)
      setEmail(user.email)
    }
  }, [user])

  const handleSaveProfile = async () => {
    if (!name.trim() || name.trim().length < 2) {
      toast.error(t("account.name_too_short"))
      return
    }
    if (!email.trim() || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      toast.error(t("account.invalid_email"))
      return
    }

    setSaving(true)
    try {
      const res = await api.patch("/auth/profile", {
        name: name.trim(),
        email: email.trim().toLowerCase(),
      })
      setUser(res.data.user)
      toast.success(t("account.profile_updated"))
    } catch (err: any) {
      const detail = err.response?.data?.detail
      toast.error(detail || t("account.profile_update_failed"))
    } finally {
      setSaving(false)
    }
  }

  const handleChangePassword = async () => {
    if (!currentPassword) {
      toast.error(t("account.current_password_required"))
      return
    }
    if (!newPassword || newPassword.length < 8) {
      toast.error(t("account.password_too_short"))
      return
    }
    if (newPassword !== confirmPassword) {
      toast.error(t("account.passwords_dont_match"))
      return
    }

    setChangingPassword(true)
    try {
      await api.post("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      })
      setCurrentPassword("")
      setNewPassword("")
      setConfirmPassword("")
      toast.success(t("account.password_changed"))
    } catch (err: any) {
      const detail = err.response?.data?.detail
      toast.error(detail || t("account.password_change_failed"))
    } finally {
      setChangingPassword(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Profile section */}
      <Card className="p-5">
        <div className="flex items-center gap-2">
          <User className="size-4 text-primary" />
          <h2 className="text-sm font-semibold">{t("account.profile_title")}</h2>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{t("account.profile_hint")}</p>

        <div className="mt-4 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="name">{t("account.name")}</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("account.name_placeholder")}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="email">{t("account.email")}</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t("account.email_placeholder")}
            />
          </div>

          <Button onClick={handleSaveProfile} disabled={saving}>
            {saving ? t("account.saving") : t("account.save_profile")}
          </Button>
        </div>
      </Card>

      {/* Password section */}
      <Card className="p-5">
        <div className="flex items-center gap-2">
          <Key className="size-4 text-primary" />
          <h2 className="text-sm font-semibold">{t("account.password_title")}</h2>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{t("account.password_hint")}</p>

        <div className="mt-4 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="currentPassword">{t("account.current_password")}</Label>
            <Input
              id="currentPassword"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder={t("account.current_password_placeholder")}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="newPassword">{t("account.new_password")}</Label>
            <Input
              id="newPassword"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder={t("account.new_password_placeholder")}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="confirmPassword">{t("account.confirm_password")}</Label>
            <Input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder={t("account.confirm_password_placeholder")}
            />
          </div>

          <Button onClick={handleChangePassword} disabled={changingPassword}>
            {changingPassword ? t("account.changing") : t("account.change_password")}
          </Button>
        </div>
      </Card>
    </div>
  )
}

/** Card saran batch inferensi (Phase 4) — user memutuskan sebelum auto-apply 24 jam. */
function PendingSuggestionCard({
  pending,
  onApprove,
  onReject,
  busy,
}: {
  pending: PendingSuggestion
  onApprove: () => void
  onReject: () => void
  busy: boolean
}) {
  const { t } = useTranslation("account")
  const entries = Object.entries(pending.fields ?? {})
  if (entries.length === 0) return null
  return (
    <Card className="mt-4 border-primary/30 bg-primary/[0.03] p-5">
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-primary" />
        <h2 className="text-sm font-semibold">{t("suggestion_title")}</h2>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{t("suggestion_hint")}</p>
      <ul className="mt-3 space-y-1.5">
        {entries.map(([field, value]) => (
          <li key={field} className="flex items-baseline gap-2 text-sm">
            <span className="w-36 shrink-0 text-muted-foreground">{t(`field.${field}`)}</span>
            <span className="font-medium">
              {typeof value === "number"
                ? `${value}/5 — ${t(`depth.${value}`)}`
                : t(`${field}.${String(value)}`)}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex gap-2">
        <Button size="sm" className="gap-1" onClick={onApprove} disabled={busy}>
          <Check className="size-3.5" /> {t("suggestion_approve")}
        </Button>
        <Button size="sm" variant="outline" className="gap-1" onClick={onReject} disabled={busy}>
          <X className="size-3.5" /> {t("suggestion_reject")}
        </Button>
      </div>
    </Card>
  )
}
