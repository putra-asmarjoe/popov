/**
 * SplitHandle — divider vertikal tipis utk drag-resize split pane.
 * Menangani pointerdown → hook useDragResize. Memberi affordance
 * (cursor col-resize + highlight hover/active).
 */
export function SplitHandle({
  onPointerDown,
}: {
  onPointerDown: (e: React.PointerEvent) => void
}) {
  return (
    <div
      className="group relative w-1.5 shrink-0 cursor-col-resize touch-none select-none bg-transparent hover:bg-primary/15 active:bg-primary/20"
      onPointerDown={onPointerDown}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
    >
      <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors group-hover:bg-primary/40" />
    </div>
  )
}