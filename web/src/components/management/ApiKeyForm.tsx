import { useState } from "react"
import { useTranslation } from "react-i18next"
import { HardDrive, KeyRound, Loader2, Pencil, PlugZap, Plus, Trash2, Zap } from "lucide-react"
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
import { useQueryClient } from "@tanstack/react-query"
import { cn } from "@/lib/utils"
import { api, apiErrorMessage } from "@/lib/api"
import { useLlmConfig, useUpdateLlm, useDeleteLlmProvider } from "@/hooks/useManagement"

const PROVIDERS = [
  { id: "openai", label: "OpenAI" },
  { id: "openrouter", label: "OpenRouter" },
  { id: "google", label: "Google AI (Gemini)" },
  { id: "opencode", label: "OpenCode" },
  { id: "claude", label: "Claude (Anthropic)" },
] as const

/** Default base URL per provider — single source of truth di FE untuk auto-fill.
 *  Selaras dengan default di `services/llm_factory.py` backend. Tetap bisa diedit manual. */
const DEFAULT_BASE_URLS: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  openrouter: "https://openrouter.ai/api/v1",
  google: "https://generativelanguage.googleapis.com/v1beta/openai",
  opencode: "https://opencode.ai/zen/v1",
  claude: "https://api.anthropic.com/v1",
}

/** Chip hasil uji koneksi — solid, tema-aware (hijau sukses / merah gagal).
 *  Pecah pesan panjang ke baris baru (break-words + whitespace-pre-line) sehingga
 *  badge mengikuti lebar modal — tidak melebar, tidak terpotong. */
function TestResultChip({ text }: { text: string }) {
  const ok = text.startsWith("✅")
  return (
    <div
      title={text}
      className={cn(
        "max-w-full whitespace-pre-line break-words rounded-md px-2.5 py-1 font-mono text-[11px]",
        ok ? "bg-status-resolved text-status-resolved-fg" : "bg-destructive text-destructive-foreground",
      )}
    >
      {text}
    </div>
  )
}

/** Badge solid "AKTIF" — penanda item yang sedang dipakai. */
function ActiveBadge({ label = "Aktif" }: { label?: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary-foreground">
      <Zap className="size-2.5" /> {label}
    </span>
  )
}

/**
 * Tab API Keys — BYOK (Fix #54): provider/model/key/base_url MURNI DB (encrypted).
 * Halaman = LIST kredensial yang sudah ditambahkan (ringkas); penambahan/editing
 * lewat MODAL dengan pilih provider. Pola sama untuk LLM dan Embedding.
 */
export function ApiKeyForm() {
  const { t } = useTranslation("management")
  const { data, isLoading } = useLlmConfig()
  const update = useUpdateLlm()
  // Invalidate cache react-query setelah test — supaya badge toolCalling di baris
  // langsung update (bukan cuma chip lokal yang hilang saat reload).
  const qc = useQueryClient()

  const [testing, setTesting] = useState<"llm" | "embed" | null>(null)
  const [lastTest, setLastTest] = useState<"llm" | "embed" | null>(null)
  const [testResult, setTestResult] = useState<string | null>(null)
  // Test koneksi tersimpan langsung dari baris list — tanpa buka modal
  const [rowTesting, setRowTesting] = useState<string | null>(null)
  const [rowResult, setRowResult] = useState<{ id: string; text: string } | null>(null)
  // Delete provider — hook WAJIB di atas sebelum early-return (Rules of Hooks)
  const delMutation = useDeleteLlmProvider()
  const [deleting, setDeleting] = useState<string | null>(null)

  const runSavedTest = async (
    id: string,
    kind: "llm" | "embed",
    ep: string,
    mdl: string,
  ) => {
    if (!ep || !mdl) return
    setRowTesting(id)
    setRowResult(null)
    try {
      // apiKey/baseUrl kosong → backend pakai nilai TERsimpan utk provider ini
      const { data: res } = await api.post(
        kind === "llm" ? "/config/llm/test" : "/config/llm/test-embedding",
        { provider: ep, model: mdl, baseUrl: "", apiKey: "" },
      )
      if (res.ok) {
        let resultText = `✅ OK · ${res.latency_ms}ms` + (res.dim ? ` · dim=${res.dim}` : "")
        // After connectivity test succeeds for LLM, also run tool-calling test
        if (kind === "llm") {
          try {
            const { data: tcRes } = await api.post(
              "/config/llm/test-tool-calling",
              { provider: ep, model: mdl, baseUrl: "", apiKey: "" },
            )
            if (tcRes.ok) {
              const tcIcon = tcRes.supports_tool_calling ? "✓" : "✗"
              const tcLabel = tcRes.supports_tool_calling ? "Tool Calling" : "No Tool Calling"
              resultText += ` · ${tcIcon} ${tcLabel}`
              // Backend persist flag + invalidate cache server; refresh data
              // di sini supaya badge baris langsung terlihat (bukan setelah reload).
              qc.invalidateQueries({ queryKey: ["config", "llm"] })
            }
          } catch {
            // Tool calling test failed — don't block connectivity result
          }
        }
        setRowResult({ id, text: resultText })
        // TC gagal pun tetap refresh — flag bisa berubah ke false.
        qc.invalidateQueries({ queryKey: ["config", "llm"] })
      } else {
        setRowResult({ id, text: `❌ ${res.error ?? "failed"}` })
      }
    } catch (e) {
      setRowResult({ id, text: `❌ ${apiErrorMessage(e, t("apikeys.test_failed_fallback"))}` })
    } finally {
      setRowTesting(null)
    }
  }

  // Modal LLM (tambah/edit kredensial provider)
  const [llmModal, setLlmModal] = useState<{
    mode: "add" | "edit"
    provider: string
    name: string
    baseUrl: string
    key: string
    model: string
    // Custom provider fields (used when provider starts with 'custom-')
    providerId?: string
  } | null>(null)
  // Modal Embedding (konfigurasi embedding provider)
  const [embModal, setEmbModal] = useState<{ provider: string; model: string; maxChars: number } | null>(null)

  if (isLoading || !data) {
    return <Skeleton className="h-64 w-full rounded-lg" />
  }

  const bUrl = (p: string) => data.baseUrls[p] ?? ""
  const mModel = (p: string) => data.models?.[p] ?? data.model ?? ""
  const isSet = (p: string) => data.keys?.[p] === "set"
  const isActive = (p: string) => data.provider === p
  const availableProviders = PROVIDERS.filter((p) => !isSet(p.id))
  // Custom provider ids — gabungkan dari models/base_urls/names (bisa ada di salah satunya)
  const customIds = Array.from(
    new Set([
      ...Object.keys(data.models || {}),
      ...Object.keys(data.baseUrls || {}),
      ...Object.keys(data.names || {}),
    ]),
  ).filter((id) => id.startsWith("custom-"))
  // SATU list unify: built-in yang sudah di-set + semua custom (bisa >1)
  const providerRows = [
    ...PROVIDERS.filter((p) => isSet(p.id)).map((p) => ({
      id: p.id,
      name: data.names?.[p.id] || p.label,
      isCustom: false,
    })),
    ...customIds.map((id) => ({ id, name: data.names?.[id] || id, isCustom: true })),
  ]
  // Resolusi nama tampilan untuk konfirmasi hapus (builtin label / custom name / id)
  const rowName = (id: string) =>
    data.names?.[id] || PROVIDERS.find((p) => p.id === id)?.label || id

  const runTest = async (
    kind: "llm" | "embed",
    ep: string,
    mdl: string,
    url: string,
    key: string,
  ) => {
    if (!ep || !mdl) return
    setTesting(kind)
    setLastTest(kind)
    setTestResult(null)
    try {
      const { data: res } = await api.post(
        kind === "llm" ? "/config/llm/test" : "/config/llm/test-embedding",
        { provider: ep, model: mdl, baseUrl: url, apiKey: key },
      )
      if (res.ok) {
        let resultText =
          `✅ ${kind === "llm" ? "LLM" : "Embedding"} OK · ${res.latency_ms}ms` +
            (res.dim ? ` · dim=${res.dim}` : "")
        // After connectivity test succeeds for LLM, also run tool-calling test
        if (kind === "llm") {
          try {
            const { data: tcRes } = await api.post(
              "/config/llm/test-tool-calling",
              { provider: ep, model: mdl, baseUrl: "", apiKey: "" },
            )
            if (tcRes.ok) {
              const tcIcon = tcRes.supports_tool_calling ? "✓" : "✗"
              const tcLabel = tcRes.supports_tool_calling ? "Tool Calling" : "No Tool Calling"
              resultText += ` · ${tcIcon} ${tcLabel}`
              qc.invalidateQueries({ queryKey: ["config", "llm"] })
            }
          } catch {
            // Tool calling test failed — don't block connectivity result
          }
        }
        setTestResult(resultText)
        qc.invalidateQueries({ queryKey: ["config", "llm"] })
      } else {
        setTestResult(`❌ ${res.error ?? "gagal"}`)
      }
    } catch (e) {
      setTestResult(`❌ ${apiErrorMessage(e, t("apikeys.test_failed_fallback"))}`)
    } finally {
      setTesting(null)
    }
  }

  const activateProvider = (p: string) => update.mutate({ provider: p })

  // Delete unify: custom → hapus total; built-in → clear credentials (bisa di-add ulang).
  // Konfirmasi pakai AlertDialog (pola yang sama dgn delete di tempat lain), bukan confirm().
  const handleDeleteProvider = (providerId: string) => {
    delMutation.mutate(providerId, {
      onSuccess: () => setDeleting(null),
    })
  }

  const closeLlmModal = () => {
    setLlmModal(null)
    setTestResult(null)
    setLastTest(null)
  }

  const openLlmAdd = () => {
    setTestResult(null)
    setLastTest(null)
    const defaultProvider = availableProviders[0]?.id ?? "custom-openai"
    setLlmModal({
      mode: "add",
      provider: defaultProvider,
      name: "",
      baseUrl: DEFAULT_BASE_URLS[defaultProvider] ?? "",
      key: "",
      model: "",
    })
  }
  // Edit unify: deteksi custom → set providerId supaya saveLlmModal menulis ke id benar.
  // Builtin & custom sekarang satu jalur.
  const openEdit = (providerId: string) => {
    setTestResult(null)
    setLastTest(null)
    setLlmModal({
      mode: "edit",
      provider: providerId,
      providerId: providerId.startsWith("custom-") ? providerId : undefined,
      name: data.names?.[providerId] ?? "",
      baseUrl: bUrl(providerId),
      key: "",
      model: mModel(providerId),
    })
  }

  const saveLlmModal = () => {
    if (!llmModal) return
    const patch: {
      baseUrls?: Record<string, string>
      apiKey?: Record<string, string>
      models?: Record<string, string>
      names?: Record<string, string>
    } = {}

    if (llmModal.mode === "add" && llmModal.provider.startsWith("custom-")) {
      // Generate unique ID using max-based approach
      const typePrefix = llmModal.provider // "custom-openai" or "custom-anthropic"
      const existingIds = Object.keys(data?.models || {}).filter(k => k.startsWith(typePrefix))
      const maxN = existingIds.reduce((max, id) => {
        const num = parseInt(id.split('-').pop() || '0', 10)
        return num > max ? num : max
      }, 0)
      const providerId = `${typePrefix}-${maxN + 1}`
      if (llmModal.baseUrl.trim()) patch.baseUrls = { [providerId]: llmModal.baseUrl.trim() }
      if (llmModal.key.trim().length >= 20) patch.apiKey = { [providerId]: llmModal.key.trim() }
      if (llmModal.model.trim()) patch.models = { [providerId]: llmModal.model.trim() }
      if (llmModal.name.trim()) patch.names = { [providerId]: llmModal.name.trim() }
    } else {
      const targetId = llmModal.providerId || llmModal.provider
      if (llmModal.baseUrl.trim()) patch.baseUrls = { [targetId]: llmModal.baseUrl.trim() }
      if (llmModal.key.trim().length >= 20) patch.apiKey = { [targetId]: llmModal.key.trim() }
      if (llmModal.model.trim()) patch.models = { [targetId]: llmModal.model.trim() }
      if (llmModal.name.trim()) patch.names = { [targetId]: llmModal.name.trim() }
    }
    update.mutate(patch, { onSuccess: () => closeLlmModal() })
  }

  const openEmbAdd = () => {
    setTestResult(null)
    setLastTest(null)
    setEmbModal({
      provider: data.embedding?.provider ?? "openrouter",
      model: data.embedding?.model ?? "",
      maxChars: data.embedding?.maxChars ?? 8000,
    })
  }

  const closeEmbModal = () => {
    setEmbModal(null)
    setTestResult(null)
    setLastTest(null)
  }

  const saveEmbModal = () => {
    if (!embModal || !embModal.model.trim()) return
    update.mutate(
      {
        embedding: {
          mode: "provider",
          provider: embModal.provider,
          model: embModal.model.trim(),
          maxChars: embModal.maxChars,
        },
      },
      { onSuccess: () => closeEmbModal() },
    )
  }

  const activateEmb = (mode: "local" | "provider") => {
    if (mode === "local") {
      update.mutate({ embedding: { mode: "local" } })
    } else if (data.embedding?.mode === "provider") {
      update.mutate({
        embedding: {
          mode: "provider",
          provider: data.embedding.provider ?? "openrouter",
          model: data.embedding.model ?? "",
        },
      })
    }
  }

  // Warning banner when active provider doesn't support tool calling
  const showToolCallingWarning = data?.provider && data?.toolCalling?.[data.provider] === false

  return (
    <div className="max-w-3xl space-y-7">
      {/* Warning: active LLM doesn't support tool calling */}
      {showToolCallingWarning && (
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3">
          <p className="text-sm text-yellow-800 dark:text-yellow-200">
            ⚠️ <strong>Tool calling not supported</strong> — Your active LLM (<code>{data.models?.[data.provider] ?? data.provider}</code>)
            does not support tool calling. This may reduce response accuracy for real-time data queries
            (metrics, logs, K8s). Consider switching to a model with tool-calling support.
          </p>
        </div>
      )}

      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{t("apikeys.title")}</h2>
        <p
          className="mt-1 max-w-2xl text-sm text-muted-foreground"
          dangerouslySetInnerHTML={{ __html: t("apikeys.description") }}
        />
      </div>

      {/* ── LLM: list kredensial + modal tambah/edit ── */}
      <div>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <p
            className="max-w-xl text-xs text-muted-foreground"
            dangerouslySetInnerHTML={{ __html: t("apikeys.per_model_hint") }}
          />
          <Button
            size="sm"
            className="gap-1.5"
            disabled={update.isPending}
            onClick={openLlmAdd}
          >
            <Plus className="size-4" /> {t("apikeys.add_provider")}
          </Button>
        </div>

        {/* List kredensial provider (built-in + custom) */}
        <div className="mt-3 overflow-hidden rounded-xl border bg-background">
          {providerRows.length === 0 ? (
            <div className="flex items-center gap-2 px-4 py-6 text-xs text-muted-foreground">
              <KeyRound className="size-4 shrink-0" />
              {t("apikeys.empty_credentials")}
            </div>
          ) : (
            <ul className="divide-y">
              {providerRows.map((row) => (
                <li key={row.id} className="flex items-center gap-3 px-3 py-2.5">
                  <KeyRound className="size-4 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{row.name}</span>
                      {row.isCustom && (
                        <span className="font-mono text-[10px] text-muted-foreground">{row.id}</span>
                      )}
                      {isActive(row.id) && <ActiveBadge label={t("apikeys.active_llm_badge")} />}
                    </div>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {mModel(row.id) || "-"} · {data.keysMasked[row.id]}
                    </span>
                    <span className="ml-2 inline-flex items-center gap-1 text-[11px]">
                      {data.toolCalling?.[row.id] === true && (
                        <span className="font-mono text-[11px] text-muted-foreground">✓ Tool Calling</span>
                      )}
                      {data.toolCalling?.[row.id] === false && (
                        <span className="font-mono text-[11px] text-muted-foreground">✗ No Tool Calling</span>
                      )}
                      {data.toolCalling?.[row.id] === undefined && (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </span>
                    {rowResult?.id === row.id && !rowTesting && (
                      <div className="mt-1.5">
                        <TestResultChip text={rowResult.text} />
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 text-xs"
                      // Semua provider harus bisa dites. Tanpa key, backend kasih error
                      // "API key belum diisi" — lebih jelas dari tombol grayed-out.
                      disabled={rowTesting !== null || testing !== null}
                      title={t("apikeys.test_saved_title")}
                      onClick={() => runSavedTest(row.id, "llm", row.id, mModel(row.id))}
                    >
                      <PlugZap className={cn("size-3 mr-0.5", rowTesting === row.id && "animate-pulse")} />
                      {rowTesting === row.id ? "…" : "Test"}
                    </Button>
                    {!isActive(row.id) && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 gap-1 text-xs"
                        disabled={update.isPending}
                        onClick={() => activateProvider(row.id)}
                      >
                        <Zap className="size-3" /> {t("apikeys.make_active")}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 text-xs"
                      onClick={() => openEdit(row.id)}
                    >
                      <Pencil className="size-3" /> Edit
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 text-xs text-destructive hover:text-destructive"
                      disabled={delMutation.isPending}
                      aria-label={t("apikeys.delete_label", { name: row.name })}
                      onClick={() => setDeleting(row.id)}
                    >
                      <Trash2 className="size-3" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

      </div>



      {/* ── Embedding (Second Brain) ── */}
      <div className="rounded-xl border bg-background p-4">
        <h3 className="text-sm font-semibold">{t("apikeys.embedding_title")}</h3>
        <p
          className="mt-1 text-xs text-muted-foreground"
          dangerouslySetInnerHTML={{ __html: t("apikeys.embedding_description") }}
        />

        <ul className="mt-3 space-y-2">
          {/* Local Only */}
          <li className="flex items-center gap-3 rounded-lg border px-3 py-2.5">
            <HardDrive className="size-4 shrink-0 text-muted-foreground/70" />
            <div className="min-w-0 flex-1">
              <span className="text-sm font-medium">{t("apikeys.local_only")}</span>
              <span className="ml-2 text-[11px] text-muted-foreground">{t("apikeys.local_only_hint")}</span>
            </div>
            {data.embedding?.mode === "local" ? (
              <ActiveBadge />
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                disabled={update.isPending}
                onClick={() => activateEmb("local")}
              >
                {t("apikeys.activate")}
              </Button>
            )}
          </li>

          {/* Provider embedding */}
          <li className="flex items-center gap-3 rounded-lg border px-3 py-2.5">
            <KeyRound
              className={cn(
                "size-4 shrink-0",
                data.embedding?.mode === "provider" ? "text-primary" : "text-muted-foreground/50",
              )}
            />
            <div className="min-w-0 flex-1">
              {data.embedding?.mode === "provider" ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{t("apikeys.provider_label")}</span>
                    {data.embedding.mode === "provider" && <ActiveBadge />}
                  </div>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {data.embedding.provider} · {data.embedding.model || "-"}
                  </span>
                  {data.embedding.maxChars && (
                    <span className="ml-2 inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {data.embedding.maxChars.toLocaleString()} chars
                    </span>
                  )}
                  {rowResult?.id === "embed-provider" && !rowTesting && (
                    <div className="mt-1.5">
                      <TestResultChip text={rowResult.text} />
                    </div>
                  )}
                </>
              ) : (
                <span className="text-sm text-muted-foreground">
                  {t("apikeys.not_configured")}
                </span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {data.embedding?.mode !== "provider" && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1 text-xs"
                  disabled={update.isPending}
                  onClick={openEmbAdd}
                >
                  <Plus className="size-3" /> {t("apikeys.add")}
                </Button>
              )}
              {data.embedding?.mode === "provider" && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 text-xs"
                    disabled={rowTesting !== null || testing !== null || !data.embedding.model}
                    title={t("apikeys.test_saved_title")}
                    onClick={() =>
                      runSavedTest(
                        "embed-provider",
                        "embed",
                        data.embedding!.provider ?? "openrouter",
                        data.embedding!.model ?? "",
                      )
                    }
                  >
                    <PlugZap className={cn("size-3 mr-0.5", rowTesting === "embed-provider" && "animate-pulse")} />
                    {rowTesting === "embed-provider" ? "…" : "Test"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 text-xs"
                    onClick={openEmbAdd}
                  >
                    <Pencil className="size-3" /> Edit
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    disabled={update.isPending}
                    onClick={() => activateEmb("provider")}
                  >
                    {t("apikeys.activate")}
                  </Button>
                </>
              )}
            </div>
          </li>
        </ul>
      </div>

      {/* ── Modal LLM: tambah / edit kredensial provider ── */}
      <Dialog open={llmModal !== null} onOpenChange={(o) => !o && closeLlmModal()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {llmModal?.mode === "edit"
                ? t("apikeys.llm_modal_edit_title", {
                    provider: llmModal.providerId
                      ? (llmModal.name || llmModal.provider)
                      : (PROVIDERS.find((p) => p.id === llmModal.provider)?.label ?? ""),
                  })
                : t("apikeys.llm_modal_add_title")}
            </DialogTitle>
            <DialogDescription>{t("apikeys.llm_modal_description")}</DialogDescription>
          </DialogHeader>
          {llmModal && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>{t("apikeys.provider_label")}</Label>
                <Select
                  value={llmModal.provider}
                  onValueChange={(v) =>
                    setLlmModal((s) => {
                      if (!s) return s
                      // Auto-fill base URL saat user pilih provider — hanya jika belum
                      // pernah diedit (kosong ATAU masih sama dgn default provider lama).
                      // Ini mencegah overwrite URL custom yang sudah diketik user.
                      const prevDefault = DEFAULT_BASE_URLS[s.provider] ?? ""
                      const shouldAutofill =
                        !s.baseUrl.trim() || s.baseUrl.trim() === prevDefault
                      const newLabel = PROVIDERS.find((p) => p.id === v)?.label ?? ""
                      return {
                        ...s,
                        provider: v,
                        name: s.name.trim() ? s.name : newLabel,
                        baseUrl: shouldAutofill ? (DEFAULT_BASE_URLS[v] ?? "") : s.baseUrl,
                      }
                    })
                  }
                  disabled={llmModal.mode === "edit"}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(llmModal.mode === "add" ? availableProviders : PROVIDERS).map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>
                    ))}
                    {llmModal.mode === "add" && (
                      <>
                        <SelectItem value="custom-openai">OpenAI Compatible (Custom)</SelectItem>
                        <SelectItem value="custom-anthropic">Anthropic Compatible (Custom)</SelectItem>
                      </>
                    )}
                    {llmModal.mode === "edit" && llmModal.provider.startsWith("custom-") && (
                      <SelectItem value={llmModal.provider}>
                        {llmModal.name || data.names?.[llmModal.provider] || llmModal.provider}
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="llm-modal-name">Name</Label>
                <Input
                  id="llm-modal-name"
                  value={llmModal.name}
                  onChange={(e) => setLlmModal((s) => (s ? { ...s, name: e.target.value } : s))}
                  placeholder="Display name for this provider"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="llm-modal-url">{t("apikeys.base_url_label")}</Label>
                <Input
                  id="llm-modal-url"
                  value={llmModal.baseUrl}
                  onChange={(e) => setLlmModal((s) => (s ? { ...s, baseUrl: e.target.value } : s))}
                  placeholder="https://…"
                  className="font-mono text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="llm-modal-key">{t("apikeys.api_key_label")}</Label>
                <Input
                  id="llm-modal-key"
                  type="password"
                  value={llmModal.key}
                  onChange={(e) => setLlmModal((s) => (s ? { ...s, key: e.target.value } : s))}
                  placeholder={t("apikeys.key_placeholder")}
                  className="font-mono text-xs"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="llm-modal-model">{t("apikeys.model_label")}</Label>
                <Input
                  id="llm-modal-model"
                  value={llmModal.model}
                  onChange={(e) => setLlmModal((s) => (s ? { ...s, model: e.target.value } : s))}
                  placeholder={t("apikeys.model_placeholder")}
                  className="font-mono text-xs"
                />
              </div>
              <div className="flex flex-col items-stretch gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    disabled={testing !== null}
                    onClick={() =>
                      runTest(
                        "llm",
                        llmModal.provider,
                        llmModal.model.trim() || mModel(llmModal.provider),
                        llmModal.baseUrl.trim(),
                        llmModal.key.trim(),
                      )
                    }
                  >
                    <PlugZap className={testing === "llm" ? "size-4 animate-pulse" : "size-4"} />
                    {testing === "llm" ? t("apikeys.testing") : t("apikeys.test_connection")}
                  </Button>
                </div>
                {lastTest === "llm" && testResult && !testing && <TestResultChip text={testResult} />}
              </div>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={closeLlmModal}>
              {t("apikeys.cancel")}
            </Button>
            <Button size="sm" disabled={update.isPending} onClick={saveLlmModal}>
              {update.isPending && <Loader2 className="size-4 animate-spin" />}
              {t("apikeys.save")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Modal Embedding: pilih provider + model ── */}
      <Dialog open={embModal !== null} onOpenChange={(o) => !o && closeEmbModal()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("apikeys.emb_modal_title")}</DialogTitle>
            <DialogDescription>{t("apikeys.emb_modal_description")}</DialogDescription>
          </DialogHeader>
          {embModal && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>{t("apikeys.provider_label")}</Label>
                <Select
                  value={embModal.provider}
                  onValueChange={(v) => setEmbModal((s) => (s ? { ...s, provider: v } : s))}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PROVIDERS.map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="emb-modal-model">{t("apikeys.emb_model_label")}</Label>
                <Input
                  id="emb-modal-model"
                  value={embModal.model}
                  onChange={(e) => setEmbModal((s) => (s ? { ...s, model: e.target.value } : s))}
                  placeholder={t("apikeys.emb_model_placeholder")}
                  className="font-mono text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="emb-modal-maxchars">{t("apikeys.emb_max_chars_label")}</Label>
                <Input
                  id="emb-modal-maxchars"
                  type="number"
                  min={256}
                  max={32000}
                  value={embModal.maxChars}
                   onChange={(e) => setEmbModal((s) => (s ? { ...s, maxChars: parseInt(e.target.value) || 8000 } : s))}
                   placeholder="8000"
                  className="font-mono text-xs"
                />
                <p className="text-[0.7rem] text-muted-foreground">
                  {t("apikeys.emb_max_chars_hint")}
                </p>
              </div>
              <div className="flex flex-col items-stretch gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    disabled={testing !== null || !embModal.model.trim()}
                    onClick={() =>
                      runTest("embed", embModal.provider, embModal.model.trim(), bUrl(embModal.provider), "")
                    }
                  >
                    <PlugZap className={testing === "embed" ? "size-4 animate-pulse" : "size-4"} />
                    {testing === "embed" ? t("apikeys.testing") : t("apikeys.test_embedding")}
                  </Button>
                </div>
                {lastTest === "embed" && testResult && !testing && <TestResultChip text={testResult} />}
              </div>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={closeEmbModal}>
              {t("apikeys.cancel")}
            </Button>
            <Button
              size="sm"
              disabled={update.isPending || !embModal?.model.trim()}
              onClick={saveEmbModal}
            >
              {update.isPending && <Loader2 className="size-4 animate-spin" />}
              {t("apikeys.save")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Konfirmasi hapus provider — pola AlertDialog yg sama dgn delete lain */}
      <AlertDialog open={!!deleting} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("apikeys.delete_confirm_title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {deleting?.startsWith("custom-")
                ? t("apikeys.delete_confirm_desc_custom", { name: rowName(deleting ?? "") })
                : t("apikeys.delete_confirm_desc_builtin", { name: rowName(deleting ?? "") })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={delMutation.isPending}
              onClick={() => deleting && handleDeleteProvider(deleting)}
            >
              {t("apikeys.delete_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}