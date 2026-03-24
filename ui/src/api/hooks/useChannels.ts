import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { Channel, ChannelSettings } from "../../types/api";

interface ChannelListResponse {
  channels: Channel[];
  total: number;
  page: number;
  page_size: number;
}

export function useChannels() {
  return useQuery({
    queryKey: ["channels"],
    queryFn: async () => {
      const res = await apiFetch<ChannelListResponse>("/api/v1/admin/channels-enriched?page_size=100");
      return res.channels;
    },
  });
}

export function useChannel(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channels", channelId],
    queryFn: () => apiFetch<Channel>(`/api/v1/channels/${channelId}`),
    enabled: !!channelId,
  });
}

export function useChannelSettings(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-settings", channelId],
    queryFn: () => apiFetch<ChannelSettings>(`/api/v1/admin/channels/${channelId}/settings`),
    enabled: !!channelId,
  });
}

export function useUpdateChannelSettings(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: Partial<ChannelSettings>) =>
      apiFetch<ChannelSettings>(`/api/v1/admin/channels/${channelId}/settings`, {
        method: "PUT",
        body: JSON.stringify(settings),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-settings", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}
