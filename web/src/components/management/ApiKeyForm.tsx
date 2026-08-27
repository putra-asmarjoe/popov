import { useState } from "react"
import { useTranslation } from "react-i18next"
import { HardDrive, KeyRound, Loader2, Pencil, PlugZap, Plus, Zap } from "lucide-react"
import { Button } from "@/components/ui/button"
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
import { cn } from "@/lib/utils"
import { api, apiErrorMessage } from "@/lib/api"
import { useLlmConfig, useUpdateLlm } from "@/hooks/useManagement"

const PROVIDERS = [
  { id: "openai", label: "OpenAI" },
  { id: "openrouter", label: "OpenRouter" },
  { id: "google", label: "Google AI (Gemini)" },
  { id: "opencode", label: "OpenCode Zen" },
] as const

/** Default base URL per provider — single source of truth di FE untuk auto-fill.
 *  Selaras dengan default di `services/llm_factory.py` backend. Tetap bisa diedit manual. */
const DEFAULT_BASE_URLS: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  openrouter: "https://openrouter.ai/api/v1",
  google: "https://generativelanguage.googleapis.com/v1beta/openai",
  opencode: "https://opencode.ai/zen/v1",
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

  const [testing, setTesting] = useState<"llm" | "embed" | null>(null)
  const [lastTest, setLastTest] = useState<"llm" | "embed" | null>(null)
  const [testResult, setTestResult] = useState<string | null>(null)
  // Test koneksi tersimpan langsung dari baris list — tanpa buka modal
  const [rowTesting, setRowTesting] = useState<string | null>(null)
  const [rowResult, setRowResult] = useState<{ id: string; text: string } | null>(null)

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
        setRowResult({
          id,
          text: `✅ OK · ${res.latency_ms}ms` + (res.dim ? ` · dim=${res.dim}` : ""),
        })
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
    baseUrl: string
    key: string
    model: string // Fix #56: model per provider
  } | null>(null)
  // Modal Embedding (konfigurasi embedding provider)
  const [embModal, setEmbModal] = useState<{ provider: string; model: string } | null>(null)

  if (isLoading || !data) {
    return <Skeleton className="h-64 w-full rounded-lg" />
  }

  const bUrl = (p: string) => data.baseUrls[p] ?? ""
  const mModel = (p: string) => data.models?.[p] ?? data.model ?? ""
  const isSet = (p: string) => data.keys[p] === "set"
  const isActive = (p: string) => data.provider === p
  const addedProviders = PROVIDERS.filter((p) => isSet(p.id))
  const availableProviders = PROVIDERS.filter((p) => !isSet(p.id))

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
        setTestResult(
          `✅ ${kind === "llm" ? "LLM" : "Embedding"} OK · ${res.latency_ms}ms` +
            (res.dim ? ` · dim=${res.dim}` : ""),
        )
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

  const closeLlmModal = () => {
    setLlmModal(null)
    setTestResult(null)
    setLastTest(null)
  }

  const openLlmAdd = () => {
    setTestResult(null)
    setLastTest(null)
    const defaultProvider = availableProviders[0]?.id ?? PROVIDERS[0].id
    setLlmModal({
      mode: "add",
      provider: defaultProvider,
      // Auto-fill base URL default untuk provider pilihan — user tetap bisa edit.
      baseUrl: DEFAULT_BASE_URLS[defaultProvider] ?? "",
      key: "",
      model: "",
    })
  }
  const openLlmEdit = (p: string) => {
    setTestResult(null)
    setLastTest(null)
    setLlmModal({ mode: "edit", provider: p, baseUrl: bUrl(p), key: "", model: mModel(p) })
  }

  const saveLlmModal = () => {
    if (!llmModal) return
    const patch: {
      baseUrls?: Record<string, string>
      apiKey?: Record<string, string>
      models?: Record<string, string> // Fix #56
    } = {}
    if (llmModal.baseUrl.trim()) patch.baseUrls = { [llmModal.provider]: llmModal.baseUrl.trim() }
    if (llmModal.key.trim().length >= 20) patch.apiKey = { [llmModal.provider]: llmModal.key.trim() }
    if (llmModal.model.trim()) patch.models = { [llmModal.provider]: llmModal.model.trim() }
    update.mutate(patch, { onSuccess: () => closeLlmModal() })
  }

  const openEmbAdd = () => {
    setTestResult(null)
    setLastTest(null)
    setEmbModal({
      provider: data.embedding?.provider ?? "openrouter",
      model: data.embedding?.model ?? "",
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

  return (
    <div className="max-w-3xl space-y-7">
      {/* Header */}
      <div>
        <p className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
          {t("apikeys.eyebrow")}
        </p>
        <h2 className="mt-1 text-lg font-semibold tracking-tight">API Keys</h2>
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
            disabled={availableProviders.length === 0 || update.isPending}
            onClick={openLlmAdd}
          >
            <Plus className="size-4" /> {t("apikeys.add_provider")}
          </Button>
        </div>

        {/* List kredensial provider */}
        <div className="mt-3 overflow-hidden rounded-xl border bg-background">
          {addedProviders.length === 0 ? (
            <div className="flex items-center gap-2 px-4 py-6 text-xs text-muted-foreground">
              <KeyRound className="size-4 shrink-0" />
              {t("apikeys.empty_credentials")}
            </div>
          ) : (
            <ul className="divide-y">
              {addedProviders.map((p) => (
                <li key={p.id} className="flex items-center gap-3 px-3 py-2.5">
                  <KeyRound className="size-4 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{p.label}</span>
                      {isActive(p.id) && <ActiveBadge label={t("apikeys.active_llm_badge")} />}
                    </div>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {mModel(p.id) || "-"} · {data.keysMasked[p.id]}
                    </span>
                    {rowResult?.id === p.id && !rowTesting && (
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
                      disabled={rowTesting !== null || testing !== null || !isSet(p.id)}
                      title={t("apikeys.test_saved_title")}
                      onClick={() => runSavedTest(p.id, "llm", p.id, mModel(p.id))}
                    >
                      <PlugZap className={cn("size-3 mr-0.5", rowTesting === p.id && "animate-pulse")} />
                      {rowTesting === p.id ? "…" : "Test"}
                    </Button>
                    {!isActive(p.id) && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 gap-1 text-xs"
                        disabled={update.isPending}
                        onClick={() => activateProvider(p.id)}
                      >
                        <Zap className="size-3" /> {t("apikeys.make_active")}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 text-xs"
                      onClick={() => openLlmEdit(p.id)}
                    >
                      <Pencil className="size-3" /> Edit
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
              <span className="text-sm font-medium">Local Only</span>
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
                    <span className="text-sm font-medium">Provider</span>
                    {data.embedding.mode === "provider" && <ActiveBadge />}
                  </div>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {data.embedding.provider} · {data.embedding.model || "-"}
                  </span>
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
                    provider: PROVIDERS.find((p) => p.id === llmModal.provider)?.label ?? "",
                  })
                : t("apikeys.llm_modal_add_title")}
            </DialogTitle>
            <DialogDescription>{t("apikeys.llm_modal_description")}</DialogDescription>
          </DialogHeader>
          {llmModal && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>Provider</Label>
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
                      return {
                        ...s,
                        provider: v,
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
                  </SelectContent>
                </Select>
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
                <Label>Provider</Label>
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
    </div>
  )
}