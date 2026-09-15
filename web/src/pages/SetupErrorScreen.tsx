import { useEffect } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { SetupStatus } from "@/hooks/useSetupStatus"

/**
 * SetupErrorScreen — Fix #294 (First Launch Setup)
 * Tampil saat backend unreachable, MongoDB mati, atau DATA_ENCRYPTION_KEY
 * tidak valid. Bukan wizard — hanya instruksi perbaikan yang tepat.
 * Feel & scene sama dengan LoginPage (login-scene), stage langsung "lit".
 */
export function SetupErrorScreen({
  kind,
  status,
  onRetry,
}: {
  kind: "unreachable" | "env"
  status: SetupStatus | null
  onRetry: () => void
}) {
  const { t } = useTranslation("setup")

  // Auto-recheck tiap 5 detik — setelah user memperbaiki .env / menyalakan
  // Mongo, halaman pulih sendiri tanpa reload (keputusan: diagnosa + recheck).
  useEffect(() => {
    const id = window.setInterval(onRetry, 5_000)
    return () => window.clearInterval(id)
  }, [onRetry])

  return (
    <div className="login-scene bg-background" data-stage="lit">
      <div className="login-scene__blob login-scene__blob--a" aria-hidden="true" />
      <div className="login-scene__blob login-scene__blob--b" aria-hidden="true" />
      <div className="login-scene__blackout" aria-hidden="true" />

      <div className="login-scene__content">
        <div className="login-scene__card w-full max-w-sm">
          <Card className="w-full max-w-sm">
            <CardHeader className="text-center">
              <CardTitle className="text-xl text-destructive">
                {kind === "unreachable"
                  ? t("error.unreachable_heading")
                  : t("error.env_heading")}
              </CardTitle>
              <CardDescription>
                {kind === "unreachable"
                  ? t("error.unreachable_detail")
                  : t("error.env_detail")}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {kind === "unreachable" && (
                <ErrorCard
                  title={t("error.unreachable_heading")}
                  fix={t("error.unreachable_detail")}
                />
              )}

              {status && !status.mongodb.connected && (
                <ErrorCard
                  title={t("error.mongo.title")}
                  detail={status.mongodb.error ?? undefined}
                  fix={t("error.mongo.fix")}
                  command={t("error.command_mongosh")}
                />
              )}
              {status && !status.encryption_key.set && (
                <ErrorCard
                  title={t("error.enc_key_missing.title")}
                  fix={t("error.enc_key_missing.fix")}
                  command={t("error.command_generate_key")}
                />
              )}
              {status && status.encryption_key.set && !status.encryption_key.valid && (
                <ErrorCard
                  title={t("error.enc_key_invalid.title")}
                  fix={t("error.enc_key_invalid.fix")}
                  command={t("error.command_generate_key")}
                />
              )}

              <p className="text-center text-xs text-muted-foreground">
                {t("error.rechecking")}
              </p>

              <Button variant="outline" className="w-full" onClick={onRetry}>
                {t("error.retry")}
              </Button>

              <p className="text-center text-xs text-muted-foreground">
                {t("error.after_fix")}
              </p>

              <p className="text-center text-[10px] tracking-wide text-muted-foreground/60">
                v{__APP_VERSION__}
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

/**
 * Kartu instruksi perbaikan — dipakai SetupErrorScreen dan Step 1 wizard.
 */
export function ErrorCard({
  title,
  detail,
  fix,
  command,
}: {
  title: string
  detail?: string
  fix: string
  command?: string
}) {
  return (
    <div className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
      <p className="text-sm font-medium text-destructive">{title}</p>
      {detail && (
        <p className="break-words font-mono text-xs text-muted-foreground">{detail}</p>
      )}
      <p className="text-xs text-muted-foreground">{fix}</p>
      {command && (
        <pre className="overflow-x-auto rounded bg-muted px-3 py-2 text-xs text-foreground">
          {command}
        </pre>
      )}
    </div>
  )
}
