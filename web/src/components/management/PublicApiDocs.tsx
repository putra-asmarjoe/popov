import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  Check,
  Copy,
  KeyRound,
  ShieldCheck,
  SquareTerminal,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import {
  usePublicEndpoints,
  type PublicEndpoint,
} from "@/hooks/useApiKeys"

// ── Helpers ───────────────────────────────────────────────────────────────────

const METHOD_STYLES: Record<string, string> = {
  GET: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  POST: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  PATCH: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  PUT: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  DELETE: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
}

function methodStyle(method: string): string {
  return METHOD_STYLES[method] ?? METHOD_STYLES["GET"]
}

function buildCurl(
  origin: string,
  method: string,
  path: string,
  body?: Record<string, unknown>,
): string {
  const lines = [
    `curl -X ${method} "${origin}${path}" \\`,
    `  -H "Authorization: Bearer pk_pub_<YOUR_API_KEY>"`,
    `  -H "Content-Type: application/json"`,
  ]
  if (body && Object.keys(body).length > 0) {
    lines.push(`  -d '${JSON.stringify(body)}'`)
  }
  return lines.join(" \\\n")
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const { t } = useTranslation("management")
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable — ignore
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="inline-flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      {copied ? t("api_docs.copied") : label}
    </button>
  )
}

function CodeBlock({ code, copyLabel }: { code: string; copyLabel: string }) {
  return (
    <div className="relative overflow-hidden rounded-lg border bg-muted/40">
      <div className="absolute right-2 top-2">
        <CopyButton text={code} label={copyLabel} />
      </div>
      <pre className="overflow-x-auto p-4 pt-8 text-xs leading-relaxed">
        <code className="font-mono">{code}</code>
      </pre>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function PublicApiDocs() {
  const { t } = useTranslation("management")
  const { data: endpoints, isLoading } = usePublicEndpoints()

  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const sorted = useMemo(() => endpoints ?? [], [endpoints])

  const selected: PublicEndpoint | undefined =
    sorted.find((e) => `${e.method} ${e.path}` === selectedKey) ?? sorted[0]

  const origin =
    typeof window !== "undefined" ? window.location.origin : ""

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (sorted.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center">
        <SquareTerminal className="mx-auto size-8 text-muted-foreground/60" />
        <p className="mt-3 text-sm font-medium">{t("api_docs.no_endpoints")}</p>
      </div>
    )
  }

  const spec = selected?.spec ?? {}
  const bodyParams = (spec.params ?? []).filter((p) => p.in === "body")
  const pathParams = (spec.params ?? []).filter((p) => p.in !== "body")

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{t("api_docs.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("api_docs.subtitle")}</p>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {t("api_docs.base_url_hint", { url: `${origin}/api/pub/v1` })}
        </p>
      </div>

      {/* Auth banner */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
        <h4 className="flex items-center gap-1.5 text-sm font-medium text-amber-800 dark:text-amber-200">
          <KeyRound className="size-4" />
          {t("api_docs.auth_title")}
        </h4>
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
          {t("api_docs.auth_desc")}
        </p>
        <div className="mt-2 flex items-center gap-2">
          <code className="flex-1 rounded bg-amber-100 px-2 py-1 font-mono text-xs dark:bg-amber-900/50">
            {t("api_docs.auth_code")}
          </code>
          <CopyButton
            text={t("api_docs.auth_code")}
            label={t("api_docs.copy")}
          />
        </div>
      </div>

      {/* Postman-like layout */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[240px_1fr]">
        {/* Sidebar — endpoint list */}
        <nav className="space-y-1 lg:sticky lg:top-4 lg:self-start">
          <p className="px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("api_docs.sidebar_title")}
          </p>
          {sorted.map((ep) => {
            const key = `${ep.method} ${ep.path}`
            const active = selected && key === `${selected.method} ${selected.path}`
            return (
              <button
                key={key}
                type="button"
                onClick={() => setSelectedKey(key)}
                className={cn(
                  "flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-left transition-colors",
                  active
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                <span
                  className={cn(
                    "w-14 shrink-0 rounded px-1.5 py-0.5 text-center font-mono text-[10px] font-bold uppercase",
                    methodStyle(ep.method),
                  )}
                >
                  {ep.method}
                </span>
                <span className="truncate font-mono text-xs">{ep.path.replace("/api/pub/v1", "")}</span>
              </button>
            )
          })}
        </nav>

        {/* Detail panel */}
        {selected ? (
          <div className="min-w-0 space-y-5">
            {/* Method + path header */}
            <div className="rounded-lg border p-4">
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    "rounded px-2 py-1 font-mono text-sm font-bold uppercase",
                    methodStyle(selected.method),
                  )}
                >
                  {selected.method}
                </span>
                <code className="truncate font-mono text-sm font-medium">
                  {selected.path}
                </code>
              </div>

              {spec.summary ? (
                <p className="mt-3 text-sm font-medium">{spec.summary}</p>
              ) : null}
              <p className="mt-1 text-sm text-muted-foreground">
                {selected.description}
              </p>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge variant="secondary" className="gap-1">
                  <ShieldCheck className="size-3" />
                  {t("api_docs.required_scope")}: {selected.scopes.join(", ")}
                </Badge>
                <Badge variant="outline">
                  {t("api_docs.rate_limit")}: {selected.rate_limit}
                  {t("api_docs.per_hour")}
                </Badge>
              </div>
            </div>

            {/* Parameters */}
            <section>
              <h4 className="mb-2 text-sm font-semibold">
                {t("api_docs.params_title")}
              </h4>
              {(pathParams.length > 0 || bodyParams.length > 0) ? (
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/50 text-left">
                        <th className="px-3 py-2 font-medium">{t("api_docs.col_name")}</th>
                        <th className="px-3 py-2 font-medium">{t("api_docs.col_type")}</th>
                        <th className="px-3 py-2 font-medium">{t("api_docs.col_required")}</th>
                        <th className="px-3 py-2 font-medium">{t("api_docs.col_default")}</th>
                        <th className="px-3 py-2 font-medium">{t("api_docs.col_desc")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pathParams.map((p) => (
                        <tr key={`path-${p.name}`} className="border-b last:border-b-0">
                          <td className="px-3 py-2">
                            <span className="flex items-center gap-1.5">
                              <code className="font-mono text-xs">{`{${p.name}}`}</code>
                              <Badge variant="secondary" className="text-[10px]">
                                {t("api_docs.in_path")}
                              </Badge>
                            </span>
                          </td>
                          <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{p.type}</td>
                          <td className="px-3 py-2">
                            {p.required ? (
                              <span className="font-medium text-destructive">{t("api_docs.required")}</span>
                            ) : (
                              <span className="text-muted-foreground">{t("api_docs.optional")}</span>
                            )}
                          </td>
                          <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                            {p.default == null ? "—" : String(p.default)}
                          </td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">{p.description}</td>
                        </tr>
                      ))}
                      {bodyParams.map((p) => (
                        <tr key={`body-${p.name}`} className="border-b last:border-b-0">
                          <td className="px-3 py-2">
                            <span className="flex items-center gap-1.5">
                              <code className="font-mono text-xs">{p.name}</code>
                              <Badge variant="secondary" className="text-[10px]">
                                {t("api_docs.in_body")}
                              </Badge>
                            </span>
                          </td>
                          <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{p.type}</td>
                          <td className="px-3 py-2">
                            {p.required ? (
                              <span className="font-medium text-destructive">{t("api_docs.required")}</span>
                            ) : (
                              <span className="text-muted-foreground">{t("api_docs.optional")}</span>
                            )}
                          </td>
                          <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                            {p.default == null ? "—" : String(p.default)}
                          </td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">{p.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">{t("api_docs.params_none")}</p>
              )}
            </section>

            {/* Request example */}
            <section>
              <h4 className="mb-2 text-sm font-semibold">
                {t("api_docs.request_title")}
              </h4>
              <CodeBlock
                code={buildCurl(
                  origin,
                  selected.method,
                  selected.path,
                  spec.example_request as Record<string, unknown> | undefined,
                )}
                copyLabel={t("api_docs.copy")}
              />
            </section>

            {/* Response example */}
            {spec.example_response ? (
              <section>
                <h4 className="mb-2 text-sm font-semibold">
                  {t("api_docs.response_title")}
                </h4>
                <CodeBlock
                  code={JSON.stringify(spec.example_response, null, 2)}
                  copyLabel={t("api_docs.copy")}
                />
              </section>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}