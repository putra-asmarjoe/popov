import { useTranslation } from "react-i18next"
import { useSearchParams } from "react-router-dom"
import { FileText, KeyRound, ShieldAlert, Unlock } from "lucide-react"
import { ApiKeyForm } from "@/components/management/ApiKeyForm"
import { ApiKeyManager } from "@/components/management/ApiKeyManager"
import { KnowledgeManager } from "@/components/management/KnowledgeManager"
import { MemoryViewer } from "@/components/management/MemoryViewer"
import { OnboardingBackStrip } from "@/components/workspace/OnboardingBackStrip"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

const TABS = [
  { id: "knowledge", icon: FileText },
  { id: "apikeys", icon: KeyRound },
  { id: "apitokens", icon: Unlock },
  { id: "memory", icon: ShieldAlert },
] as const

type TabId = (typeof TABS)[number]["id"]

/**
 * ManagementPage (/management) — admin global.
 * Tab "Knowledge" renders Grounding — System (AgentDocsManager) only.
 * Tab "API Keys" renders LLM provider credentials (BYOK).
 * Tab "API Tokens" renders API key management for external integrations.
 * Tab "Memory" renders Second Brain episodes.
 */
export function ManagementPage() {
  const { t } = useTranslation("management")
  const { t: tc } = useTranslation("common")
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = (searchParams.get("tab") ?? "knowledge") as TabId

  if (user?.role !== "admin") {
    return (
      <div className="p-8">
        <div className="mx-auto max-w-md rounded-lg border border-dashed p-8 text-center">
          <ShieldAlert className="mx-auto size-8 text-muted-foreground/60" />
          <p className="mt-3 text-sm font-medium">{tc("notif.access_denied")}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {tc("notif.admin_only")}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl p-6 md:p-8">
      {/* Jalur pulang bila datang dari onboarding checklist */}
      <OnboardingBackStrip backTo="/" />

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
        {tab === "apikeys" && <ApiKeyForm />}
        {tab === "apitokens" && <ApiKeyManager />}
        {tab === "knowledge" && <KnowledgeManager />}
        {tab === "memory" && <MemoryViewer />}
      </div>
    </div>
  )
}
