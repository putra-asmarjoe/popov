import { useEffect, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useTranslation } from "react-i18next"
import type { TFunction } from "i18next"
import { useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Loader2, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RiverClam } from "@/components/login/RiverClam"
import { api, apiErrorMessage } from "@/lib/api"
import { useAuth } from "@/hooks/useAuth"
import type { SetupStatus } from "@/hooks/useSetupStatus"

/**
 * SetupWizard — Fix #294 (First Launch Setup)
 *
 * Adaptive steps:
 * - step="configure" → configure → admin → llm → done (4 steps)
 * - step="admin"     → admin → llm → done (3 steps, .env already good)
 *
 * Feel & scene sama dengan LoginPage (login-scene + RiverClam).
 */

type SceneStage = "dark" | "lit"
type StepId = "configure" | "admin" | "done"

interface SetupWizardProps {
  status: SetupStatus
  /** Titik masuk wizard — "configure" jika .env belum ada, "admin" jika .env sudah OK. */
  initialStep?: StepId
}

export function SetupWizard({ status, initialStep = "configure" }: SetupWizardProps) {
  const { t } = useTranslation("setup")
  const queryClient = useQueryClient()
  const [currentStep, setCurrentStep] = useState<StepId>(initialStep)

  // Adaptive steps: configure needed → 3 dots, admin-only → 2 dots
  const steps: { id: StepId; key: string }[] = useMemo(() => {
    if (status.needs_configuration) {
      return [
        { id: "configure", key: "steps.configure" },
        { id: "admin", key: "steps.admin" },
        { id: "done", key: "steps.done" },
      ]
    }
    return [
      { id: "admin", key: "steps.admin" },
      { id: "done", key: "steps.done" },
    ]
  }, [status.needs_configuration])

  // Reduced motion → lewati sinematik, langsung terang (sama dengan LoginPage).
  const prefersReducedMotion = useMemo(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    []
  )
  const [stage, setStage] = useState<SceneStage>(prefersReducedMotion ? "lit" : "dark")

  // Wizard memandu sendiri: lampu menyala otomatis setelah mount.
  useEffect(() => {
    if (prefersReducedMotion) return
    const id = window.setTimeout(() => setStage("lit"), 600)
    return () => window.clearTimeout(id)
  }, [prefersReducedMotion])

  const goTo = (step: StepId) => setCurrentStep(step)

  const lit = stage === "lit"

  return (
    <div className="login-scene bg-background" data-stage={stage}>
      <div className="login-scene__blob login-scene__blob--a" aria-hidden="true" />
      <div className="login-scene__blob login-scene__blob--b" aria-hidden="true" />
      <div className="login-scene__blackout" aria-hidden="true" />

      <div className="login-scene__content">
        <div className="login-scene__card w-full max-w-sm" inert={!lit} aria-hidden={!lit}>
          <Card className="w-full max-w-sm">
            <CardHeader className="text-center">
              <CardTitle className="text-xl">{t("wizard.title")}</CardTitle>
              <CardDescription>{t("wizard.subtitle")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <StepDots steps={steps} current={currentStep} />

              {currentStep === "configure" && (
                <StepConfigure onSuccess={() => {
                  void queryClient.invalidateQueries({ queryKey: ["setup-status"] })
                  goTo("admin")
                }} />
              )}
              {currentStep === "admin" && (
                <StepAdmin
                  onNext={() => {
                    goTo("done")
                  }}
                />
              )}
              {currentStep === "done" && <StepDone />}

              <p className="text-center text-[10px] tracking-wide text-muted-foreground/60">
                v{__APP_VERSION__}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Kerang dekoratif — scene sudah menyala otomatis, bukan tombol */}
        <div className="login-scene__clam pointer-events-none" aria-hidden="true">
          <RiverClam />
        </div>

        <p className="login-scene__hint">{t("wizard.clam_hint")}</p>
      </div>
    </div>
  )
}

// ── Progress dots (adaptive) ────────────────────────────────────────────────

function StepDots({
  steps,
  current,
}: {
  steps: { id: StepId; key: string }[]
  current: StepId
}) {
  const { t } = useTranslation("setup")
  const currentIndex = steps.findIndex((s) => s.id === current)
  return (
    <div className="flex items-center justify-center gap-1.5" aria-hidden="true">
      {steps.map((step, i) => (
        <div key={step.id} className="flex items-center gap-1.5">
          <span
            title={t(step.key)}
            className={[
              "h-1.5 rounded-full transition-all",
              i < currentIndex
                ? "w-4 bg-primary"
                : i === currentIndex
                  ? "w-6 bg-primary"
                  : "w-4 bg-muted",
            ].join(" ")}
          />
        </div>
      ))}
    </div>
  )
}

// ── Step: Configure (.env) ──────────────────────────────────────────────────

interface ConfigureFormValues {
  mongodb_uri: string
  mongodb_db: string
  jwt_secret: string
  data_encryption_key: string
}

function StepConfigure({ onSuccess }: { onSuccess: () => void }) {
  const { t } = useTranslation("setup")
  const [serverError, setServerError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<ConfigureFormValues>({
    defaultValues: {
      mongodb_uri: "mongodb://localhost:27017",
      mongodb_db: "popovagent",
      jwt_secret: "",
      data_encryption_key: "",
    },
  })

  const onSubmit = async (values: ConfigureFormValues) => {
    setServerError(null)
    setIsSubmitting(true)
    try {
      await api.post("/setup/configure", {
        mongodb_uri: values.mongodb_uri.trim(),
        mongodb_db: values.mongodb_db.trim() || "popovagent",
        jwt_secret: values.jwt_secret.trim(),
        data_encryption_key: values.data_encryption_key.trim(),
      })
      toast.success(t("configure.success"))
      // Invalidate query so SetupGate re-evaluates, then move to admin step
      onSuccess()
    } catch (error) {
      const message = apiErrorMessage(error, t("configure.error"))
      setServerError(message)
      toast.error(message)
    } finally {
      setIsSubmitting(false)
    }
  }

  const generateJwt = () => {
    // Generate 64 hex chars (32 bytes) — matches openssl rand -hex 32
    const arr = new Uint8Array(32)
    crypto.getRandomValues(arr)
    const hex = Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("")
    setValue("jwt_secret", hex, { shouldValidate: false })
  }

  const generateEncKey = () => {
    // Generate 32 bytes base64url — same format as Fernet.generate_key()
    const arr = new Uint8Array(32)
    crypto.getRandomValues(arr)
    const b64 = btoa(String.fromCharCode(...arr))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "")
    setValue("data_encryption_key", b64 + "=", { shouldValidate: false })
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
      <div className="text-center">
        <h2 className="text-lg font-semibold">{t("configure.heading")}</h2>
        <p className="mt-1 text-xs text-muted-foreground">{t("configure.description")}</p>
      </div>

      {/* MongoDB URI */}
      <div className="space-y-1.5">
        <Label htmlFor="cfg-mongo-uri">{t("configure.mongodb_uri.label")}</Label>
        <Input
          id="cfg-mongo-uri"
          placeholder={t("configure.mongodb_uri.placeholder")}
          {...register("mongodb_uri", {
            required: t("configure.mongodb_uri.required"),
          })}
        />
        {errors.mongodb_uri && (
          <p className="text-xs text-destructive">{errors.mongodb_uri.message}</p>
        )}
      </div>

      {/* MongoDB Database */}
      <div className="space-y-1.5">
        <Label htmlFor="cfg-mongo-db">{t("configure.mongodb_db.label")}</Label>
        <Input
          id="cfg-mongo-db"
          placeholder={t("configure.mongodb_db.placeholder")}
          {...register("mongodb_db")}
        />
      </div>

      {/* JWT Secret */}
      <div className="space-y-1.5">
        <Label htmlFor="cfg-jwt">{t("configure.jwt_secret.label")}</Label>
        <div className="flex gap-2">
          <Input
            id="cfg-jwt"
            placeholder={t("configure.jwt_secret.placeholder")}
            className="flex-1"
            {...register("jwt_secret")}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={generateJwt}
            title={t("configure.jwt_secret.generate")}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Data Encryption Key */}
      <div className="space-y-1.5">
        <Label htmlFor="cfg-enc">{t("configure.data_encryption_key.label")}</Label>
        <div className="flex gap-2">
          <Input
            id="cfg-enc"
            placeholder={t("configure.data_encryption_key.placeholder")}
            className="flex-1"
            {...register("data_encryption_key")}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={generateEncKey}
            title={t("configure.data_encryption_key.generate")}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {serverError && (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {serverError}
        </p>
      )}

      <Button type="submit" className="w-full" disabled={isSubmitting}>
        {isSubmitting ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            {t("configure.testing_connection")}
          </>
        ) : (
          t("configure.submit")
        )}
      </Button>
    </form>
  )
}

// ── Step: Admin account ─────────────────────────────────────────────────────

const makeAdminSchema = (t: TFunction) =>
  z.object({
    name: z.string().refine((v) => v.trim().length >= 2, t("validation.name_min", { ns: "auth" })),
    email: z.string().email(t("validation.invalid_email", { ns: "auth" })),
    password: z.string().min(8, t("validation.password_min", { ns: "auth" })),
  })

type AdminFormValues = z.infer<ReturnType<typeof makeAdminSchema>>

function StepAdmin({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation("setup")
  const { register } = useAuth()
  const [serverError, setServerError] = useState<string | null>(null)

  const schema = useMemo(() => makeAdminSchema(t), [t])
  const {
    register: registerField,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AdminFormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", email: "", password: "" },
  })

  const onSubmit = async (values: AdminFormValues) => {
    setServerError(null)
    try {
      await register(values.name, values.email, values.password)
      toast.success(t("admin.success_toast"))
      onNext()
    } catch (error) {
      const message = apiErrorMessage(error, t("admin.failed_fallback"))
      setServerError(message)
      toast.error(message)
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
      <div className="text-center">
        <h2 className="text-lg font-semibold">{t("admin.heading")}</h2>
        <p className="mt-1 text-xs text-muted-foreground">{t("admin.description")}</p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="setup-name">{t("field.name_label", { ns: "auth" })}</Label>
        <Input
          id="setup-name"
          placeholder={t("field.name_placeholder", { ns: "auth" })}
          {...registerField("name")}
        />
        {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="setup-email">{t("field.email_label", { ns: "auth" })}</Label>
        <Input
          id="setup-email"
          type="email"
          placeholder={t("field.email_placeholder", { ns: "auth" })}
          {...registerField("email")}
        />
        {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="setup-password">{t("field.password_label", { ns: "auth" })}</Label>
        <Input
          id="setup-password"
          type="password"
          placeholder={t("field.password_placeholder", { ns: "auth" })}
          {...registerField("password")}
        />
        {errors.password && (
          <p className="text-xs text-destructive">{errors.password.message}</p>
        )}
      </div>

      {serverError && (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {serverError}
        </p>
      )}

      <Button type="submit" className="w-full" disabled={isSubmitting}>
        {isSubmitting ? t("admin.processing") : t("admin.submit")}
      </Button>
    </form>
  )
}

// ── Step: Done ──────────────────────────────────────────────────────────────

function StepDone() {
  const { t } = useTranslation("setup")
  const queryClient = useQueryClient()

  const handleFinish = () => {
    void queryClient.invalidateQueries({ queryKey: ["setup-status"] })
    window.location.replace("/")
  }

  return (
    <div className="space-y-4 text-center">
      <div className="flex justify-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
          <CheckCircle2 className="h-7 w-7 text-primary" />
        </div>
      </div>
      <div>
        <h2 className="text-lg font-semibold">{t("done.heading")}</h2>
        <p className="mt-1 text-xs text-muted-foreground">{t("done.description")}</p>
      </div>
      {/* User sudah ber-token sejak admin step — RootRedirect mendaratkan ke workspace. */}
      <Button className="w-full" onClick={handleFinish}>
        {t("done.open")}
      </Button>
    </div>
  )
}
