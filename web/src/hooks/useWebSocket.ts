import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { getToken } from "@/lib/auth"

function wsBaseUrl(): string {
  const override = import.meta.env.VITE_WS_BASE_URL as string | undefined
  if (override) return override.replace(/\/$/, "")
  // Same-origin via Vite proxy (dev, ws:true) atau FastAPI (prod)
  const proto = window.location.protocol === "https:" ? "wss" : "ws"
  return `${proto}://${window.location.host}/api/v1`
}

/**
 * useTicketRealtime — WebSocket per project (native, tanpa Socket.io).
 * Event tiket → debounce 300ms invalidate list; notification:new → invalidate + toast.
 * Reconnect backoff 5s → 30s.
 */
export function useTicketRealtime(projectId: string | null | undefined) {
  const queryClient = useQueryClient()

  useEffect(() => {
    const token = getToken()
    if (!projectId || !token) return

    let ws: WebSocket | null = null
    let closed = false
    let retries = 0
    let reconnectTimer: number | undefined
    let invalidateTimer: number | undefined

    const debouncedInvalidate = () => {
      window.clearTimeout(invalidateTimer)
      invalidateTimer = window.setTimeout(() => {
        // List + detail tiket. React-query hanya refetch query yang sedang aktif
        // (mounted), jadi tanpa looping/berat; detail tiket yang terbuka ikut segar.
        queryClient.invalidateQueries({ queryKey: ["tickets", projectId] })
        queryClient.invalidateQueries({ queryKey: ["ticket"] })
        // Fix #86: alert ter-link ikut segar (event ticket:alert_added)
        queryClient.invalidateQueries({ queryKey: ["ticketAlerts"] })
        // War Room: run baru / status berubah saat investigasi selesai → segar
        queryClient.invalidateQueries({ queryKey: ["ticket-warroom"] })
        // Overview: open count / episode timeline berubah saat tiket berubah
        queryClient.invalidateQueries({ queryKey: ["project-overview", projectId] })
      }, 300)
    }

    const connect = () => {
      if (closed) return
      ws = new WebSocket(`${wsBaseUrl()}/ws/${projectId}?token=${encodeURIComponent(token)}`)

      ws.onopen = () => {
        retries = 0
      }

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data)
          if (typeof event.type === "string" && event.type.startsWith("ticket:")) {
            debouncedInvalidate()
          }
          if (event.type === "notification:new") {
            queryClient.invalidateQueries({ queryKey: ["notifications"] })
            if (event.payload?.title) toast.info(event.payload.title)
          }
        } catch {
          // payload bukan JSON — abaikan
        }
      }

      ws.onclose = () => {
        if (closed) return
        retries += 1
        const delay = Math.min(5000 * retries, 30000)
        reconnectTimer = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closed = true
      window.clearTimeout(reconnectTimer)
      window.clearTimeout(invalidateTimer)
      ws?.close()
    }
  }, [projectId, queryClient])
}
