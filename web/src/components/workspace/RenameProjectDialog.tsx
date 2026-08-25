import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
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
import { useRenameProject } from "@/hooks/useWorkspaces"
import type { Project } from "@/types/workspace"

interface RenameProjectDialogProps {
  workspaceId: string | null
  project: Project | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Dialog rename nama project — slug & key tidak berubah, jadi URL dan
 * nomor tiket lama tetap valid. Dipakai di WorkspacesPage & ProjectPage.
 */
export function RenameProjectDialog({ workspaceId, project, open, onOpenChange }: RenameProjectDialogProps) {
  const { t } = useTranslation("workspace")
  const rename = useRenameProject(workspaceId)
  const [name, setName] = useState("")

  useEffect(() => {
    if (open && project) setName(project.name)
  }, [open, project])

  const trimmed = name.trim()
  const valid = trimmed.length >= 2 && project != null && trimmed !== project.name

  const submit = async () => {
    if (!project || !valid) return
    await rename.mutateAsync({ projectId: project.id, name: trimmed })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("rename_project.title")}</DialogTitle>
          <DialogDescription>
            {t("rename_project.description", { key: project?.key ?? "" })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="rename-project-name">{t("rename_project.new_name_label")}</Label>
          <Input
            id="rename-project-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder={project?.name}
            autoFocus
          />
          {trimmed.length > 0 && trimmed.length < 2 && (
            <p className="text-xs text-destructive">{t("rename_project.validation_name_min")}</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("action.cancel", { ns: "common" })}
          </Button>
          <Button disabled={!valid || rename.isPending} onClick={submit}>
            {rename.isPending ? t("rename_project.saving") : t("rename_project.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
