import { useTranslation } from "react-i18next"
import { ArrowDown, ArrowUp } from "lucide-react"
import { useLlmUsage } from "@/hooks/useLlmUsage"
import { useLlmConfig } from "@/hooks/useManagement"

/** Section "LLM usage" di Agent Trace panel (Fix #302): baris per-model yang
 *  melayani turn ini (model · provider | jumlah token | latensi | status).
 *  Kehadiran section = balasan ini diproses LLM; turn non-LLM (total_calls 0)
 *  merender null. Juga null saat requestId null agar pesan lawas tanpa id
 *  tetap valid. */
export function LlmUsageSection({ requestId }: { requestId: string | null }) {
  const { t, i18n } = useTranslation("project")
  const { data, isLoading, isError } = useLlmUsage(requestId)
  // Nama tampilan provider dari config LLM (queryKey ["config","llm"]; murah & cache).
  // Fallback ke id raw saat loading atau provider tanpa nama tersimpan.
  const { data: llmConfig } = useLlmConfig()
  const llmNames = llmConfig?.names

  if (!requestId) return null

  if (isLoading) {
    return (
      <section className="space-y-3 border-t pt-3" aria-busy="true">
        <div className="h-20 animate-pulse rounded-lg border bg-muted/40" />
      </section>
    )
  }

  // Gagal memuat (backend down / 5xx / jaringan) → status degraded, bukan
  // skeleton permanen. Kontrak menjamin 200 + total_calls:0 untuk turn
  // non-LLM, jadi jalur ini hanya tercapai pada kegagalan sungguhan.
  if (isError || !data) {
    return (
      <section className="space-y-3 border-t pt-3">
        <p className="text-[11px] text-muted-foreground">{t("chat.trace_no_data")}</p>
      </section>
    )
  }

  const locale = i18n.language === "en" ? "en-US" : "id-ID"
  const fmtInt = (n: number) => n.toLocaleString(locale)
  const fmtLatency = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`)

  // Turn non-LLM (deterministik / cache / gagal sebelum LLM jalan) →
  // total_calls 0 + models kosong. Footer verdict sudah dihapus, jadi
  // disembunyikan sepenuhnya agar tidak ada divider border-t kosong.
  if (data.models.length === 0 || data.total_calls === 0) return null

  return (
    <section className="space-y-3 border-t pt-3">
      {/* Per-model: model · provider | calls | token | latensi | status */}
      {data.models.map((m) => (
        <div
          key={`${m.provider}/${m.model}`}
          className="space-y-1.5 rounded-lg border bg-muted/40 px-3 py-2"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 truncate text-xs font-semibold">
              {llmNames?.[m.provider] || m.provider}
              <span className="font-normal text-muted-foreground"> · {m.model}</span>
            </span>
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
              {fmtLatency(m.total_latency_ms)}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-muted-foreground">
            <span>{t("chat.llm_calls", { count: fmtInt(m.calls) })}</span>
            <span className="inline-flex items-center gap-1">
              <ArrowUp className="size-3" aria-hidden="true" />
              {fmtInt(m.prompt_tokens)}
              <ArrowDown className="size-3" aria-hidden="true" />
              {fmtInt(m.completion_tokens)}
            </span>
          </div>
          {(m.ok > 0 || m.error > 0 || m.timeout > 0) && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
              {m.ok > 0 && (
                <span className="inline-flex items-center gap-1 font-mono text-green-600 dark:text-green-400">
                  <span className="size-1.5 rounded-full bg-green-600 dark:bg-green-400" aria-hidden="true" />
                  {fmtInt(m.ok)} {t("chat.status_ok")}
                </span>
              )}
              {m.error > 0 && (
                <span className="inline-flex items-center gap-1 font-mono text-red-600 dark:text-red-400">
                  <span className="size-1.5 rounded-full bg-red-600 dark:bg-red-400" aria-hidden="true" />
                  {fmtInt(m.error)} {t("chat.status_error")}
                </span>
              )}
              {m.timeout > 0 && (
                <span className="inline-flex items-center gap-1 font-mono text-amber-600 dark:text-amber-400">
                  <span className="size-1.5 rounded-full bg-amber-600 dark:bg-amber-400" aria-hidden="true" />
                  {fmtInt(m.timeout)} {t("chat.status_timeout")}
                </span>
              )}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}
