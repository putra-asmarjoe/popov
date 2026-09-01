import { useCallback, useEffect, useRef, useState } from "react"

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

/**
 * useDragResize — drag-to-resize split pane (pointer events, col-resize).
 * - `reverse`: true bila pane yang di-resize ada di KANAN divider (trace),
 *   false bila di KIRI (detail). Delta X dikalikan -1 untuk pane kanan.
 * - `storageKey`: persist lebar per user (localStorage) supaya pilihan end-user
 *   awet lintas sesi.
 */
export function useDragResize({
  initial,
  min,
  max,
  reverse = false,
  storageKey,
}: {
  initial: number
  min: number
  max: number
  reverse?: boolean
  storageKey?: string
}) {
  const [width, setWidth] = useState<number>(() => {
    if (storageKey) {
      try {
        const saved = window.localStorage.getItem(storageKey)
        if (saved) {
          const n = parseInt(saved, 10)
          if (!Number.isNaN(n)) return clamp(n, min, max)
        }
      } catch {
        // localStorage unavailable (privacy mode) — pakai initial
      }
    }
    return initial
  })
  const startRef = useRef<{ x: number; startWidth: number } | null>(null)
  const widthRef = useRef(width)
  useEffect(() => {
    widthRef.current = width
  }, [width])

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return
    e.preventDefault()
    startRef.current = { x: e.clientX, startWidth: widthRef.current }
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"
  }, [])

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const start = startRef.current
      if (!start) return
      const dx = e.clientX - start.x
      setWidth(clamp(start.startWidth + (reverse ? -dx : dx), min, max))
    }
    const onUp = () => {
      if (!startRef.current) return
      startRef.current = null
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
      if (storageKey) {
        try {
          window.localStorage.setItem(storageKey, String(widthRef.current))
        } catch {
          // abaikan — preferensi tidak persist
        }
      }
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
    }
  }, [reverse, min, max, storageKey])

  return { width, onPointerDown }
}