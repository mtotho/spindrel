import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { WidgetAgencyReceiptList, WidgetUsefulnessAssessment } from "@/src/types/api";

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

export function useChannelWidgetAgencyReceipts(channelId?: string | null, limit = 8) {
  return useQuery({
    queryKey: ["channel-widget-agency-receipts", channelId, limit],
    queryFn: () =>
      apiFetch<WidgetAgencyReceiptList>(
        `/api/v1/admin/channels/${encodeURIComponent(channelId!)}/widget-agency/receipts?limit=${limit}`,
      ),
    enabled: !!channelId,
    staleTime: 30_000,
  });
}
