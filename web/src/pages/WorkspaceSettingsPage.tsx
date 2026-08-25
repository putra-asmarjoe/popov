import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { ArrowLeft, Bell, Database, FolderKanban, Radio, UserPlus, Users } from "lucide-react"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useAuth } from "@/hooks/useAuth"
import { useInviteMember, useRemoveMember, useWorkspaces, useWorkspaceDetail } from "@/hooks/useWorkspaces"
import { apiErrorMessage } from "@/lib/api"
import { cn, formatDate } from "@/lib/utils"
import { WorkspaceKnowledge } from "@/components/workspace/WorkspaceKnowledge"
import { WorkspaceServicesKnowledge } from "@/components/workspace/WorkspaceServicesKnowledge"
import { WorkspaceServiceHierarchy } from "@/components/workspace/WorkspaceServiceHierarchy"
import { ObservabilityTargets } from "@/components/workspace/ObservabilityTargets"
import { NotificationChannels } from "@/components/workspace/NotificationChannels"
import type { WorkspaceMember } from "@/types/workspace"

// Pesan validasi via factory (ikut locale)
const makeInviteSchema = (tInvalidEmail: string) =>
  z.object({
    email: z.string().email(tInvalidEmail),
    role: z.enum(["admin", "member"]),
  })

type InviteValues = z.infer<ReturnType<typeof makeInviteSchema>>

const TABS = [
  { id: "projects", labelKey: "tabs.projects", icon: FolderKanban },
  { id: "services", labelKey: "tabs.services", icon: Database },
  { id: "stacks", labelKey: "tabs.stacks", icon: Radio },
  { id: "notifications", labelKey: "tabs.notifications", icon: Bell },
  { id: "users", labelKey: "tabs.users", icon: Users },
] as const

type TabId = (typeof TABS)[number]["id"]

/**
 * WorkspaceSettingsPage (/w/:wsSlug/settings) — 4 tab:
 * Service (knowledge + services) | Stacks | Notifikasi | Users (tab via ?tab=).
 * Stacks & Notifikasi hanya untuk workspace admin; Knowledge digabung ke dalam tab Service.
 */
export function WorkspaceSettingsPage() {
  const { t } = useTranslation("settings")
  const { wsSlug } = useParams<{ wsSlug: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: workspaces, isLoading: wsLoading } = useWorkspaces()
  const workspace = useMemo(
    () => workspaces?.find((w) => w.slug === wsSlug) ?? null,
    [workspaces, wsSlug],
  )
  const { data: detail, isLoading } = useWorkspaceDetail(workspace?.id ?? null)
  const inviteMember = useInviteMember(workspace?.id ?? null)
  const removeMember = useRemoveMember(workspace?.id ?? null)
  const { user: me } = useAuth()
  const [confirmRemove, setConfirmRemove] = useState<WorkspaceMember | null>(null)

  const myWsRole = useMemo(
    () => detail?.members.find((m) => m.userId === me?.id)?.wsRole ?? null,
    [detail, me],
  )
  const isAdmin = myWsRole === "admin" || detail?.isOwner === true

  // stacks & notifications hanya utk admin — bila tidak berhak fallback ke default
  const rawTab = (searchParams.get("tab") ?? "projects") as TabId
  const adminOnlyTabs: TabId[] = ["stacks", "notifications"]
  const tab: TabId = adminOnlyTabs.includes(rawTab) && !isAdmin ? "projects" : rawTab
  const visibleTabs = TABS.filter((t) => !adminOnlyTabs.includes(t.id) || isAdmin)

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<InviteValues>({
    resolver: zodResolver(makeInviteSchema(t("members_section.validation_invalid_email"))),
    defaultValues: { email: "", role: "member" },
  })

  const onInvite = async (values: InviteValues) => {
    try {
      await inviteMember.mutateAsync(values)
      reset({ email: "", role: "member" })
    } catch (error) {
      // toast sudah ditangani hook; catch agar form tidak reset saat gagal
      void apiErrorMessage(error)
    }
  }

  return (
    <div className="mx-auto max-w-5xl p-6 md:p-8">
      <Button asChild variant="ghost" size="sm" className="-ml-2 mb-4">
        <Link to={`/w/${wsSlug}`}>
          <ArrowLeft className="size-4" /> {t("back")}
        </Link>
      </Button>

      <h1 className="text-xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {t("subtitle", { name: workspace?.name ?? (wsLoading ? t("loading") : "—") })}
      </p>

      {/* Tab bar */}
      <div className="mt-6 flex flex-wrap gap-1 border-b pb-px">
        {visibleTabs.map((tb) => (
          <button
            key={tb.id}
            type="button"
            className={cn(
              "flex cursor-pointer items-center gap-1.5 rounded-t-md border-b-2 px-3 py-2 text-sm outline-none",
              tab === tb.id
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setSearchParams({ tab: tb.id }, { replace: true })}
          >
            <tb.icon className="size-3.5" />
            {t(tb.labelKey)}
          </button>
        ))}
      </div>

      <div className="space-y-8 pt-6">
        {/* FE-8.6: Projects tab pertama — project → service → knowledge */}
        {tab === "projects" && workspace && (
          <WorkspaceServicesKnowledge wsId={workspace.id} isAdmin={!!isAdmin} />
        )}

        {/* Service tab = hierarki registry → RAG → knowledge + knowledge umum workspace */}
        {tab === "services" && workspace && detail && (
          <>
            <WorkspaceServiceHierarchy workspaceId={workspace.id} isAdmin={!!isAdmin} />
            <WorkspaceKnowledge wsId={workspace.id} isAdmin={!!isAdmin} />
          </>
        )}

        {/* Observability stack milik workspace ini (admin saja) */}
        {tab === "stacks" && workspace && isAdmin && (
          <section className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold">{t("stacks_section.title")}</h2>
              <p className="text-xs text-muted-foreground">
                {t("stacks_section.description")}
              </p>
            </div>
            <ObservabilityTargets workspaceId={workspace.id} />
            {/* Fix #41/#45: link project→stack dikelola langsung di kolom "Projects"
                pada daftar ObservabilityTargets di atas (chip + project… / ✕). */}
          </section>
        )}

        {/* Notifikasi milik workspace ini (admin saja) */}
        {tab === "notifications" && workspace && isAdmin && (
          <section className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold">{t("notifications_section.title")}</h2>
              <p className="text-xs text-muted-foreground">
                {t("notifications_section.description")}
              </p>
            </div>
            <NotificationChannels wsId={workspace.id} />
            {/* Fix #47: link project→channel kini inline di kolom Project di atas */}
          </section>
        )}

        {/* Anggota workspace */}
        {tab === "users" && (
          <section className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold">{t("members_section.title")}</h2>
              <p className="text-xs text-muted-foreground">
                {t("members_section.description")}
              </p>
            </div>

            {/* Invite form */}
            {isAdmin && (
              <form
                onSubmit={handleSubmit(onInvite)}
                className="flex flex-wrap items-end gap-2 rounded-lg border p-4"
                noValidate
              >
                <div className="min-w-56 flex-1 space-y-1.5">
                  <Label htmlFor="invite-email">{t("members_section.email_label")}</Label>
                  <Input
                    id="invite-email"
                    type="email"
                    placeholder={t("members_section.email_placeholder")}
                    {...register("email")}
                  />
                  {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label>{t("members_section.role_label")}</Label>
                  <Select
                    value={watch("role")}
                    onValueChange={(v) => setValue("role", v as InviteValues["role"])}
                  >
                    <SelectTrigger className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="member">Member</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Button type="submit" disabled={isSubmitting}>
                  <UserPlus className="size-4" />
                  {isSubmitting ? t("members_section.inviting") : t("members_section.invite")}
                </Button>
              </form>
            )}

            {/* Members table */}
            <div className="overflow-hidden rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("members_table.member")}</TableHead>
                    <TableHead className="hidden sm:table-cell">{t("members_table.ws_role")}</TableHead>
                    <TableHead className="hidden md:table-cell">{t("members_table.joined")}</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {isLoading || !detail ? (
                    [...Array(2)].map((_, i) => (
                      <TableRow key={i}>
                        <TableCell colSpan={4}>
                          <Skeleton className="h-9 w-full" />
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    detail.members.map((member) => {
                      const isOwner = member.userId === detail.ownerId
                      const canRemove =
                        isAdmin && !isOwner && member.userId !== me?.id
                      return (
                        <TableRow key={member.userId}>
                          <TableCell>
                            <div className="flex items-center gap-3">
                              <Avatar className="size-8">
                                <AvatarFallback className="text-xs">
                                  {initials(member.name)}
                                </AvatarFallback>
                              </Avatar>
                              <div className="min-w-0">
                                <p className="truncate text-sm font-medium leading-tight">
                                  {member.name}
                                  {member.userId === me?.id && (
                                    <span className="ml-1.5 text-xs text-muted-foreground">{t("members_table.you")}</span>
                                  )}
                                </p>
                                <p className="truncate text-xs text-muted-foreground">{member.email}</p>
                              </div>
                            </div>
                          </TableCell>
                          <TableCell className="hidden sm:table-cell">
                            {isOwner ? (
                              <Badge>Owner</Badge>
                            ) : (
                              <Badge variant={member.wsRole === "admin" ? "default" : "secondary"} className="capitalize">
                                {member.wsRole}
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                            {formatDate(member.joinedAt)}
                          </TableCell>
                          <TableCell>
                            {canRemove && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-destructive hover:text-destructive"
                                onClick={() => setConfirmRemove(member)}
                              >
                                {t("members_table.remove")}
                              </Button>
                            )}
                          </TableCell>
                        </TableRow>
                      )
                    })
                  )}
                </TableBody>
              </Table>
            </div>
          </section>
        )}
      </div>

      {/* Confirm remove */}
      <AlertDialog open={!!confirmRemove} onOpenChange={(open) => !open && setConfirmRemove(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("remove_confirm.title", { name: confirmRemove?.name ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("remove_confirm.description", { name: confirmRemove?.name ?? "" })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmRemove) removeMember.mutate(confirmRemove.userId)
                setConfirmRemove(null)
              }}
            >
              {t("remove_confirm.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
