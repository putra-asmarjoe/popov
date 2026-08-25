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
import { useCreateProject } from "@/hooks/useWorkspaces"

const makeSchema = (t: TFunction) =>
  z.object({
    name: z.string().min(2, t("create_project.validation.name_min")),
    key: z
      .string()
      .min(2, t("create_project.validation.key_min"))
      .max(5, t("create_project.validation.key_max"))
      .regex(/^[A-Za-z][A-Za-z0-9]+$/, t("create_project.validation.key_regex")),
  })

type FormValues = z.infer<ReturnType<typeof makeSchema>>

interface CreateProjectDialogProps {
  workspaceId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (key: string) => void
}

/** Dialog buat project baru — dipakai di WorkspacesPage & Sidebar. */
export function CreateProjectDialog({ workspaceId, open, onOpenChange, onCreated }: CreateProjectDialogProps) {
  const { t } = useTranslation("workspace")
  const schema = useMemo(() => makeSchema(t), [t])
  const createProject = useCreateProject(workspaceId)
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", key: "" },
  })

  useEffect(() => {
    if (!open) reset({ name: "", key: "" })
  }, [open, reset])

  const onSubmit = async (values: FormValues) => {
    const project = await createProject.mutateAsync({
      name: values.name,
      key: values.key.toUpperCase(),
    })
    onOpenChange(false)
    onCreated?.(project.slug)
  }

  // Auto-uppercase key saat mengetik
  const keyField = watch("key")
  useEffect(() => {
    if (keyField && keyField !== keyField.toUpperCase()) {
      setValue("key", keyField.toUpperCase())
    }
  }, [keyField, setValue])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("create_project.title")}</DialogTitle>
          <DialogDescription asChild>
            <div dangerouslySetInnerHTML={{ __html: t("create_project.description") }} />
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="project-name">{t("create_project.name_label")}</Label>
            <Input id="project-name" placeholder={t("create_project.name_label")} {...register("name")} autoFocus />
            {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="project-key">{t("create_project.key_label")}</Label>
            <Input id="project-key" placeholder="CORE" className="font-mono uppercase" {...register("key")} />
            {errors.key && <p className="text-xs text-destructive">{errors.key.message}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t("action.cancel", { ns: "common" })}
            </Button>
            <Button type="submit" disabled={isSubmitting || !workspaceId}>
              {isSubmitting ? t("create_project.creating") : t("create_project.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
