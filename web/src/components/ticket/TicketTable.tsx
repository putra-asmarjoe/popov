import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { ChevronLeft, ChevronRight, Ticket } from "lucide-react"
import { useTranslation } from "react-i18next"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { AssigneeList } from "@/components/ticket/AssigneeList"
import { SeverityBadge, StatusBadge } from "@/components/ticket/Badges"
import { cn, formatDate } from "@/lib/utils"
import type { Ticket as TicketType, TicketListMeta } from "@/types/ticket"

const columnHelper = createColumnHelper<TicketType>()

interface TicketTableProps {
  projectKey: string
  tickets: TicketType[]
  meta: TicketListMeta | undefined
  page: number
  onPageChange: (page: number) => void
  isLoading: boolean
  activeTicketId: string | null
  onSelect: (ticket: TicketType) => void
}

/** Tabel tiket (TanStack Table, manual pagination server-side). */
export function TicketTable({
  projectKey,
  tickets,
  meta,
  page,
  onPageChange,
  isLoading,
  activeTicketId,
  onSelect,
}: TicketTableProps) {
  const { t } = useTranslation("project")
  const columns = [
    columnHelper.accessor("ticketNumber", {
      header: "#",
      cell: (info) => (
        <span className="font-mono text-xs font-semibold text-muted-foreground">
          {projectKey}-{info.getValue()}
        </span>
      ),
    }),
    columnHelper.accessor("title", {
      header: t("table.header_title"),
      cell: (info) => (
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="truncate font-medium">{info.getValue()}</span>
          {info.row.original.source === "watchdog" && (
            <span title={t("table.watchdog_badge")} className="shrink-0 text-xs">🤖</span>
          )}
        </div>
      ),
    }),
    columnHelper.accessor("severity", {
      header: "Severity",
      cell: (info) => <SeverityBadge severity={info.getValue()} />,
    }),
    columnHelper.accessor("status", {
      header: "Status",
      cell: (info) => <StatusBadge status={info.getValue()} />,
    }),
    columnHelper.accessor("assigneesDetail", {
      header: "Assignee",
      cell: (info) => <AssigneeList assignees={info.getValue()} />,
    }),
    columnHelper.accessor("updatedAt", {
      header: t("table.header_updated"),
      cell: (info) => (
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          {formatDate(info.getValue())}
        </span>
      ),
    }),
  ]

  const table = useReactTable({
    data: tickets,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  if (isLoading && !tickets.length) {
    return (
      <div className="space-y-2 p-4">
        {[...Array(6)].map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (!tickets.length) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="max-w-sm text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-muted">
            <Ticket className="size-6 text-muted-foreground" />
          </div>
          <p className="mt-4 text-sm font-medium">{t("table.empty_title")}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("table.empty_hint")}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <Table>
          <TableHeader className="sticky top-0 bg-background">
            <TableRow>
              {table.getHeaderGroups()[0].headers.map((header) => (
                <TableHead key={header.id} className="text-xs">
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                className={cn(
                  "cursor-pointer",
                  row.original.id === activeTicketId && "bg-muted/60",
                )}
                onClick={() => onSelect(row.original)}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="py-2.5">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {meta && meta.pages > 1 && (
        <div className="flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
          <span>
            {t("table.pagination", { total: meta.total, page: meta.page, pages: meta.pages })}
          </span>
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="icon"
              className="size-7"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              <ChevronLeft className="size-3.5" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="size-7"
              disabled={page >= meta.pages}
              onClick={() => onPageChange(page + 1)}
            >
              <ChevronRight className="size-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
