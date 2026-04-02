import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SystemStatus {
  paused: boolean;
  pause_behavior: "queue" | "drop";
}

export function useSystemStatus() {
  return useQuery({
    queryKey: ["system-status"],
    queryFn: () => apiFetch<SystemStatus>("/api/v1/admin/status"),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
