import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { Channel } from "../../types/api";

export function useChannels() {
  return useQuery({
    queryKey: ["channels"],
    queryFn: () => apiFetch<Channel[]>("/api/v1/channels"),
  });
}

export function useChannel(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channels", channelId],
    queryFn: () => apiFetch<Channel>(`/api/v1/channels/${channelId}`),
    enabled: !!channelId,
  });
}
