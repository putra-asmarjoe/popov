import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useWorkspaceServiceGroups } from "@/hooks/useServicesLib"

interface ServicePickerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Service yang sudah terpilih */
  selected: string[]
  /** Callback saat user simpan */
  onConfirm: (serviceIds: string[]) => void
  pending?: boolean
}

/**
 * Dialog multi-select service dari daftar service yang ter-link ke project.
 * Dari project_service_refs (sama dengan panel workspace service hierarki).
 */
export function ServicePickerDialog({
  open,
  onOpenChange,
  selected,
  onConfirm,
  pending,
}: ServicePickerDialogProps) {
  const { t } = useTranslation("project")
  const { data: groups } = useWorkspaceServiceGroups(null)
  const [picks, setPicks] = useState<Set<string>>(new Set(selected))

  // Sync picks saat dialog buka (selected berubah)
  const [lastOpen, setLastOpen] = useState(false)
  if (open !== lastOpen) {
    setLastOpen(open)
    if (open) setPicks(new Set(selected))
  }

  // Flatten semua service dari semua project dalam workspace
  const allServices = (groups ?? []).flatMap((g) =>
    g.services.map((s) => ({
      serviceId: s.serviceId,
      label: s.label || s.serviceId,
      projectName: g.projectName,
    })),
  )

  const toggle = (id: string) => {
    setPicks((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("service_picker.title")}</DialogTitle>
          <DialogDescription>{t("service_picker.desc")}</DialogDescription>
        </DialogHeader>

        {allServices.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            {t("service_picker.empty")}
          </p>
        ) : (
          <div className="max-h-72 space-y-0.5 overflow-y-auto rounded-md border p-1">
            {allServices.map((svc) => {
              const isChecked = picks.has(svc.serviceId)
              return (
                <label
                  key={svc.serviceId}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted"
                >
                  <input
                    type="checkbox"
                    className="size-3.5 accent-primary"
                    checked={isChecked}
                    onChange={() => toggle(svc.serviceId)}
                  />
                  <span className="min-w-0 flex-1 truncate">{svc.label}</span>
                  <span className="truncate text-[10px] text-muted-foreground">{svc.projectName}</span>
                  {isChecked && <Check className="size-3.5 shrink-0 text-primary" />}
                </label>
              )
            })}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            <X className="mr-1 size-3.5" /> {t("service_picker.cancel")}
          </Button>
          <Button
            size="sm"
            disabled={pending}
            onClick={() => onConfirm(Array.from(picks))}
          >
            {t("service_picker.save")} ({picks.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
