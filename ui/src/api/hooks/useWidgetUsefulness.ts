import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { WidgetUsefulnessAssessment } from "@/src/types/api";

export function useChannelWidgetUsefulness(channelId?: string | null) {
  return useQuery({
    queryKey: ["channel-widget-usefulness", channelId],
    queryFn: () =>
      apiFetch<WidgetUsefulnessAssessment>(
        `/api/v1/admin/channels/${encodeURIComponent(channelId!)}/widget-usefulness`,
      ),
    enabled: !!channelId,
    staleTime: 30_000,
  });
}
