import { useMemo } from "react"
import type { AgentTrace } from "@/types/chat"

/** Layout & render SVG graph agent (Per-Agent Tracing Fase 2).
 *  Setiap agent = node card (rounded rect + nama + durasi), edges = kurva antar
 *  node sesuai urutan eksekusi. Node paralel (fan-out) di baris sama. */
export function AgentGraphSVG({
  traces,
  selectedAgent,
  onSelect,
}: {
  traces: AgentTrace[]
  selectedAgent: string | null
  onSelect: (agent: string) => void
}) {
  // ── Layout: buat "baris" (kolom) berdasarkan urutan — node berurutan = edge lurus
  const layout = useMemo(() => {
    const NODE_W = 148
    const NODE_H = 56
    const GAP_X = 44
    const GAP_Y = 28
    const nodes = traces.map((t, i) => {
      const x = 20 + i * (NODE_W + GAP_X)
      const y = 30 + (i % 2) * (NODE_H + GAP_Y) // zig-zag biar muat horizontal
      return { ...t, x, y, w: NODE_W, h: NODE_H }
    })
    const width = nodes.length ? nodes[nodes.length - 1].x + NODE_W + 20 : 320
    const height = 30 + 2 * (NODE_H + GAP_Y) + 20
    // Edges: urutan berurutan → garis dari node[i] ke node[i+1]
    const edges = nodes.slice(0, -1).map((n, i) => ({ from: n, to: nodes[i + 1] }))
    return { nodes, edges, width, height }
  }, [traces])

  if (traces.length === 0) return null

  return (
    <div className="overflow-x-auto">
      <svg width={layout.width} height={layout.height} className="min-w-[320px]">
        {/* Edges */}
        {layout.edges.map((e, i) => (
          <path
            key={`edge-${i}`}
            d={`M ${e.from.x + e.from.w} ${e.from.y + e.from.h / 2} C ${e.from.x + e.from.w + 30} ${e.from.y + e.from.h / 2}, ${e.to.x - 30} ${e.to.y + e.to.h / 2}, ${e.to.x} ${e.to.y + e.to.h / 2}`}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            className="text-muted-foreground/40"
            markerEnd="url(#trace-arrow)"
          />
        ))}
        <defs>
          <marker id="trace-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-muted-foreground/40" />
          </marker>
        </defs>

        {/* Nodes */}
        {layout.nodes.map((n) => {
          const selected = n.agent === selectedAgent
          const dur = n.duration_ms
          const durText = dur == null ? "…" : `${(dur / 1000).toFixed(1)}s`
          const slow = dur != null && dur > 3000
          return (
            <g
              key={`${n.agent}-${n.order}`}
              onClick={() => onSelect(n.agent)}
              className="cursor-pointer"
            >
              <rect
                x={n.x}
                y={n.y}
                width={n.w}
                height={n.h}
                rx={10}
                className={selected ? "fill-primary/15 stroke-primary" : "fill-muted/60 stroke-muted-foreground/30"}
                strokeWidth={selected ? 2 : 1}
              />
              <text x={n.x + 12} y={n.y + 22} fontSize={11} fontWeight={600} className="fill-foreground">
                {n.agent.replace("_agent", "")}
              </text>
              <text x={n.x + 12} y={n.y + 40} fontSize={10} className={slow ? "fill-destructive" : "fill-muted-foreground"}>
                {durText}
              </text>
              <text x={n.x + n.w - 10} y={n.y + 22} fontSize={9} textAnchor="end" className="fill-muted-foreground/60">
                #{n.order}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
