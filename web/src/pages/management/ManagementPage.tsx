import { useEffect } from "react"
import { useTranslation } from "react-i18next"
import { useSearchParams } from "react-router-dom"
import { Database, FileText, KeyRound, Radio, ShieldAlert } from "lucide-react"
import { ServiceLibrary } from "@/components/management/ServiceLibrary"
import { ApiKeyForm } from "@/components/management/ApiKeyForm"
import { KnowledgeManager } from "@/components/management/KnowledgeManager"
import { MemoryViewer } from "@/components/management/MemoryViewer"
import { ObservabilityTargets } from "@/components/workspace/ObservabilityTargets"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

const TABS = [
  { id: "services", icon: Database },
  { id: "knowledge", icon: FileText },
  { id: "stacks", icon: Radio },
  { id: "apikeys", icon: KeyRound },
  { id: "memory", icon: ShieldAlert },
] as const

type TabId = (typeof TABS)[number]["id"]

/**
 * ManagementPage (/management) — admin global.
 * Fix #58: tab Docs + Knowledge diKONSOLIDASI jadi satu tab "Knowledge"
 * (sub-view Grounding Sistem / Knowledge Tenant). /management?tab=docs → redirect.
 */
export function ManagementPage() {
  const { t } = useTranslation("management")
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = (searchParams.get("tab") ?? "services") as TabId

  // Backward-compat: ?tab=docs (lama) → tab=knowledge&view=grounding
  useEffect(() => {
    if (searchParams.get("tab") === "docs") {
      setSearchParams({ tab: "knowledge", view: "grounding" }, { replace: true })
    }
  }, [searchParams, setSearchParams])

  if (user?.role !== "admin") {
    return (
      <div className="p-8">
        <div className="mx-auto max-w-md rounded-lg border border-dashed p-8 text-center">
          <ShieldAlert className="mx-auto size-8 text-muted-foreground/60" />
          <p className="mt-3 text-sm font-medium">Akses ditolak</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Panel management hanya untuk admin.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl p-6 md:p-8">
      <h1 className="text-xl font-semibold tracking-tight">{t("page.title")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t("page.subtitle")}</p>

      {/* Tab bar */}
      <div className="mt-6 flex flex-wrap gap-1 border-b pb-px">
        {TABS.map((tb) => (
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
            {t(`tabs.${tb.id}`)}
          </button>
        ))}
      </div>

      <div className="space-y-10 pt-6">
        {tab === "services" && <ServiceLibrary />}
        {tab === "stacks" && <ObservabilityTargets />}
        {tab === "apikeys" && <ApiKeyForm />}
        {tab === "knowledge" && <KnowledgeManager />}
        {tab === "memory" && <MemoryViewer />}
      </div>
    </div>
  )
}