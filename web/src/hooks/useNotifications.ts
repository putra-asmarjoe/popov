import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"
import type { NotificationsResponse } from "@/types/notification"

/** Notifikasi user — poll 60s sebagai fallback (utama: push WS notification:new). */
export function useNotifications(limit = 20, unreadOnly = false) {
  return useQuery({
    queryKey: ["notifications", limit, unreadOnly],
    queryFn: async () => {
      const { data } = await api.get("/notifications", {
        params: { limit, unreadOnly: unreadOnly ? "true" : undefined },
      })
      return data as NotificationsResponse
    },
    refetchInterval: 60_000,
  })
}

/** Tandai terbaca. ids kosong/undefined = semua. */
export function useMarkRead() {
  const { t } = useTranslation("settings")
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (ids?: string[]) => {
      const { data } = await api.post("/notifications/read", { ids: ids ?? [] })
      return data as { updated: number }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("toasts.notification_mark_failed"))),
  })
}
