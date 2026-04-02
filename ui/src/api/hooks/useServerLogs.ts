import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface ServerLogEntry {
  timestamp: number;
  level: string;
  logger: string;
  message: string;
  formatted: string;
}

export interface ServerLogsResponse {
  entries: ServerLogEntry[];
  total: number;
  levels: string[];
}

export interface ServerLogsParams {
  tail?: number;
  level?: string;
  search?: string;
  since?: number;
}

export function useServerLogs(params: ServerLogsParams = {}, options?: { refetchInterval?: number }) {
  const qs = new URLSearchParams();
  if (params.tail) qs.set("tail", String(params.tail));
  if (params.level) qs.set("level", params.level);
  if (params.search) qs.set("search", params.search);
  if (params.since) qs.set("since_minutes", String(params.since));
  const query = qs.toString();
  return useQuery({
    queryKey: ["server-logs", params],
    queryFn: () => apiFetch<ServerLogsResponse>(`/api/v1/admin/server-logs${query ? `?${query}` : ""}`),
    refetchInterval: options?.refetchInterval,
  });
}

export interface LogLevelResponse {
  level: string;
}

export function useLogLevel() {
  return useQuery({
    queryKey: ["log-level"],
    queryFn: () => apiFetch<LogLevelResponse>("/api/v1/admin/log-level"),
  });
}

export function useSetLogLevel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (level: string) =>
      apiFetch<LogLevelResponse>("/api/v1/admin/log-level", {
        method: "PUT",
        body: JSON.stringify({ level }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["log-level"] });
      qc.invalidateQueries({ queryKey: ["server-logs"] });
    },
  });
}
