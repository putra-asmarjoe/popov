import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { Link } from "react-router-dom"
import {
  BellRing,
  BookOpen,
  Boxes,
  CheckCircle2,
  ChevronRight,
  FolderKanban,
  KeyRound,
  RadioTower,
  Sparkles,
  X,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useAuth } from "@/hooks/useAuth"
import { useProjects, useWorkspaceDetail } from "@/hooks/useWorkspaces"
import {
  useLlmConfig,
  useObservabilityTargets,
  useWsRegistryList,
} from "@/hooks/useManagement"
import { useWorkspaceKnowledgeSummary } from "@/hooks/useKnowledge"
import { useWorkspaceChannels } from "@/hooks/useNotificationChannels"
import {
  clearOnboardingProgress,
  dismissOnboarding,
  isOnboardingDismissed,
  saveOnboardingProgress,
} from "@/lib/onboarding-storage"

interface OnboardingChecklistProps {
  wsSlug: string
  /** null saat workspace masih loading — kartu belum dirender */
  workspaceId: string | null
  /** Buka dialog buat-project yang sudah ada di halaman (tanpa navigasi). */
  onCreateProject: () => void
}

interface Row {
  id: string
  icon: LucideIcon
  label: string
  hint: string
  to?: string
  onOpen?: () => void
  done: boolean
  optional?: boolean
}

/**
 * OnboardingChecklist — panduan setup untuk user baru di halaman workspace.
 *
 * Centang otomatis dari data nyata (hook react-query yang sama dengan halaman
 * settings — cache dishare, tanpa state tambahan). Item di luar wewenang user
 * disembunyikan (gate sama seperti halamannya). Dismiss persist per-user per-
 * workspace via lib/onboarding-storage.
 */
export function OnboardingChecklist({ wsSlug, workspaceId, onCreateProject }: OnboardingChecklistProps) {
  const { t } = useTranslation("onboarding")
  const { user: me } = useAuth()
  const { data: detail } = useWorkspaceDetail(workspaceId)
  const [justDismissed, setJustDismissed] = useState(false)

  const userId = me?.id ?? null
  const isGlobalAdmin = me?.role === "admin"
  // Pola sama dgn WorkspacesPage: owner workspace atau member ber-role admin.
  const isWsAdmin =
    detail?.isOwner === true ||
    detail?.members.find((m) => m.userId === me?.id)?.wsRole === "admin"

  const servicesHref = `/w/${wsSlug}/settings?tab=services&from=onboarding`
  const stacksHref = `/w/${wsSlug}/settings?tab=stacks&from=onboarding`
  const notificationsHref = `/w/${wsSlug}/settings?tab=notifications&from=onboarding`

  // Semua query memakai queryKey yang sama dengan pemakai lain → cache dishare.
  const { data: projects, isLoading: projLoading } = useProjects(workspaceId)
  const { data: registry, isLoading: regLoading } = useWsRegistryList(workspaceId)
  const { data: knowledgeSummary, isLoading: summaryLoading } = useWorkspaceKnowledgeSummary(workspaceId)
  const { data: channels, isLoading: chanLoading } = useWorkspaceChannels(workspaceId)
  // Endpoint stacks & LLM keys require_admin global — hanya dipanggil bila berhak.
  const isAdminQueryReady = !!workspaceId && isWsAdmin
  const { data: targets, isLoading: obsLoading } = useObservabilityTargets({
    enabled: isAdminQueryReady,
  })
  const { data: llm, isLoading: llmLoading } = useLlmConfig({
    enabled: !!workspaceId && isGlobalAdmin,
  })

  const initiallyDismissed = useMemo(
    () => (!!userId && !!workspaceId ? isOnboardingDismissed(userId, workspaceId) : false),
    [userId, workspaceId],
  )

  const ready =
    !projLoading &&
    !regLoading &&
    !summaryLoading &&
    !chanLoading &&
    !obsLoading &&
    !llmLoading

  // "Add knowledge" ✓ bila ada knowledge APAPUN workspace: refs, service knowledge, grounding docs.
  const hasAnyKnowledge = knowledgeSummary?.has ?? false

  const rows: Row[] = ready
    ? [
        {
          id: "project",
          icon: FolderKanban,
          label: t("items.project.label"),
          hint: t("items.project.hint"),
          onOpen: onCreateProject,
          done: (projects?.length ?? 0) > 0,
        },
        // Stack & notifikasi = tab admin-only workspace (gate sama dgn Settings).
        ...(isWsAdmin
          ? ([
              {
                id: "stacks",
                icon: RadioTower,
                label: t("items.stacks.label"),
                hint: t("items.stacks.hint"),
                to: stacksHref,
                done: (targets ?? []).some((tg) => tg.workspace_id === workspaceId),
              },
              {
                id: "notifications",
                icon: BellRing,
                label: t("items.notifications.label"),
                hint: t("items.notifications.hint"),
                to: notificationsHref,
                done: (channels?.length ?? 0) > 0,
                optional: true,
              },
            ] as Row[])
          : []),
        {
          id: "services",
          icon: Boxes,
          label: t("items.services.label"),
          hint: t("items.services.hint"),
          to: servicesHref,
          done: (registry?.length ?? 0) > 0,
        },
        {
          id: "knowledge",
          icon: BookOpen,
          label: t("items.knowledge.label"),
          hint: t("items.knowledge.hint"),
          to: servicesHref,
          done: hasAnyKnowledge,
        },
        // Management (LLM keys) = admin global saja (gate sama dgn /management).
        ...(isGlobalAdmin
          ? ([
              {
                id: "llm_keys",
                icon: KeyRound,
                label: t("items.llm_keys.label"),
                hint: t("items.llm_keys.hint"),
                to: "/management?tab=llmtokens&from=onboarding",
                done: !!llm && Object.values(llm.keys ?? {}).some((v) => v === "set"),
              },
              {
                id: "embedding",
                icon: Sparkles,
                label: t("items.embedding.label"),
                hint: t("items.embedding.hint"),
                to: "/management?tab=llmtokens&from=onboarding",
                done: !!llm && llm.embedding?.mode === "provider",
                optional: true,
              },
            ] as Row[])
          : []),
      ]
    : []

  const required = rows.filter((r) => !r.optional)
  const doneCount = required.filter((r) => r.done).length
  const allDone = required.length > 0 && doneCount === required.length

  // Simpan progress terakhir utk strip "kembali ke checklist" di halaman lain.
  // Checklist selesai (semua wajib ✓) → progress dibersihkan: strip tak boleh
  // muncul lagi di halaman mana pun, termasuk tab lama ber-URL from=onboarding.
  // (Semua hook wajib di atas early-return — rules-of-hooks.)
  useEffect(() => {
    if (!ready) return
    if (allDone) clearOnboardingProgress()
    else saveOnboardingProgress(doneCount, required.length)
  }, [ready, allDone, doneCount, required.length])

  if (!workspaceId || initiallyDismissed || justDismissed) return null

  const handleDismiss = () => {
    if (userId) dismissOnboarding(userId, workspaceId)
    clearOnboardingProgress()
    setJustDismissed(true)
  }

  if (!ready) {
    return (
      <Card className="mt-4 p-5">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="mt-3 h-1.5 w-full" />
        <div className="mt-4 space-y-2">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-9 w-full rounded-lg" />
          ))}
        </div>
      </Card>
    )
  }

  // Semua langkah wajib selesai → strip sukses ringkas (bisa ditutup).
  if (allDone) {
    return (
      <Card className="mt-4 border-primary/30 bg-primary/[0.05] p-4">
        <div className="flex items-center gap-3">
          <Sparkles className="size-5 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{t("success_title")}</p>
            <p className="truncate text-xs text-muted-foreground">{t("success_hint")}</p>
          </div>
          <Button variant="ghost" size="icon" className="size-7 shrink-0" aria-label={t("close")} onClick={handleDismiss}>
            <X className="size-4" />
          </Button>
        </div>
      </Card>
    )
  }

  return (
    <Card className="mt-4 border-primary/25 bg-primary/[0.04]">
      <div className="p-5 pb-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-tight">{t("title")}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("subtitle")}</p>
          </div>
          <Badge variant="secondary" className="shrink-0 tabular-nums">
            {t("progress", { done: doneCount, total: required.length })}
          </Badge>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 shrink-0 px-2 text-xs text-muted-foreground"
            onClick={handleDismiss}
          >
            {t("dismiss")}
          </Button>
        </div>

        {/* Progress bar */}
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${required.length ? Math.round((doneCount / required.length) * 100) : 0}%` }}
          />
        </div>

        <ul className="mt-3 space-y-1">
          {rows.map((row) => (
            <li key={row.id}>
              {row.to ? (
                <Link
                  to={row.to}
                  className="flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-muted/50"
                  aria-label={row.label}
                >
                  <RowContent row={row} />
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={row.onOpen}
                  className="flex w-full cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted/50"
                >
                  <RowContent row={row} />
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}

function RowContent({ row }: { row: Row }) {
  const { t } = useTranslation("onboarding")
  const Icon = row.icon
  return (
    <>
      <span
        className={`flex size-8 shrink-0 items-center justify-center rounded-md ${
          row.done ? "bg-primary text-primary-foreground" : "bg-primary/10 text-primary"
        }`}
      >
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium leading-tight">{row.label}</span>
          {row.optional && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px] text-muted-foreground">
              {t("optional_badge")}
            </Badge>
          )}
        </span>
        <span className="block truncate text-xs text-muted-foreground">{row.hint}</span>
      </span>
      {row.done ? (
        <CheckCircle2 className="size-5 shrink-0 text-primary" />
      ) : (
        <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
      )}
    </>
  )
}
