import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Brain, Trash2 } from "lucide-react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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
import { useDeleteEpisode, useEpisodes, type Episode } from "@/hooks/useManagement"
import { formatDate } from "@/lib/utils"

/** Tab Memory — Second Brain incident_episodes (DRY: reuse GET /brain/episodes). */
export function MemoryViewer() {
  const { t } = useTranslation("management")
  const [service, setService] = useState("")
  const [status, setStatus] = useState("all")
  const { data: episodes, isLoading } = useEpisodes(service, status)
  const remove = useDeleteEpisode()
  const [confirmDelete, setConfirmDelete] = useState<Episode | null>(null)

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Brain className="size-4 text-primary" />
        <p className="text-sm text-muted-foreground">{t("memory.description")}</p>
        <div className="ml-auto flex gap-2">
          <Input
            value={service}
            onChange={(e) => setService(e.target.value)}
            placeholder={t("memory.filter_service_placeholder")}
            className="h-8 w-44 text-sm"
          />
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="h-8 w-36 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("memory.all_statuses")}</SelectItem>
              <SelectItem value="correct">Correct</SelectItem>
              <SelectItem value="wrong">Wrong</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("memory.col_episode")}</TableHead>
              <TableHead className="hidden sm:table-cell">{t("memory.col_service")}</TableHead>
              <TableHead>{t("memory.col_feedback")}</TableHead>
              <TableHead className="hidden md:table-cell">{t("memory.col_time")}</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [...Array(5)].map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={5}><Skeleton className="h-8 w-full" /></TableCell>
                </TableRow>
              ))
            ) : !episodes?.length ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                  {t("memory.empty")}
                </TableCell>
              </TableRow>
            ) : (
              episodes.map((ep) => (
                <TableRow key={ep.episode_id}>
                  <TableCell>
                    <p className="font-mono text-xs font-semibold">{ep.episode_id}</p>
                    {ep.symptoms_summary && (
                      <p className="mt-0.5 max-w-72 truncate text-[11px] text-muted-foreground">
                        {String(ep.symptoms_summary)}
                      </p>
                    )}
                  </TableCell>
                  <TableCell className="hidden font-mono text-xs sm:table-cell">
                    {ep.service_name ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        ep.feedback === "correct" ? "default"
                        : ep.feedback === "wrong" ? "destructive"
                        : "outline"
                      }
                    >
                      {ep.feedback ?? "pending"}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                    {formatDate(ep.timestamp)}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7 text-destructive hover:text-destructive"
                      title={t("action.delete")}
                      onClick={() => setConfirmDelete(ep)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Confirm hapus — AlertDialog, UX paritas dgn delete stack di tab Stacks */}
      <AlertDialog open={!!confirmDelete} onOpenChange={(o) => !o && setConfirmDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("memory.delete_title", { id: confirmDelete?.episode_id ?? "" })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("memory.delete_description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("apikeys.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={remove.isPending}
              onClick={() => {
                if (confirmDelete) remove.mutate(confirmDelete.episode_id)
                setConfirmDelete(null)
              }}
            >
              {t("memory.delete_confirm_btn")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
