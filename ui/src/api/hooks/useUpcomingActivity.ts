import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface UpcomingItem {
  type: "heartbeat" | "task" | "memory_hygiene";
  scheduled_at: string;
  bot_id: string;
  bot_name: string;
  channel_id: string | null;
  channel_name: string | null;
  title: string;
  // heartbeat-specific
  interval_minutes?: number;
  in_quiet_hours?: boolean;
  // task-specific
  task_id?: string;
  task_type?: string;
  recurrence?: string;
  // memory_hygiene-specific
  interval_hours?: number;
}

interface UpcomingResponse {
  items: UpcomingItem[];
}

export function useUpcomingActivity(limit: number = 50, typeFilter?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (typeFilter) params.set("type", typeFilter);

  return useQuery({
    queryKey: ["upcoming-activity", limit, typeFilter],
    queryFn: () => apiFetch<UpcomingResponse>(`/api/v1/admin/upcoming-activity?${params}`),
    refetchInterval: 60_000,
    select: (data) => data.items,
  });
}

export function useSpatialUpcomingActivity(limit: number = 50, typeFilter?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (typeFilter) params.set("type", typeFilter);

  return useQuery({
    queryKey: ["spatial-upcoming-activity", limit, typeFilter],
    queryFn: () =>
      apiFetch<UpcomingResponse>(`/api/v1/workspace/spatial/upcoming-activity?${params}`),
    refetchInterval: 60_000,
    select: (data) => data.items,
  });
}
