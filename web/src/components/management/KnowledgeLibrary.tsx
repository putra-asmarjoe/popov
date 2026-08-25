import { lazy, Suspense, useRef, useState } from "react"
import { toast } from "sonner"
import { BookMarked, Eye, FileText, Link2, Pencil, Trash2, Upload } from "lucide-react"
import { api, apiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  fetchKnowledgeUsage,
  useCreateKnowledge,
  useDeleteKnowledge,
  useMyLibrary,
  useUpdateKnowledge,
} from "@/hooks/useKnowledge"
import type { KnowledgeFolder, KnowledgeItem, KnowledgeUsage } from "@/types/knowledge"

const MarkdownView = lazy(() => import("@/components/shared/MarkdownView"))

const FOLDERS: { id: KnowledgeFolder; label: string }[] = [
  { id: "general", label: "Umum" },
  { id: "services", label: "Service" },
  { id: "playbooks", label: "Playbook" },
  { id: "schemas", label: "Schema" },
  { id: "connections", label: "Koneksi" },
  { id: "observability", label: "Observability" },
]

interface EditorState {
  item: KnowledgeItem | null // null = create baru
  name: string
  folder: KnowledgeFolder
  content: string
}

/**
 * Tab Knowledge (/management) — FE-7: Library Pribadi.
 * Dokumen milik uploader saja; dipakai ulang dengan me-link ke workspace.
 */
export function KnowledgeLibrary() {
  const { data: items, isLoading } = useMyLibrary()
  const create = useCreateKnowledge()
  const update = useUpdateKnowledge()
  const remove = useDeleteKnowledge()
  const fileRef = useRef<HTMLInputElement>(null)

  const [category, setCategory] = useState<KnowledgeFolder>("general")
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [editorMode, setEditorMode] = useState<"tulis" | "preview">("tulis")
  const [confirmDelete, setConfirmDelete] = useState<{
    item: KnowledgeItem
    workspaces?: KnowledgeUsage[]
  } | null>(null)
  const [preview, setPreview] = useState<{ item: KnowledgeItem; content: string } | null>(null)

  const all = items ?? []
  const filtered = all.filter((i) => i.folder === category)

  // View: baca dokumen dalam render Markdown rapi (bukan mentah)
  const openPreview = async (item: KnowledgeItem) => {
    try {
      setPreview({ item, content: "" }) // buka dialog dulu (loading state)
      const { data } = await api.get(`/knowledge/library/${item.id}`)
      setPreview({ item, content: data.content ?? "" })
    } catch (e) {
      setPreview(null)
      toast.error(apiErrorMessage(e, "Gagal memuat dokumen"))
    }
  }

  const openCreate = () => {
    setEditorMode("tulis")
    setEditor({ item: null, name: "", folder: category, content: "" })
  }
  const openEdit = (item: KnowledgeItem) => {
    // konten diambil ulang via detail? library list tidak membawa content → fetch usage+content
    void fetchContentAndOpen(item)
  }

  const fetchContentAndOpen = async (item: KnowledgeItem) => {
    try {
      const { data } = await api.get(`/knowledge/library/${item.id}`)
      setEditorMode("tulis")
      setEditor({
        item,
        name: data.name ?? item.name,
        folder: data.folder ?? item.folder,
        content: data.content ?? "",
      })
    } catch {
      setEditor({ item, name: item.name, folder: item.folder, content: "" })
    }
  }

  const onFile = async (file: File | undefined) => {
    if (!file || !editor) return
    const text = await file.text()
    setEditor({ ...editor, name: file.name.replace(/\.md$/i, ""), content: text })
    if (fileRef.current) fileRef.current.value = ""
  }

  const save = () => {
    if (!editor) return
    if (editor.item) {
      update.mutate(
        { id: editor.item.id, name: editor.name, folder: editor.folder, content: editor.content },
        { onSuccess: () => setEditor(null) },
      )
    } else {
      create.mutate(
        { name: editor.name, folder: editor.folder, content: editor.content },
        { onSuccess: () => setEditor(null) },
      )
    }
  }

  const askDelete = async (item: KnowledgeItem) => {
    let workspaces: KnowledgeUsage[] | undefined
    try {
      workspaces = await fetchKnowledgeUsage(item.id)
    } catch {
      workspaces = undefined
    }
    setConfirmDelete({ item, workspaces })
  }

  if (isLoading) return <Skeleton className="h-64 w-full rounded-lg" />

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Knowledge Service</h2>
          <p className="text-xs text-muted-foreground">
            Detailing bagaimana sebuah service bekerja: business logic, collection map,
            hubungan antar service, playbook insiden. Milik Anda — di-link ke
            workspace/service sebagai <strong>konteks tambahan</strong> analisis
            (tak memengaruhi routing).
          </p>
        </div>
        <Button size="sm" className="gap-1.5" onClick={openCreate}>
          <Upload className="size-4" /> Tulis / Upload .md
        </Button>
      </div>

      {/* Kategori (penyusunan by kategori — pola sama dgn Grounding) */}
      <div className="flex flex-wrap gap-1">
        {FOLDERS.map((f) => {
          const count = all.filter((i) => i.folder === f.id).length
          return (
            <button
              key={f.id}
              type="button"
              className={cn(
                "flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                category === f.id
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setCategory(f.id)}
            >
              {f.label}
              <span className={cn("text-[10px]", category === f.id ? "opacity-80" : "opacity-50")}>
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* List dokumen kategori terpilih */}
      <div className="overflow-hidden rounded-lg border">
        {all.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-10 text-center text-muted-foreground">
            <BookMarked className="size-8 opacity-40" />
            <p className="text-sm">Belum ada knowledge. Buat dokumen pertama Anda.</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-8 text-center text-muted-foreground">
            <BookMarked className="size-8 opacity-40" />
            <p className="text-sm">
              Belum ada dokumen kategori {FOLDERS.find((f) => f.id === category)?.label}.
            </p>
          </div>
        ) : (
          filtered.map((item) => (
            <div key={item.id} className="flex items-center gap-2.5 border-b px-3 py-2 last:border-b-0">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-xs font-medium">{item.name}</p>
                <p className="text-[11px] text-muted-foreground">
                  {formatBytes(item.sizeBytes)} · {new Date(item.updatedAt ?? "").toLocaleString("id-ID")}
                </p>
              </div>
              <Badge variant="secondary" className="shrink-0 text-[10px]">{item.folder}</Badge>
              {(item.usageCount ?? 0) > 0 && (
                <Badge className="shrink-0 gap-1 text-[10px]">
                  <Link2 className="size-3" /> {item.usageCount}
                </Badge>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                title="Baca (render Markdown)"
                onClick={() => openPreview(item)}
              >
                <Eye className="size-3.5" />
              </Button>
              <Button variant="ghost" size="icon" className="size-7" onClick={() => openEdit(item)}>
                <Pencil className="size-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 text-destructive hover:text-destructive"
                onClick={() => askDelete(item)}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))
        )}
      </div>

      {/* Editor dialog */}
      <Dialog open={!!editor} onOpenChange={(open) => !open && setEditor(null)}>
        <DialogContent className="sm:max-w-3xl overflow-y-auto max-h-[85vh]">
          <DialogHeader>
            <DialogTitle>{editor?.item ? `Edit ${editor?.item.name}` : "Knowledge baru"}</DialogTitle>
            <DialogDescription>
              Markdown teks biasa (.md). Maks 200KB. Nama otomatis slugify.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-48 flex-1 space-y-1.5">
                <Label>Nama</Label>
                <input
                  className="w-full rounded-md border bg-transparent px-3 py-2 text-sm"
                  placeholder="runbook-oom-killed"
                  value={editor?.name ?? ""}
                  onChange={(e) => editor && setEditor({ ...editor, name: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Kategori</Label>
                <Select
                  value={editor?.folder ?? "general"}
                  onValueChange={(v) => editor && setEditor({ ...editor, folder: v as KnowledgeFolder })}
                >
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {FOLDERS.map((f) => (
                      <SelectItem key={f.id} value={f.id}>{f.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <input ref={fileRef} type="file" accept=".md" className="hidden"
                onChange={(e) => onFile(e.target.files?.[0])} />
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                Ambil file .md…
              </Button>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label>Konten</Label>
                <div className="flex rounded-md border p-0.5 text-xs">
                  {(["tulis", "preview"] as const).map((m) => (
                    <button
                      key={m}
                      type="button"
                      className={cn(
                        "rounded px-2.5 py-1 capitalize transition-colors",
                        editorMode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                      )}
                      onClick={() => setEditorMode(m)}
                    >
                      {m === "tulis" ? "✍️ Tulis" : "👁 Preview"}
                    </button>
                  ))}
                </div>
              </div>
              {editorMode === "tulis" ? (
                <Textarea
                  rows={16}
                  className="min-h-[320px] max-h-[60vh] resize-y overflow-y-auto font-mono text-xs leading-relaxed"
                  placeholder={"# Runbook OOMKilled\nLangkah penanganan…"}
                  value={editor?.content ?? ""}
                  onChange={(e) => editor && setEditor({ ...editor, content: e.target.value })}
                />
              ) : (
                <Suspense fallback={<Skeleton className="h-72 w-full" />}>
                  <div className="min-h-[320px] max-h-[60vh] overflow-y-auto rounded-md border bg-muted/30 p-4">
                    {(editor?.content ?? "").trim() ? (
                      <MarkdownView content={editor?.content ?? ""} />
                    ) : (
                      <p className="text-sm text-muted-foreground">Belum ada konten untuk dipratinjau.</p>
                    )}
                  </div>
                </Suspense>
              )}
              <p className="text-[11px] text-muted-foreground">
                Markdown (heading, list, tabel, code block didukung) · {editor?.content.length ?? 0} karakter
                {editorMode === "tulis" && " · tarik sudut bawah untuk memperbesar"}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditor(null)}>Batal</Button>
            <Button
              onClick={save}
              disabled={create.isPending || update.isPending || !editor?.name || !editor?.content}
            >
              Simpan
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* View (render Markdown rapi) */}
      <Dialog open={!!preview} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="sm:max-w-4xl overflow-y-auto max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{preview?.item.name}</DialogTitle>
            <DialogDescription>
              Kategori: {preview?.item.folder}
              {typeof preview?.item.sizeBytes === "number" &&
                ` · ${(preview.item.sizeBytes / 1024).toFixed(1)} KB`}
            </DialogDescription>
          </DialogHeader>
          {preview && !preview.content ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <Suspense fallback={<Skeleton className="h-48 w-full" />}>
              <div className="min-h-24 rounded-md border bg-muted/30 p-4">
                <MarkdownView content={preview?.content ?? ""} />
              </div>
            </Suspense>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete confirm (+ warning cascade) */}
      <AlertDialog open={!!confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Hapus {confirmDelete?.item.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmDelete?.workspaces?.length ? (
                <>
                  ⚠️ Dokumen ini masih dipakai di{" "}
                  <strong>{confirmDelete.workspaces.map((w) => w.name).join(", ")}</strong>.
                  Menghapusnya akan ikut melepas knowledge tersebut dari semua workspace tsb —
                  Popov Agent tidak lagi memakainya untuk analisis di workspace itu.
                </>
              ) : (
                "Dokumen akan dihapus permanen dari library Anda."
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Batal</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmDelete)
                  remove.mutate({ id: confirmDelete.item.id, confirm: !!confirmDelete.workspaces?.length })
                setConfirmDelete(null)
              }}
            >
              Ya, hapus
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function formatBytes(n?: number): string {
  if (!n) return "0 B"
  if (n < 1024) return `${n} B`
  return `${(n / 1024).toFixed(1)} KB`
}
