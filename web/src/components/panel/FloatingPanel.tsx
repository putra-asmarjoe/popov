import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import interact from "interactjs"
import { Maximize2, Minimize2, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { usePanelStore } from "@/store/panel.store"

interface FloatingPanelProps {
  open: boolean
  onClose: () => void
  title?: React.ReactNode
  /** Konten yang di-render di dalam body panel (scrollable) */
  children: React.ReactNode
  /** Slot kiri header di samping handle/judul (mis. tab switcher) */
  headerLeft?: React.ReactNode
  /** z-index panel */
  zIndex?: number
}

const MOBILE_BREAKPOINT = 768
const MARGIN = 16
const MIN_WIDTH = 320
const MIN_HEIGHT = 320

interface PanelGeom {
  x: number
  y: number
  width: number
  height: number
}

function getViewportSize() {
  if (typeof window === "undefined") return { w: 1280, h: 800 }
  return { w: window.innerWidth, h: window.innerHeight }
}

function isMobile(): boolean {
  if (typeof window === "undefined") return false
  return window.innerWidth < MOBILE_BREAKPOINT
}

/** Clamp bounds agar selalu berada di dalam viewport (dipakai di render & interaksi). */
function clampToViewport(b: PanelGeom, vw: number, vh: number): PanelGeom {
  return {
    x: Math.min(Math.max(b.x, MARGIN), Math.max(MARGIN, vw - b.width - MARGIN)),
    y: Math.min(Math.max(b.y, MARGIN), Math.max(MARGIN, vh - b.height - MARGIN)),
    width: Math.min(Math.max(b.width, MIN_WIDTH), vw - MARGIN * 2),
    height: Math.min(Math.max(b.height, MIN_HEIGHT), vh - MARGIN * 2),
  }
}

function applyGeom(el: HTMLElement, g: PanelGeom) {
  el.style.width = `${g.width}px`
  el.style.height = `${g.height}px`
  el.style.transform = `translate(${g.x}px, ${g.y}px)`
}

/** Handle resize (sebagai anak panel agar selalu terlihat & tidak ter-clip oleh overflow).
 *  Handle sudut membawa dua kelas kardinal agar interact.js mengaktifkan 2 edge sekaligus (diagonal). */
function ResizeHandles() {
  return (
    <>
      <div className="ph-top absolute left-4 right-4 top-0 z-30 h-1.5 cursor-ns-resize" />
      <div className="ph-bottom absolute bottom-0 left-4 right-4 z-30 h-1.5 cursor-ns-resize" />
      <div className="ph-left absolute bottom-4 left-0 top-4 z-30 w-1.5 cursor-ew-resize" />
      <div className="ph-right absolute bottom-4 right-0 top-4 z-30 w-1.5 cursor-ew-resize" />
      <div className="ph-top ph-left absolute left-0 top-0 z-30 size-3.5 cursor-nwse-resize" />
      <div className="ph-top ph-right absolute right-0 top-0 z-30 size-3.5 cursor-nesw-resize" />
      <div className="ph-bottom ph-left absolute bottom-0 left-0 z-30 size-3.5 cursor-nesw-resize" />
      <div className="ph-bottom ph-right absolute bottom-0 right-0 z-30 size-3.5 cursor-nwse-resize" />
    </>
  )
}

export function FloatingPanel({
  open,
  onClose,
  title,
  children,
  headerLeft,
  zIndex = 60,
}: FloatingPanelProps) {
  const bounds = usePanelStore((s) => s.bounds)
  const isMaximized = usePanelStore((s) => s.isMaximized)
  const setBounds = usePanelStore((s) => s.setBounds)
  const toggleMaximize = usePanelStore((s) => s.toggleMaximize)

  const [mobile, setMobile] = useState<boolean>(isMobile)
  const panelRef = useRef<HTMLDivElement | null>(null)
  // Geometri "live" selama drag/resize (commit ke store hanya saat selesai).
  const geomRef = useRef<PanelGeom>({ x: 0, y: 0, width: 0, height: 0 })

  // Track viewport resize untuk re-clamp bounds ke dalam viewport
  useEffect(() => {
    const onResize = () => {
      setMobile(isMobile())
      const { w, h } = getViewportSize()
      const clamped = clampToViewport(
        { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height },
        w,
        h,
      )
      // Hanya set kalau memang berbeda (hindari loop render)
      if (
        clamped.x !== bounds.x ||
        clamped.y !== bounds.y ||
        clamped.width !== bounds.width ||
        clamped.height !== bounds.height
      ) {
        setBounds(clamped)
      }
    }
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [bounds.x, bounds.y, bounds.width, bounds.height, setBounds])

  // Escape close
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  // Interaksi drag + resize (interact.js). Hanya aktif di desktop, panel terbuka, dan tidak maximize.
  useEffect(() => {
    const el = panelRef.current
    if (!el || !open || mobile || isMaximized) return

    const { w, h } = getViewportSize()
    const start = clampToViewport(
      { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height },
      w,
      h,
    )
    geomRef.current = { ...start }
    applyGeom(el, start)

    let dragEnd: PanelGeom | null = null
    let resizeEnd: PanelGeom | null = null

    const instance = interact(el)
      .draggable({
        allowFrom: ".panel-drag-handle",
        inertia: false,
        listeners: {
          move(event) {
            const g = geomRef.current
            const { w: vw, h: vh } = getViewportSize()
            const next = clampToViewport(
              { x: g.x + event.dx, y: g.y + event.dy, width: g.width, height: g.height },
              vw,
              vh,
            )
            dragEnd = next
            applyGeom(el, next)
          },
          end() {
            if (dragEnd) geomRef.current = dragEnd
            setBounds({ x: geomRef.current.x, y: geomRef.current.y })
          },
        },
      })
      .resizable({
        edges: {
          top: ".ph-top",
          left: ".ph-left",
          bottom: ".ph-bottom",
          right: ".ph-right",
        },
        inertia: false,
        listeners: {
          // Anchor per-edge: edge yang TIDAK digerakkan dipertahankan posisinya;
          // edge yang digerakkan berhenti di tepi viewport (ukuran berhenti tumbuh,
          // posisi TIDAK melompat — hindari window nyangkut di kiri-atas saat membesar melewati viewport).
          move(event) {
            const g = geomRef.current
            const { w: vw, h: vh } = getViewportSize()
            const e = event.edges ?? {}
            const maxW = vw - MARGIN * 2
            const maxH = vh - MARGIN * 2

            let { x, y, width, height } = g

            if (e.left || e.right) {
              const rawW = event.rect.width
              if (e.left && !e.right) {
                // kiri bergerak → jangkar di kanan (right edge ditahan)
                const right = g.x + g.width
                x = Math.min(Math.max(event.rect.left, MARGIN), right - MIN_WIDTH)
                width = Math.min(right - x, maxW)
                width = Math.max(MIN_WIDTH, width)
                x = right - width
              } else if (e.right && !e.left) {
                // kanan bergerak → jangkar di kiri (x tetap), ukuran berhenti di viewport
                x = g.x
                width = Math.max(MIN_WIDTH, Math.min(rawW, vw - MARGIN - x))
              } else {
                // dua-duanya bergerak (sudut) → bebas, dibatasi viewport & MIN
                x = Math.min(Math.max(event.rect.left, MARGIN), vw - MARGIN - MIN_WIDTH)
                width = Math.max(MIN_WIDTH, Math.min(rawW, vw - MARGIN - x, maxW))
              }
            }

            if (e.top || e.bottom) {
              const rawH = event.rect.height
              if (e.top && !e.bottom) {
                // atas bergerak → jangkar di bawah (bottom edge ditahan)
                const bottom = g.y + g.height
                y = Math.min(Math.max(event.rect.top, MARGIN), bottom - MIN_HEIGHT)
                height = Math.min(bottom - y, maxH)
                height = Math.max(MIN_HEIGHT, height)
                y = bottom - height
              } else if (e.bottom && !e.top) {
                // bawah bergerak → jangkar di atas (y tetap), ukuran berhenti di viewport
                y = g.y
                height = Math.max(MIN_HEIGHT, Math.min(rawH, vh - MARGIN - y))
              } else {
                // dua-duanya bergerak (sudut)
                y = Math.min(Math.max(event.rect.top, MARGIN), vh - MARGIN - MIN_HEIGHT)
                height = Math.max(MIN_HEIGHT, Math.min(rawH, vh - MARGIN - y, maxH))
              }
            }

            const next = { x, y, width, height }
            resizeEnd = next
            // Guard: jangan tulis geometri non-finite (event ekstrem/platform tertentu)
            if (![x, y, width, height].every(Number.isFinite)) return
            applyGeom(el, next)
          },
          end() {
            if (resizeEnd) geomRef.current = resizeEnd
            setBounds({ ...geomRef.current })
          },
        },
      })

    return () => {
      instance.unset()
    }
  }, [open, mobile, isMaximized, bounds.x, bounds.y, bounds.width, bounds.height, setBounds])

  if (!open) return null

  const { w: vw, h: vh } = getViewportSize()

  // Mobile: drawer mode (full-height, dari kanan)
  if (mobile) {
    return (
      <>
        <div
          aria-hidden
          className="fixed inset-0 z-40 bg-foreground/40"
          onClick={onClose}
        />
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col border-l bg-background shadow-xl"
        >
          <PanelHeader
            headerLeft={headerLeft}
            title={title}
            isMobile
            onClose={onClose}
          />
          <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
        </div>
      </>
    )
  }

  // Desktop: floating window (drag dari header, resize 8 arah, posisi/ukuran di-clamp ke viewport).
  const maxWidth = vw - MARGIN * 2
  const maxHeight = vh - MARGIN * 2
  const displayW = isMaximized ? maxWidth : Math.min(bounds.width, maxWidth)
  const displayH = isMaximized ? maxHeight : Math.min(bounds.height, maxHeight)
  const displayPos = isMaximized
    ? { x: MARGIN, y: MARGIN }
    : (() => {
        const c = clampToViewport(
          { x: bounds.x, y: bounds.y, width: displayW, height: displayH },
          vw,
          vh,
        )
        return { x: c.x, y: c.y }
      })()

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      className={cn(
        "absolute left-0 top-0 z-[60] flex flex-col overflow-hidden rounded-xl border bg-background shadow-2xl ring-1 ring-foreground/5",
        isMaximized && "rounded-none",
      )}
      style={{
        zIndex,
        width: displayW,
        height: displayH,
        transform: `translate(${displayPos.x}px, ${displayPos.y}px)`,
      }}
    >
      <PanelHeader
        headerLeft={headerLeft}
        title={title}
        isMobile={false}
        onClose={onClose}
        isMaximized={isMaximized}
        onToggleMaximize={toggleMaximize}
      />
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</div>
      {!isMaximized && <ResizeHandles />}
    </div>
  )
}

function PanelHeader({
  headerLeft,
  title,
  isMobile,
  onClose,
  isMaximized,
  onToggleMaximize,
}: {
  headerLeft?: React.ReactNode
  title?: React.ReactNode
  isMobile: boolean
  onClose: () => void
  isMaximized?: boolean
  onToggleMaximize?: () => void
}) {
  const { t } = useTranslation("common")
  const draggable = !isMobile
  return (
    <div
      className={cn(
        "flex h-11 min-w-0 shrink-0 items-center gap-1 border-b bg-background px-2",
        draggable && "panel-drag-handle cursor-grab active:cursor-grabbing",
      )}
    >
      {headerLeft}
      {title && (
        <div className="ml-1 truncate text-xs font-semibold text-muted-foreground">
          {title}
        </div>
      )}
      <div className="ml-auto flex items-center gap-0.5 panel-no-drag">
        {onToggleMaximize && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={onToggleMaximize}
            aria-label={isMaximized ? t("panel.minimize") : t("panel.maximize")}
          >
            {isMaximized ? (
              <Minimize2 className="size-3.5" />
            ) : (
              <Maximize2 className="size-3.5" />
            )}
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={onClose}
          aria-label={t("panel.close")}
        >
          <X className="size-3.5" />
        </Button>
      </div>
    </div>
  )
}