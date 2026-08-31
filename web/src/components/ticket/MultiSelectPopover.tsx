import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

/** Multi-select popover (Status/Severity) — dipakai TicketFilters & TicketSummaryCard (DRY). */
export function MultiSelectPopover({
  label,
  activeCount,
  items,
}: {
  label: string
  activeCount: number
  items: { value: string; label: string; checked: boolean; onToggle: () => void }[]
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-sm">
          {label}
          {activeCount > 0 && (
            <span className="rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">
              {activeCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-44 p-2">
        {items.map((item) => (
          <Label
            key={item.value}
            className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm font-normal hover:bg-muted"
          >
            <Checkbox checked={item.checked} onCheckedChange={item.onToggle} />
            {item.label}
          </Label>
        ))}
      </PopoverContent>
    </Popover>
  )
}