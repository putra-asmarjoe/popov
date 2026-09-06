import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ProjectOverviewData } from "@/types/overview"

/** Project Overview — refetch sinkron watchdog 30s tick. */
export function useProjectOverview(
  projectId: string | null | undefined,
  days: number = 7,
  open_only: boolean = false,
) {
  return useQuery({
    queryKey: ["project-overview", projectId, days, open_only],
    queryFn: () =>
      api.get<ProjectOverviewData>(
        `/projects/${projectId}/overview?days=${days}${open_only ? "&open_only=true" : ""}`
      ).then((r) => r.data),
    enabled: Boolean(projectId),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    placeholderData: (prev) => prev,
  })
}