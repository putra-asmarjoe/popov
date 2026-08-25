import { useEffect, useMemo } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useTranslation } from "react-i18next"
import type { TFunction } from "i18next"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import type { Ticket } from "@/types/ticket"

// Schema factory — pesan validasi via t() agar ikut locale aktif
const makeSchema = (t: TFunction) =>
  z.object({
    title: z.string().min(5, t("form.validation.title_min")),
    description: z.string().min(10, t("form.validation.description_min")),
    kind: z.enum(["business_logic", "infrastructure"]),
    severity: z.enum(["critical", "high", "medium", "low"]),
    environment: z.enum(["production", "staging", "development"]),
    traceId: z
      .string()
      .regex(/^[0-9a-fA-F]{16,64}$/, t("form.validation.trace_hex"))
      .or(z.literal(""))
      .optional(),
    tagsInput: z.string().optional(),
  })

type FormValues = z.infer<ReturnType<typeof makeSchema>>

export interface TicketFormValues {
  title: string
  description: string
  kind: "business_logic" | "infrastructure"
  severity: "critical" | "high" | "medium" | "low"
  environment: "production" | "staging" | "development"
  traceId?: string
  tags?: string[]
}

/** Form tiket — dipakai NewTicketPage (create) & TicketDetail (edit). */
export function TicketForm({
  initial,
  submitting,
  onSubmit,
  submitLabel,
  onCancel,
}: {
  initial?: Partial<Ticket>
  submitting?: boolean
  onSubmit: (values: TicketFormValues) => void
  submitLabel?: string
  onCancel?: () => void
}) {
  const { t } = useTranslation("project")
  const schema = useMemo(() => makeSchema(t), [t])
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: initial?.title ?? "",
      description: initial?.description ?? "",
      kind: initial?.kind ?? "business_logic",
      severity: initial?.severity ?? "medium",
      environment: initial?.environment ?? "production",
      traceId: initial?.traceId ?? "",
      tagsInput: (initial?.tags ?? []).join(", "),
    },
  })

  // Sinkron bila initial berubah (edit tiket lain)
  useEffect(() => {
    setValue("title", initial?.title ?? "")
    setValue("description", initial?.description ?? "")
    setValue("kind", initial?.kind ?? "business_logic")
    setValue("severity", initial?.severity ?? "medium")
    setValue("environment", initial?.environment ?? "production")
    setValue("traceId", initial?.traceId ?? "")
    setValue("tagsInput", (initial?.tags ?? []).join(", "))
  }, [initial, setValue])

  const submit = handleSubmit((values) => {
    onSubmit({
      ...values,
      traceId: values.traceId || undefined,
      tags: (values.tagsInput ?? "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    })
  })

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="ticket-title">{t("form.title_label")}</Label>
        <Input id="ticket-title" placeholder={t("form.title_placeholder")} {...register("title")} autoFocus />
        {errors.title && <p className="text-xs text-destructive">{errors.title.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="ticket-desc">{t("form.description_label")}</Label>
        <Textarea
          id="ticket-desc"
          rows={4}
          placeholder={t("form.description_placeholder")}
          {...register("description")}
        />
        {errors.description && <p className="text-xs text-destructive">{errors.description.message}</p>}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label>Kind</Label>
          <Select value={watch("kind")} onValueChange={(v) => setValue("kind", v as FormValues["kind"])}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="business_logic">{t("ticket.kind.business_logic")}</SelectItem>
              <SelectItem value="infrastructure">{t("ticket.kind.infrastructure")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Severity</Label>
          <Select value={watch("severity")} onValueChange={(v) => setValue("severity", v as FormValues["severity"])}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="critical">{t("ticket.severity.critical")}</SelectItem>
              <SelectItem value="high">{t("ticket.severity.high")}</SelectItem>
              <SelectItem value="medium">{t("ticket.severity.medium")}</SelectItem>
              <SelectItem value="low">{t("ticket.severity.low")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Environment</Label>
          <Select value={watch("environment")} onValueChange={(v) => setValue("environment", v as FormValues["environment"])}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="production">Production</SelectItem>
              <SelectItem value="staging">Staging</SelectItem>
              <SelectItem value="development">Development</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="ticket-trace">{t("form.trace_label")}</Label>
          <Input id="ticket-trace" placeholder="4bf92f3577b34da6…" className="font-mono text-xs" {...register("traceId")} />
          {errors.traceId && <p className="text-xs text-destructive">{errors.traceId.message}</p>}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ticket-tags">{t("form.tags_label")}</Label>
          <Input id="ticket-tags" placeholder="checkout, npe" {...register("tagsInput")} />
        </div>
      </div>

      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t("form.cancel")}
          </Button>
        )}
        <Button type="submit" disabled={submitting}>
          {submitting ? t("form.saving") : (submitLabel ?? t("form.save"))}
        </Button>
      </div>
    </form>
  )
}
