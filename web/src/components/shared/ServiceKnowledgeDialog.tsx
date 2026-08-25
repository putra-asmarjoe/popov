import { lazy, Suspense, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { Eye, FilePlus2, FileText, Pencil, Trash2 } from "lucide-react"
import { api, apiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useCreateKnowledge, useMyLibrary } from "@/hooks/useKnowledge"
import {
  useLinkServiceKnowledge,
  useServiceKnowledge,
  useUnlinkServiceKnowledge,
} from "@/hooks/useServicesLib"
import type { KnowledgeFolder } from "@/types/knowledge"

const MarkdownView = lazy(() =>
  import("@/components/shared/MarkdownView").then((m) => ({ default: m.MarkdownView })),
)

const KNOWLEDGE_FOLDERS: { id: KnowledgeFolder; label: string }[] = [
  { id: "general", label: "Umum" },
  { id: "services", label: "Service" },
  { id: "playbooks", label: "Playbook" },
  { id: "schemas", label: "Schema" },
  { id: "connections", label: "Koneksi" },
  { id: "observability", label: "Observability" },
]

interface EditorState {
  id: string | null // null = create baru (auto-link)
  name: string
  folder: KnowledgeFolder
  content: string
}

/**
 * ServiceKnowledgeDialog — FE-8.1 (shared): kelola knowledge milik satu service.
 * Dipakai di Management (ServiceLibrary) dan Workspace Settings.
 *
 * ATURAN (ketat): pemanggil WAJIB sudah memastikan user = owner service
 * (endpoint /services/library/{id}/knowledge owner-only).
 * - Tulis knowledge baru → masuk library pribadi + OTOMATIS ter-link.
 * - View selalu bisa utk semua dokumen ter-link; Edit/Hapus hanya milik sendiri
 *   (backend 404 bila bukan owner — UI sembunyikan berdasar ownerId).
 */
export function ServiceKnowledgeDialog({
  serviceId,
  serviceLabel,
  meId,
  onClose,
  autoOpenCreate = false,
}: {
  serviceId: string
  serviceLabel?: string
  meId: string
  onClose: () => void
  autoOpenCreate?: boolean
}) {
  const { data: links, isLoading } = useServiceKnowledge(serviceId)
  const { data: myKnowledge } = useMyLibrary()
  const link = useLinkServiceKnowledge(serviceId)
  const unlink = useUnlinkServiceKnowledge(serviceId)
  const createKb = useCreateKnowledge()

  const [showEditor, setShowEditor] = useState(autoOpenCreate)
  const [mode, setMode] = useState<"tulis" | "preview">("tulis")
  const [kName, setKName] = useState("")
  const [kFolder, setKFolder] = useState<KnowledgeFolder>("playbooks")
  const [kContent, setKContent] = useState("")
  const [editing, setEditing] = useState<EditorState | null>(null)
  const [viewDoc, setViewDoc] = useState<{ name: string; content: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const resetEditor = () => {
    setShowEditor(false)
    setEditing(null)
    setKName("")
    setKContent("")
    setMode("tulis")
  }

  const saveNew = () => {
    if (!kName.trim() || !kContent.trim()) return
    createKb.mutate(
      { name: kName, folder: kFolder, content: kContent },
      {
        onSuccess: (created) => {
          link.mutate(created.id, {
            onSuccess: () => {
              toast.success(`"${created.name}" tersimpan & ter-link ke ${serviceLabel ?? "service"}`)
              resetEditor()
            },
            onError: () =>
              toast.info("Dokumen tersimpan di library — buka dialog ini lagi untuk me-link manual"),
          })
        },
      },
    )
  }

  const saveEdit = () => {
    if (!editing?.id || !kName.trim() || !kContent.trim()) return
    api
      .patch(`/knowledge/library/${editing.id}`, {
        name: kName,
        folder: kFolder,
        content: kContent,
      })
      .then(() => {
        toast.success("Dokumen diperbarui — semua pemakai ikut versi baru")
        resetEditor()
      })
      .catch((e) => toast.error(apiErrorMessage(e, "Gagal memperbarui dokumen")))
  }

  const openView = async (knowledgeLibraryId: string, name: string) => {
    try {
      setViewDoc({ name, content: "" })
      const { data } = await api.get(`/knowledge/library/${knowledgeLibraryId}`)
      setViewDoc({ name, content: data.content ?? "" })
    } catch (e) {
      setViewDoc(null)
      toast.error(apiErrorMessage(e, "Dokumen bukan milikmu / tidak ditemukan"))
    }
  }

  const openEdit = async (knowledgeLibraryId: string, fallbackName: string, fallbackFolder: string) => {
    try {
      const { data } = await api.get(`/knowledge/library/${knowledgeLibraryId}`)
      setShowEditor(true)
      setEditing({ id: knowledgeLibraryId, name: data.name ?? fallbackName, folder: data.folder ?? fallbackFolder, content: data.content ?? "" })
      setKName(data.name ?? fallbackName)
      setKFolder((data.folder ?? fallbackFolder) as KnowledgeFolder)
      setKContent(data.content ?? "")
      setMode("tulis")
    } catch (e) {
      toast.error(apiErrorMessage(e, "Hanya pemilik dokumen yang bisa mengedit"))
    }
  }

  const linkable = useMemo(() => {
    const linked = new Set((links ?? []).map((l) => l.knowledgeLibraryId))
    return (myKnowledge ?? []).filter((k) => !linked.has(k.id))
  }, [links, myKnowledge])

  const isEditingExisting = editing !== null

  return (
    <>
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="sm:max-w-3xl overflow-y-auto max-h-[88vh]">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{serviceLabel ?? serviceId} — Knowledge</DialogTitle>
            <DialogDescription>
              Knowledge yang dipakai Popov saat menganalisis insiden service ini.
            </DialogDescription>
          </DialogHeader>

          {/* ── Editor tulis/edit ── */}
          {!showEditor ? (
            <Button size="sm" className="w-full gap-1.5" onClick={() => setShowEditor(true)}>
              <FilePlus2 className="size-4" />
              {isEditingExisting ? "Lanjutkan edit…" : "Tulis knowledge baru untuk service ini"}
            </Button>
          ) : (
            <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold">
                  {isEditingExisting ? (
                    <>Edit <span className="font-mono">{editing?.name}</span></>
                  ) : (
                    <>Knowledge baru → auto-link ke <span className="font-mono">{serviceLabel ?? serviceId}</span></>
                  )}
                </p>
                <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={resetEditor}>
                  Batal
                </Button>
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-36 flex-1 space-y-1">
                  <Label className="text-xs">Nama</Label>
                  <Input
                    className="h-8 font-mono text-xs"
                    placeholder={`runbook-${serviceLabel ?? serviceId}`}
                    value={kName}
                    onChange={(e) => setKName(e.target.value)}
                  />
                </div>
                <Select value={kFolder} onValueChange={(v) => setKFolder(v as KnowledgeFolder)}>
                  <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {KNOWLEDGE_FOLDERS.map((f) => (
                      <SelectItem key={f.id} value={f.id}>{f.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {!isEditingExisting && (
                  <>
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".md"
                      className="hidden"
                      onChange={async (e) => {
                        const f = e.target.files?.[0]
                        if (!f) return
                        setKName(f.name.replace(/\.md$/i, ""))
                        setKContent(await f.text())
                        if (fileRef.current) fileRef.current.value = ""
                      }}
                    />
                    <Button variant="outline" size="sm" className="h-8" onClick={() => fileRef.current?.click()}>
                      .md…
                    </Button>
                  </>
                )}
              </div>
              <div className="flex w-fit rounded-md border p-0.5 text-xs">
                {(["tulis", "preview"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={cn(
                      "rounded px-2.5 py-1 capitalize transition-colors",
                      mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                    onClick={() => setMode(m)}
                  >
                    {m === "tulis" ? "✍️ Tulis" : "👁 Preview"}
                  </button>
                ))}
              </div>
              {mode === "tulis" ? (
                <Textarea
                  rows={10}
                  className="min-h-[220px] max-h-[45vh] resize-y overflow-y-auto font-mono text-xs leading-relaxed"
                  placeholder={"# Runbook…\nLangkah penanganan…"}
                  value={kContent}
                  onChange={(e) => setKContent(e.target.value)}
                />
              ) : (
                <Suspense fallback={<Skeleton className="h-48 w-full" />}>
                  <div className="min-h-[220px] max-h-[45vh] overflow-y-auto rounded-md border bg-background p-3">
                    {kContent.trim()
                      ? <MarkdownView content={kContent} />
                      : <p className="text-sm text-muted-foreground">Belum ada konten.</p>}
                  </div>
                </Suspense>
              )}
              {!isEditingExisting && kContent.length > 0 && kContent.length < 50 && (
                <p className="text-[11px] text-amber-600">
                  Konten minimal 50 karakter ({kContent.length}/50)
                </p>
              )}
              <Button
                size="sm"
                className="w-full"
                disabled={createKb.isPending || link.isPending || !kName.trim() || !kContent.trim()}
                onClick={isEditingExisting ? saveEdit : saveNew}
              >
                {createKb.isPending || link.isPending
                  ? "Menyimpan…"
                  : isEditingExisting
                    ? "Simpan perubahan"
                    : "Simpan & ter-link ke service ini"}
              </Button>
              {(!kName.trim() || !kContent.trim()) && (
                <p className="text-center text-[11px] text-muted-foreground">
                  Isi nama dan konten untuk mengaktifkan tombol simpan.
                </p>
              )}
            </div>
          )}

          {/* ── List ter-link ── */}
          <div className="space-y-1.5">
            <Label className="text-xs">Ter-link ({links?.length ?? 0})</Label>
            {isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : (links ?? []).length === 0 ? (
              <p className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">
                Belum ada knowledge ter-link.
              </p>
            ) : (
              (links ?? []).map((l) => {
                const mine = l.ownerId === meId
                return (
                  <div key={l.id} className="flex items-center gap-2 rounded-lg border px-3 py-1.5">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">{l.name}</span>
                    {!mine && (
                      <span className="shrink-0 text-[10px] text-muted-foreground" title="Milik user lain — hanya bisa dibaca">
                        🔒
                      </span>
                    )}
                    <Button variant="ghost" size="icon" className="size-7" title="Baca"
                      onClick={() => openView(l.knowledgeLibraryId, l.name)}>
                      <Eye className="size-3.5" />
                    </Button>
                    {mine && (
                      <>
                        <Button variant="ghost" size="icon" className="size-7" title="Edit"
                          onClick={() => openEdit(l.knowledgeLibraryId, l.name, l.folder)}>
                          <Pencil className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7 text-destructive hover:text-destructive"
                          title="Lepas dari service"
                          onClick={() => unlink.mutate(l.id)}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </>
                    )}
                  </div>
                )
              })
            )}
          </div>

          {/* ── Picker dari library sendiri ── */}
          {linkable.length > 0 && (
            <div className="space-y-1.5 border-t pt-3">
              <Label className="text-xs">Atau link dari Library Knowledge saya</Label>
              <div className="max-h-40 space-y-1.5 overflow-y-auto">
                {linkable.map((k) => (
                  <button
                    key={k.id}
                    className="flex w-full items-center gap-2.5 rounded-lg border px-3 py-1.5 text-left hover:bg-accent disabled:opacity-50"
                    disabled={link.isPending}
                    onClick={() => link.mutate(k.id)}
                  >
                    <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">{k.name}</span>
                    <Badge variant="secondary" className="text-[10px]">{k.folder}</Badge>
                  </button>
                ))}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* View markdown */}
      <Dialog open={!!viewDoc} onOpenChange={(open) => !open && setViewDoc(null)}>
        <DialogContent className="sm:max-w-4xl overflow-y-auto max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{viewDoc?.name}</DialogTitle>
          </DialogHeader>
          {viewDoc && !viewDoc.content ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <Suspense fallback={<Skeleton className="h-48 w-full" />}>
              <div className="min-h-24 rounded-md border bg-muted/30 p-4">
                <MarkdownView content={viewDoc?.content ?? ""} />
              </div>
            </Suspense>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
