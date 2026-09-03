import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { PlugZap, Trash2 } from "lucide-react"
import { api, apiErrorMessage } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
import { formatDate } from "@/lib/utils"

interface SourceEntry {
  id: string
  source_type: string
  source_label: string
  signal_count: number
  last_seen_at: string | null
  last_signal_type: string | null
  enabled: boolean
  created_at: string | null
}

/**
 * Tab "Sources" Workspace Settings (Fix #207, roadmap 1C) — registry source
 * eksternal yang pernah kirim signal (deploy-event / ingest/alert) ke workspace ini.
 * Trust: user bisa lihat "dari mana saja Popov menerima data" + enable/disable
 * tanpa menghapus API key.
 */
export function SourceRegistry({ wsId, isAdmin }: { wsId: string; isAdmin: boolean }) {
  const { t } = useTranslation("settings")
  const [sources, setSources] = useState<SourceEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<SourceEntry | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get(`/workspaces/${wsId}/sources`)
      setSources(res.data?.sources ?? [])
    } catch (e) {
      setError(apiErrorMessage(e, t("sources_section.load_error")))
    } finally {
      setLoading(false)
    }
  }, [wsId, t])

  useEffect(() => {
    void load()
  }, [load])

  const toggle = async (s: SourceEntry, enabled: boolean) => {
    setBusy(true)
    try {
      const res = await api.patch(`/workspaces/${wsId}/sources/${s.id}`, { enabled })
      setSources((prev) =>
        prev.map((x) => (x.id === s.id ? { ...x, enabled: res.data?.source?.enabled ?? enabled } : x)),
      )
    } catch (e) {
      setError(apiErrorMessage(e, t("sources_section.toggle_error")))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async () => {
    if (!deleting) return
    setBusy(true)
    try {
      await api.delete(`/workspaces/${wsId}/sources/${deleting.id}`)
      setSources((prev) => prev.filter((x) => x.id !== deleting.id))
      setDeleting(null)
    } catch (e) {
      setError(apiErrorMessage(e, t("sources_section.delete_error")))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {error && (
        <div className="mb-3 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-2">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : sources.length === 0 ? (
        <div className="space-y-3">
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-6 text-center">
            <PlugZap className="size-6 text-muted-foreground/50" />
            <p className="text-sm font-medium">{t("sources_section.empty")}</p>
            <p className="max-w-md text-xs text-muted-foreground/70">
              {t("sources_section.empty_hint")}
            </p>
          </div>

          {/* Panduan langkah pertama (first-time visitor) */}
          <div className="rounded-lg border p-4 text-left">
            <p className="text-xs font-semibold">{t("sources_section.how_title")}</p>
            <ol className="mt-2 space-y-1.5 text-xs text-muted-foreground">
              <li>1. {t("sources_section.how_step1")}</li>
              <li>2. {t("sources_section.how_step2")}</li>
              <li>3. {t("sources_section.how_step3")}</li>
            </ol>
            <div className="mt-3 flex items-center gap-1.5 text-[11px] text-amber-600">
              <span>{t("sources_section.no_token")}</span>
              <a
                href="/management?tab=apikeys"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-amber-700"
              >
                {t("sources_section.create_token_link")}
              </a>
            </div>
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("sources_table.label")}</TableHead>
                <TableHead className="hidden sm:table-cell">{t("sources_table.type")}</TableHead>
                <TableHead>{t("sources_table.count")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("sources_table.last_seen")}</TableHead>
                <TableHead>{t("sources_table.status")}</TableHead>
                {isAdmin && <TableHead className="w-10" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((s) => (
                <TableRow key={s.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium leading-tight">
                        {s.source_label || "—"}
                      </span>
                      {s.last_signal_type && (
                        <Badge variant="secondary" className="text-[10px] capitalize">
                          {s.last_signal_type}
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <span className="text-xs text-muted-foreground">{s.source_type}</span>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs tabular-nums">{s.signal_count}</span>
                  </TableCell>
                  <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                    {s.last_seen_at ? formatDate(s.last_seen_at) : "—"}
                  </TableCell>
                  <TableCell>
                    {isAdmin ? (
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          onClick={() => void toggle(s, !s.enabled)}
                          aria-label={t("sources_table.enable_label", { name: s.source_label || s.id })}
                        >
                          {s.enabled ? t("sources_table.disable") : t("sources_table.enable")}
                        </Button>
                        <span className="text-xs text-muted-foreground">
                          {s.enabled ? t("sources_table.active") : t("sources_table.inactive")}
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        {s.enabled ? t("sources_table.active") : t("sources_table.inactive")}
                      </span>
                    )}
                  </TableCell>
                  {isAdmin && (
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        disabled={busy}
                        onClick={() => setDeleting(s)}
                        aria-label={t("sources_table.delete_label", { name: s.source_label || s.id })}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <AlertDialog open={!!deleting} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("sources_confirm_delete.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("sources_confirm_delete.description", {
                name: deleting?.source_label || deleting?.id || "",
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("action.cancel", { ns: "common" })}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => void onDelete()}
            >
              {t("sources_confirm_delete.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}