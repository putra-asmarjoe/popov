import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { formatDate } from "@/lib/utils"
import type { ProgressEntry } from "@/types/ticket"

/** Timeline progress entries + form tambah catatan. */
export function ProgressLog({
  entries,
  onAdd,
  adding,
}: {
  entries: ProgressEntry[]
  onAdd: (note: string) => void
  adding: boolean
}) {
  const { t } = useTranslation("project")
  const [note, setNote] = useState("")

  const submit = () => {
    if (note.trim().length < 2) return
    onAdd(note.trim())
    setNote("")
  }

  return (
    <div className="space-y-3">
      {entries.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("progress.empty")}</p>
      ) : (
        <ol className="relative space-y-3 border-l pl-4">
          {entries.map((entry) => (
            <li key={entry.id} className="relative">
              <span className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-primary/60" />
              <p className="text-sm leading-snug">{entry.note}</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {entry.byName || t("progress.anonymous")} · {formatDate(entry.at)}
              </p>
            </li>
          ))}
        </ol>
      )}

      <div className="flex items-end gap-2">
        <Textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t("progress.add_placeholder")}
          className="min-h-9 resize-none text-sm"
          rows={1}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <Button size="icon" className="size-9 shrink-0" disabled={adding || note.trim().length < 2} onClick={submit}>
          <Send className="size-4" />
        </Button>
      </div>
    </div>
  )
}
