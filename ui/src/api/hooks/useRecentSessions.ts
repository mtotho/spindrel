import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../client";
import type { ChannelSessionCatalogItem } from "../../lib/channelSessionSurfaces";

export interface RecentSessionItem extends ChannelSessionCatalogItem {
  channel_id: string;
  channel_name: string;
  unread_agent_reply_count: number;
  latest_unread_at: string | null;
}

interface RecentSessionsResponse {
  sessions: RecentSessionItem[];
}

export function useRecentSessions(limit = 8) {
  return useQuery({
    queryKey: ["recent-sessions", limit],
    queryFn: () => apiFetch<RecentSessionsResponse>(`/api/v1/sessions/recent?limit=${limit}`),
    staleTime: 30_000,
  });
}
