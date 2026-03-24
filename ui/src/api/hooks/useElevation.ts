import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { ElevationOverview } from "../../types/api";

export function useBotElevation(botId: string | undefined, limit = 10) {
  return useQuery({
    queryKey: ["bot-elevation", botId, limit],
    queryFn: () =>
      apiFetch<ElevationOverview>(
        `/api/v1/admin/bots/${botId}/elevation?limit=${limit}`,
      ),
    enabled: !!botId,
  });
}

export function useChannelElevation(
  channelId: string | undefined,
  limit = 10,
) {
  return useQuery({
    queryKey: ["channel-elevation", channelId, limit],
    queryFn: () =>
      apiFetch<ElevationOverview>(
        `/api/v1/admin/channels/${channelId}/elevation?limit=${limit}`,
      ),
    enabled: !!channelId,
  });
}
