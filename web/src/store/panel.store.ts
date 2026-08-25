import { create } from "zustand"
import { persist } from "zustand/middleware"

interface PanelBounds {
  x: number
  y: number
  width: number
  height: number
}

interface PanelStore {
  bounds: PanelBounds
  isMaximized: boolean
  setBounds: (bounds: Partial<PanelBounds>) => void
  toggleMaximize: () => void
  resetBounds: () => void
}

const DEFAULT_WIDTH = 880
const DEFAULT_HEIGHT = 600
const MARGIN = 16

function defaultBounds(): PanelBounds {
  if (typeof window === "undefined") {
    return { x: MARGIN, y: MARGIN, width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT }
  }
  return {
    x: Math.max(MARGIN, window.innerWidth - DEFAULT_WIDTH - MARGIN),
    y: Math.max(MARGIN, window.innerHeight - DEFAULT_HEIGHT - MARGIN),
    width: DEFAULT_WIDTH,
    height: DEFAULT_HEIGHT,
  }
}

export const usePanelStore = create<PanelStore>()(
  persist(
    (set) => ({
      bounds: defaultBounds(),
      isMaximized: false,
      setBounds(bounds) {
        set((state) => ({ bounds: { ...state.bounds, ...bounds } }))
      },
      toggleMaximize() {
        set((state) => {
          if (!state.isMaximized) return { isMaximized: true }
          // Minimize: kembalikan ke POSISI DEFAULT kanan-bawah (ukuran terakhir dipertahankan)
          if (typeof window === "undefined") return { isMaximized: false }
          const vw = window.innerWidth
          const vh = window.innerHeight
          const width = Math.min(state.bounds.width, vw - MARGIN * 2)
          const height = Math.min(state.bounds.height, vh - MARGIN * 2)
          return {
            isMaximized: false,
            bounds: {
              x: Math.max(MARGIN, vw - width - MARGIN),
              y: Math.max(MARGIN, vh - height - MARGIN),
              width,
              height,
            },
          }
        })
      },
      resetBounds() {
        set({ bounds: defaultBounds(), isMaximized: false })
      },
    }),
    {
      name: "popov-panel-prefs",
      partialize: (state) => ({ bounds: state.bounds, isMaximized: state.isMaximized }),
    },
  ),
)