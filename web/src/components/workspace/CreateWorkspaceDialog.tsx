import { useEffect, useMemo } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useTranslation } from "react-i18next"
import type { TFunction } from "i18next"
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
import { useCreateWorkspace } from "@/hooks/useWorkspaces"

const makeSchema = (t: TFunction) =>
  z.object({
    name: z.string().min(2, t("create_workspace.validation_name_min")),
  })

type FormValues = z.infer<ReturnType<typeof makeSchema>>

interface CreateWorkspaceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (slug: string) => void
}

/** Dialog buat workspace baru — dipakai di Topbar switcher & Sidebar. */
export function CreateWorkspaceDialog({ open, onOpenChange, onCreated }: CreateWorkspaceDialogProps) {
  const { t } = useTranslation("workspace")
  const schema = useMemo(() => makeSchema(t), [t])
  const createWorkspace = useCreateWorkspace()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "" },
  })

  useEffect(() => {
    if (!open) reset({ name: "" })
  }, [open, reset])

  const onSubmit = async (values: FormValues) => {
    const ws = await createWorkspace.mutateAsync(values.name)
    onOpenChange(false)
    onCreated?.(ws.slug)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("create_workspace.title")}</DialogTitle>
          <DialogDescription>{t("create_workspace.description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="ws-name">{t("create_workspace.name_label")}</Label>
            <Input id="ws-name" placeholder={t("create_workspace.name_placeholder")} {...register("name")} autoFocus />
            {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t("action.cancel", { ns: "common" })}
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? t("create_workspace.creating") : t("create_workspace.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
