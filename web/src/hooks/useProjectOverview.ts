import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ProjectOverviewData } from "@/types/overview"

/** Project Overview — refetch sinkron watchdog 30s tick. */
export function useProjectOverview(projectId: string | null | undefined) {
  return useQuery({
    queryKey: ["project-overview", projectId],
    queryFn: () =>
      api.get<ProjectOverviewData>(`/projects/${projectId}/overview`).then((r) => r.data),
    enabled: Boolean(projectId),
    staleTime: 15_000,
    refetchInterval: 30_000,
    // Jangan polling saat tab hidden / window unfocus (stop offscreen work)
    refetchIntervalInBackground: false,
  })
}