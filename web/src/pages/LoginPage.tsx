import { useEffect, useMemo, useRef, useState } from "react"
import { Navigate, useNavigate } from "react-router-dom"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import type { TFunction } from "i18next"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RiverClam } from "@/components/login/RiverClam"
import { apiErrorMessage } from "@/lib/api"
import { useAuth } from "@/hooks/useAuth"

type Mode = "login" | "register"

// Stage scene sinematik: gelap total → kerang dibuka → halaman menyala.
type SceneStage = "dark" | "lit"

// Satu schema (tipe konsisten) — validasi name hanya saat register.
// Pesan validasi via t() agar ikut locale aktif.
const makeSchema = (mode: Mode, t: TFunction) =>
  z
    .object({
      name: z.string(),
      email: z.string().email(t("validation.invalid_email")),
      password: z.string().min(8, t("validation.password_min")),
    })
    .superRefine((values, ctx) => {
      if (mode === "register" && values.name.trim().length < 2) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["name"],
          message: t("validation.name_min"),
        })
      }
    })

type FormValues = z.infer<ReturnType<typeof makeSchema>>

/**
 * LoginPage — login & registrasi (toggle) dengan scene sinematik:
 * halaman terbuka "mati lampu", user menyentuh kerang sungai di tengah,
 * kerang membuka, cahaya biru-putih mengembang, lalu form login naik
 * dari dalam kerang sementara pencahayaan halaman perlahan menyala.
 * User pertama yang register otomatis admin (backend).
 */
export function LoginPage() {
  const { t } = useTranslation("auth")
  const { isAuthenticated, sessionChecked, login, register } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>("login")
  const [serverError, setServerError] = useState<string | null>(null)
  const emailRef = useRef<HTMLInputElement | null>(null)

  // Reduced motion → lewati sinematik, langsung halaman terang.
  const prefersReducedMotion = useMemo(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    []
  )
  const [stage, setStage] = useState<SceneStage>(prefersReducedMotion ? "lit" : "dark")

  // t berubah identitas saat locale ganti → schema (pesan error) ikut ter-update
  const schema = useMemo(() => makeSchema(mode, t), [mode, t])

  const {
    register: registerField,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", email: "", password: "" },
  })

  // Pisahkan ref email agar bisa digabung dengan ref internal (fokus pasca-scene).
  const { ref: emailFieldRef, ...emailField } = registerField("email")

  // Setelah kerang terbuka & kartu mulai muncul → fokus ke field email.
  useEffect(() => {
    if (stage !== "lit" || prefersReducedMotion) return
    const id = window.setTimeout(() => {
      emailRef.current?.focus({ preventScroll: true })
    }, 700)
    return () => window.clearTimeout(id)
  }, [stage, prefersReducedMotion])

  // Sudah login (dan sesi sudah dicek) → langsung ke app
  if (sessionChecked && isAuthenticated) {
    return <Navigate to="/" replace />
  }

  const onSubmit = async (values: FormValues) => {
    setServerError(null)
    try {
      if (mode === "login") {
        await login(values.email, values.password)
        toast.success(t("login.success_toast"))
      } else {
        await register(values.name ?? "", values.email, values.password)
        toast.success(t("register.success_toast"))
      }
      navigate("/", { replace: true })
    } catch (error) {
      const message = apiErrorMessage(error, t("login.failed_fallback"))
      setServerError(message)
      toast.error(message)
    }
  }

  const lit = stage === "lit"

  return (
    <div className="login-scene bg-background" data-stage={stage}>
      {/* Dekorasi ambient — hanya tampak setelah lampu menyala */}
      <div className="login-scene__blob login-scene__blob--a" aria-hidden="true" />
      <div className="login-scene__blob login-scene__blob--b" aria-hidden="true" />

      {/* Blackout — memudar saat lit, latar bertema tersingkap */}
      <div className="login-scene__blackout" aria-hidden="true" />

      <div className="login-scene__content">
        <div
          className="login-scene__card w-full max-w-sm"
          inert={!lit}
          aria-hidden={!lit}
        >
          <Card className="w-full max-w-sm">
            <CardHeader className="text-center">
              <CardTitle className="text-xl">Popov</CardTitle>
              <CardDescription>
                {mode === "login"
                  ? t("login.description")
                  : t("register.description")}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
                {mode === "register" && (
                  <div className="space-y-1.5">
                    <Label htmlFor="name">{t("field.name_label")}</Label>
                    <Input id="name" placeholder={t("field.name_placeholder")} {...registerField("name")} />
                    {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
                  </div>
                )}

                <div className="space-y-1.5">
                  <Label htmlFor="email">{t("field.email_label")}</Label>
                  <Input
                    id="email"
                    ref={(el) => {
                      emailRef.current = el
                      emailFieldRef(el)
                    }}
                    type="email"
                    placeholder={t("field.email_placeholder")}
                    {...emailField}
                  />
                  {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="password">{t("field.password_label")}</Label>
                  <Input id="password" type="password" placeholder={t("field.password_placeholder")} {...registerField("password")} />
                  {errors.password && <p className="text-xs text-destructive">{errors.password.message}</p>}
                </div>

                {serverError && (
                  <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">{serverError}</p>
                )}

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting
                    ? t("field.processing")
                    : mode === "login"
                      ? t("login.submit")
                      : t("register.submit")}
                </Button>
              </form>

              <p className="mt-4 text-center text-xs text-muted-foreground">
                {mode === "login"
                  ? t("switch.to_register_prompt")
                  : t("switch.to_login_prompt")}{" "}
                <button
                  type="button"
                  className="login-scene__link cursor-pointer font-medium underline-offset-4 hover:underline"
                  onClick={() => {
                    setMode(mode === "login" ? "register" : "login")
                    setServerError(null)
                  }}
                >
                  {mode === "login" ? t("switch.to_register_action") : t("switch.to_login_action")}
                </button>
              </p>

              <p className="mt-3 text-center text-[10px] tracking-wide text-muted-foreground/60">
                v{__APP_VERSION__}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Kerang sungai — tombol pembuka scene */}
        <button
          type="button"
          onClick={() => setStage("lit")}
          aria-label={t("scene.clam_aria")}
          tabIndex={lit ? -1 : 0}
          className="login-scene__clam cursor-pointer rounded-3xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        >
          <span className="login-scene__halo" aria-hidden="true" />
          <span className="login-scene__bloom" aria-hidden="true" />
          <RiverClam />
        </button>

        <p className="login-scene__hint">{t("scene.clam_hint")}</p>
      </div>
    </div>
  )
}
