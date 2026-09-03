import { useState } from "react"
import { useTranslation } from "react-i18next"
import {
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Plus,
  Trash2,
  Webhook,
} from "lucide-react"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import {
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
  useApiKeyScopes,
  type ApiKeyCreateResult,
} from "@/hooks/useApiKeys"
import { useWorkspaceStore } from "@/store/workspace.store"

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return "Never"
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "Just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function formatExpiry(iso: string | null): { text: string; isExpired: boolean } {
  if (!iso) return { text: "No expiry", isExpired: false }
  const expDate = new Date(iso)
  const now = new Date()
  if (expDate <= now) return { text: "Expired", isExpired: true }
  const diff = expDate.getTime() - now.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days > 30) {
    const months = Math.floor(days / 30)
    return { text: `${months}mo left`, isExpired: false }
  }
  if (days > 0) return { text: `${days}d left`, isExpired: false }
  const hours = Math.floor(diff / (1000 * 60 * 60))
  if (hours > 0) return { text: `${hours}h left`, isExpired: false }
  const mins = Math.floor(diff / (1000 * 60))
  return { text: `${mins}m left`, isExpired: false }
}

// ── Key Type Badge ────────────────────────────────────────────────────────────

function KeyTypeBadge({ type }: { type: "web" | "public" }) {
  const { t } = useTranslation("management")
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
        type === "web"
          ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
          : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
      )}
    >
      {type === "web" ? (
        <Webhook className="size-2.5" />
      ) : (
        <KeyRound className="size-2.5" />
      )}
      {t(`api_key.type_${type}`)}
    </span>
  )
}

// ── Expiry Options ───────────────────────────────────────────────────────────

const EXPIRY_OPTIONS = [
  { value: "none", labelKey: "api_key.expiry_none", hours: 0 },
  { value: "1h", labelKey: "api_key.expiry_1h", hours: 1 },
  { value: "1d", labelKey: "api_key.expiry_1d", hours: 24 },
  { value: "7d", labelKey: "api_key.expiry_7d", hours: 24 * 7 },
  { value: "30d", labelKey: "api_key.expiry_30d", hours: 24 * 30 },
  { value: "90d", labelKey: "api_key.expiry_90d", hours: 24 * 90 },
  { value: "180d", labelKey: "api_key.expiry_180d", hours: 24 * 180 },
  { value: "1y", labelKey: "api_key.expiry_1y", hours: 24 * 365 },
]

function getExpiryDate(value: string): string | null {
  const option = EXPIRY_OPTIONS.find((o) => o.value === value)
  if (!option || option.hours === 0) return null
  const date = new Date()
  date.setHours(date.getHours() + option.hours)
  return date.toISOString()
}

// ── Create Dialog ─────────────────────────────────────────────────────────────

interface CreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  wsId: string
}

function CreateDialog({ open, onOpenChange, wsId }: CreateDialogProps) {
  const { t } = useTranslation("management")
  const createKey = useCreateApiKey()
  const { data: scopes } = useApiKeyScopes()

  const [name, setName] = useState("")
  const [selectedScopes, setSelectedScopes] = useState<string[]>([])
  const [rateLimit, setRateLimit] = useState<string>("")
  const [expiryOption, setExpiryOption] = useState<string>("none")
  const [createdKey, setCreatedKey] = useState<ApiKeyCreateResult | null>(null)
  const [showKey, setShowKey] = useState(false)
  const [copied, setCopied] = useState(false)

  // UI hanya untuk public keys — scope yang tersedia hanya yang public
  const availableScopes = scopes
    ? Object.entries(scopes)
        .filter(([, v]) => v.public)
        .map(([k, v]) => ({ key: k, ...v }))
    : []

  const handleSubmit = async () => {
    if (!name.trim()) return

    try {
      const result = await createKey.mutateAsync({
        ws_id: wsId,
        name: name.trim(),
        key_type: "public",
        scopes: selectedScopes.length > 0 ? selectedScopes : undefined,
        rate_limit: rateLimit ? parseInt(rateLimit) : undefined,
        expires_at: getExpiryDate(expiryOption),
      })
      setCreatedKey(result)
    } catch {
      // Error handled by mutation
    }
  }

  const handleCopy = async () => {
    if (!createdKey?.key) return
    await navigator.clipboard.writeText(createdKey.key)
    setCopied(true)
    toast.success(t("api_key.key_copied"))
    setTimeout(() => setCopied(false), 2000)
  }

  const handleClose = () => {
    setName("")
    setSelectedScopes([])
    setRateLimit("")
    setExpiryOption("none")
    setCreatedKey(null)
    setShowKey(false)
    setCopied(false)
    onOpenChange(false)
  }

  const toggleScope = (scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    )
  }

  // Show created key
  if (createdKey) {
    return (
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("api_key.created_title")}</DialogTitle>
            <DialogDescription>{t("api_key.created_description")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
              <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                {t("api_key.key_warning")}
              </p>
            </div>

            <div className="relative">
              <Input
                value={showKey ? createdKey.key : "•".repeat(48)}
                readOnly
                className="font-mono text-sm pr-10"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>

            <Button onClick={handleCopy} className="w-full" variant={copied ? "default" : "outline"}>
              <Copy className="mr-2 size-4" />
              {copied ? t("api_key.copied") : t("api_key.copy_key")}
            </Button>
          </div>

          <DialogFooter>
            <Button onClick={handleClose}>{t("api_key.close")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )
  }

  // Create form
  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("api_key.create_title")}</DialogTitle>
          <DialogDescription>{t("api_key.create_description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label>{t("api_key.name")}</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("api_key.name_placeholder")}
            />
          </div>

          {/* Scopes */}
          <div className="space-y-2">
            <Label>{t("api_key.scopes")}</Label>
            <div className="flex flex-wrap gap-2">
              {availableScopes.map((scope) => (
                <button
                  key={scope.key}
                  type="button"
                  onClick={() => toggleScope(scope.key)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs transition-colors",
                    selectedScopes.includes(scope.key)
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border text-muted-foreground hover:border-primary",
                  )}
                  title={scope.description}
                >
                  {scope.key}
                </button>
              ))}
            </div>
          </div>

          {/* Rate Limit */}
          <div className="space-y-2">
            <Label>{t("api_key.rate_limit")}</Label>
            <Input
              type="number"
              value={rateLimit}
              onChange={(e) => setRateLimit(e.target.value)}
              placeholder="200"
            />
            <p className="text-xs text-muted-foreground">
              {t("api_key.rate_limit_hint")}
            </p>
          </div>

          {/* Expiry */}
          <div className="space-y-2">
            <Label>{t("api_key.expires")}</Label>
            <Select value={expiryOption} onValueChange={setExpiryOption}>
              <SelectTrigger>
                <SelectValue placeholder={t("api_key.expiry_none")} />
              </SelectTrigger>
              <SelectContent>
                {EXPIRY_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {t(opt.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {t("api_key.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={!name.trim() || createKey.isPending}>
            {createKey.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            {t("api_key.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function ApiKeyManager() {
  const { t } = useTranslation("management")
  const { activeWorkspace } = useWorkspaceStore()
  const wsId = activeWorkspace?.id ?? null
  const { data: keys, isLoading } = useApiKeys(wsId)
  const revokeKey = useRevokeApiKey()

  const [createOpen, setCreateOpen] = useState(false)
  const [revokeConfirm, setRevokeConfirm] = useState<string | null>(null)

  const activeKeys = keys?.filter((k) => k.is_active && k.type === "public") ?? []

  if (!wsId) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center">
        <KeyRound className="mx-auto size-8 text-muted-foreground/60" />
        <p className="mt-3 text-sm font-medium">{t("api_key.select_workspace")}</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{t("api_key.title")}</h2>
          <p className="text-sm text-muted-foreground">{t("api_key.description")}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 size-4" />
          {t("api_key.create_new")}
        </Button>
      </div>

      {/* Unified Key Table */}
      {activeKeys.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          {t("api_key.no_keys")}
        </div>
      ) : (
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2.5 text-left font-medium">{t("api_key.type", "Type")}</th>
                <th className="px-4 py-2.5 text-left font-medium">{t("api_key.name")}</th>
                <th className="px-4 py-2.5 text-left font-medium">{t("api_key.scopes")}</th>
                <th className="px-4 py-2.5 text-left font-medium">{t("api_key.rate_limit")}</th>
                <th className="px-4 py-2.5 text-left font-medium">{t("api_key.expires")}</th>
                <th className="px-4 py-2.5 text-left font-medium">{t("api_key.last_used")}</th>
                <th className="px-4 py-2.5 text-right font-medium">{t("api_key.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {activeKeys.map((key) => (
                <tr key={key.id} className="border-b last:border-b-0 hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3">
                    <KeyTypeBadge type={key.type} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium">{key.name}</div>
                    <div className="text-xs text-muted-foreground font-mono">
                      {key.key_prefix}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {key.scopes.map((scope) => (
                        <span
                          key={scope}
                          className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                        >
                          {scope}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{key.rate_limit}/h</td>
                  <td className="px-4 py-3">
                    {(() => {
                      const { text, isExpired } = formatExpiry(key.expires_at)
                      return (
                        <span className={cn(
                          "text-xs",
                          isExpired ? "text-destructive font-medium" : "text-muted-foreground"
                        )}>
                          {text}
                        </span>
                      )
                    })()}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{timeAgo(key.last_used_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setRevokeConfirm(key.id)}
                      className="text-destructive hover:text-destructive"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Dialog */}
      <CreateDialog open={createOpen} onOpenChange={setCreateOpen} wsId={wsId} />

      {/* Revoke Confirmation */}
      <Dialog open={!!revokeConfirm} onOpenChange={() => setRevokeConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("api_key.revoke_title")}</DialogTitle>
            <DialogDescription>{t("api_key.revoke_description")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevokeConfirm(null)}>
              {t("api_key.cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                if (revokeConfirm) {
                  await revokeKey.mutateAsync({ ws_id: wsId, key_id: revokeConfirm })
                  setRevokeConfirm(null)
                }
              }}
            >
              {t("api_key.revoke")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
