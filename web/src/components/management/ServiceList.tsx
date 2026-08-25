import { useState } from "react"
import { FileWarning, Pencil, Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useConfigServices, useServiceMutations, type ManagedService } from "@/hooks/useManagement"

/** Tab Services — CRUD service yang dipantau Popov (config JSON + docs detection). */
export function ServiceList() {
  const { data: services, isLoading } = useConfigServices()
  const { create, update, remove } = useServiceMutations()
  const [editing, setEditing] = useState<ManagedService | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Tambah/kurang service cukup dari sini — supervisor & RAG otomatis mengenalinya.
        </p>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> Tambah service
        </Button>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Service</TableHead>
              <TableHead>Collection</TableHead>
              <TableHead className="hidden sm:table-cell">DB</TableHead>
              <TableHead>Docs</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [...Array(4)].map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={5}><Skeleton className="h-8 w-full" /></TableCell>
                </TableRow>
              ))
            ) : (
              (services ?? []).map((s) => (
                <TableRow key={s.service_id}>
                  <TableCell className="font-mono text-xs font-medium">{s.service_id}</TableCell>
                  <TableCell className="font-mono text-xs">{s.collection}</TableCell>
                  <TableCell className="hidden text-xs sm:table-cell">
                    {s.type ? `${s.type}${s.db ? ` · ${s.db}` : ""}` : "default"}
                  </TableCell>
                  <TableCell>
                    {s.has_doc ? (
                      <Badge variant="secondary">ada</Badge>
                    ) : (
                      <span className="flex items-center gap-1 text-xs text-amber-600" title="Buat docs/services/{id}.md agar analisis lebih akurat">
                        <FileWarning className="size-3.5" /> belum
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" className="size-7" onClick={() => setEditing(s)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7 text-destructive hover:text-destructive"
                        onClick={() => { if (confirm(`Hapus service "${s.service_id}"?`)) remove.mutate(s.service_id) }}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <ServiceFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={(values) => create.mutate(values)}
        submitting={create.isPending}
      />
      <ServiceFormDialog
        open={!!editing}
        onOpenChange={(open) => !open && setEditing(null)}
        initial={editing}
        onSubmit={(values) => update.mutate({ service_id: editing!.service_id, ...values })}
        submitting={update.isPending}
      />
    </div>
  )
}

function ServiceFormDialog({
  open,
  onOpenChange,
  initial,
  onSubmit,
  submitting,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  initial?: ManagedService | null
  onSubmit: (values: { service_id?: string; collection: string; type?: string; uri?: string; db?: string }) => void
  submitting: boolean
}) {
  const isEdit = !!initial
  const [serviceId, setServiceId] = useState("")
  const [collection, setCollection] = useState("")
  const [useCustomDb, setUseCustomDb] = useState(false)
  const [type, setType] = useState("mongodb")
  const [uri, setUri] = useState("")
  const [db, setDb] = useState("")

  // Reset saat dialog dibuka dengan data baru
  const [lastOpened, setLastOpened] = useState(false)
  if (open !== lastOpened) {
    setLastOpened(open)
    if (open) {
      setServiceId(initial?.service_id ?? "")
      setCollection(initial?.collection ?? "")
      setUseCustomDb(!!initial?.type)
      setType(initial?.type ?? "mongodb")
      setUri(initial?.uri?.replace("://***@", "://") ?? "")
      setDb(initial?.db ?? "")
    }
  }

  const valid = (isEdit || /^[a-z0-9_\-]{2,64}$/.test(serviceId)) && /^[A-Za-z0-9_\-]{2,64}$/.test(collection) && (!useCustomDb || (uri.length > 8 && db.length >= 1))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${initial?.service_id}` : "Service baru"}</DialogTitle>
          <DialogDescription>
            Service tanpa DB khusus memakai MongoDB default + collection fallback.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="svc-id">Service ID</Label>
            <Input
              id="svc-id"
              value={serviceId}
              onChange={(e) => setServiceId(e.target.value.toLowerCase())}
              disabled={isEdit}
              placeholder="order_service"
              className="font-mono text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="svc-col">Collection</Label>
            <Input
              id="svc-col"
              value={collection}
              onChange={(e) => setCollection(e.target.value)}
              placeholder="logs_order_service"
              className="font-mono text-xs"
            />
          </div>
          <div className="rounded-lg border p-3">
            <Label className="flex cursor-pointer items-center gap-2 text-sm font-normal">
              <input
                type="checkbox"
                checked={useCustomDb}
                onChange={(e) => setUseCustomDb(e.target.checked)}
                className="size-4 accent-primary"
              />
              DB khusus (bukan MongoDB default)
            </Label>
            {useCustomDb && (
              <div className="mt-3 space-y-3">
                <div className="space-y-1.5">
                  <Label>Tipe</Label>
                  <Select value={type} onValueChange={setType}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="mongodb">MongoDB</SelectItem>
                      <SelectItem value="mysql">MySQL</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="svc-uri">URI</Label>
                  <Input id="svc-uri" value={uri} onChange={(e) => setUri(e.target.value)} placeholder="mongodb://…" className="font-mono text-xs" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="svc-db">Database</Label>
                  <Input id="svc-db" value={db} onChange={(e) => setDb(e.target.value)} placeholder="order_db" className="font-mono text-xs" />
                </div>
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Batal</Button>
          <Button
            disabled={!valid || submitting}
            onClick={() => {
              onSubmit({
                ...(isEdit ? {} : { service_id: serviceId }),
                collection,
                ...(useCustomDb ? { type, uri, db } : {}),
              })
              onOpenChange(false)
            }}
          >
            {submitting ? "Menyimpan…" : "Simpan"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
