import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { api, apiErrorMessage } from "@/lib/api"
import type { ProfilePatch, UserProfile } from "@/types/profile"

/** User Profile per workspace — USER_PROFILE_PLAN Phase 2 UI.
 *  GET profil aktif; PATCH manual fields (enum 422 di backend);
 *  DELETE counters (reset pasif — manual fields tersentuh). */

export function useProfile(workspaceId: string | null | undefined) {
  return useQuery({
    queryKey: ["profile", workspaceId],
    queryFn: async () => {
      const { data } = await api.get("/profile", { params: { workspace_id: workspaceId } })
      return data as UserProfile
    },
    enabled: Boolean(workspaceId),
    staleTime: 30_000,
  })
}

export function useUpdateProfile(workspaceId: string | null | undefined) {
  const qc = useQueryClient()
  const { t } = useTranslation("account")
  return useMutation({
    mutationFn: async (patch: ProfilePatch) => {
      const { data } = await api.patch("/profile", patch, { params: { workspace_id: workspaceId } })
      return data as UserProfile
    },
    onSuccess: () => {
      toast.success(t("saved"))
      qc.invalidateQueries({ queryKey: ["profile", workspaceId] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("save_failed"))),
  })
}

export function useResetCounters(workspaceId: string | null | undefined) {
  const qc = useQueryClient()
  const { t } = useTranslation("account")
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.delete("/profile/counters", { params: { workspace_id: workspaceId } })
      return data as UserProfile
    },
    onSuccess: () => {
      toast.success(t("counters_reset"))
      qc.invalidateQueries({ queryKey: ["profile", workspaceId] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, t("reset_failed"))),
  })
}

// ── Phase 4: batch inferensi — approve / reject saran ─────────────────────────

function useInferenceAction(
  action: "approve" | "reject",
  workspaceId: string | null | undefined,
) {
  const qc = useQueryClient()
  const { t } = useTranslation("account")
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post(`/profile/inference/${action}`, null, {
        params: { workspace_id: workspaceId },
      })
      return data as UserProfile
    },
    onSuccess: () => {
      toast.success(action === "approve" ? t("suggestion_applied") : t("suggestion_rejected"))
      qc.invalidateQueries({ queryKey: ["profile", workspaceId] })
    },
    onError: (e) =>
      toast.error(apiErrorMessage(e, action === "approve" ? t("apply_failed") : t("reject_failed"))),
  })
}

export function useApproveSuggestion(workspaceId: string | null | undefined) {
  return useInferenceAction("approve", workspaceId)
}

export function useRejectSuggestion(workspaceId: string | null | undefined) {
  return useInferenceAction("reject", workspaceId)
}
