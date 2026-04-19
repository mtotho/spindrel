import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface ToolCallItem {
  id: string;
  session_id: string | null;
  channel_id: string | null;
  bot_id: string | null;
  client_id: string | null;
  tool_name: string;
  tool_type: string;
  server_name: string | null;
  iteration: number | null;
  arguments: Record<string, any>;
  result: string | null;
  error: string | null;
  duration_ms: number | null;
  correlation_id: string | null;
  created_at: string;
}

export interface ToolCallStatGroup {
  key: string;
  count: number;
  total_duration_ms: number;
  avg_duration_ms: number;
  error_count: number;
}

export interface ToolCallStatsResponse {
  group_by: string;
  stats: ToolCallStatGroup[];
}

export interface ToolCallFilters {
  bot_id?: string;
  tool_name?: string;
  tool_type?: string;
  session_id?: string;
  error_only?: boolean;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export function useToolCalls(filters: ToolCallFilters = {}) {
  const params = new URLSearchParams();
  if (filters.bot_id) params.set("bot_id", filters.bot_id);
  if (filters.tool_name) params.set("tool_name", filters.tool_name);
  if (filters.tool_type) params.set("tool_type", filters.tool_type);
  if (filters.session_id) params.set("session_id", filters.session_id);
  if (filters.error_only) params.set("error_only", "true");
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const qs = params.toString();

  return useQuery({
    queryKey: ["tool-calls", filters],
    queryFn: () =>
      apiFetch<ToolCallItem[]>(`/api/v1/tool-calls${qs ? `?${qs}` : ""}`),
  });
}

export function useToolCall(toolCallId: string | undefined) {
  return useQuery({
    queryKey: ["tool-call", toolCallId],
    queryFn: () => apiFetch<ToolCallItem>(`/api/v1/tool-calls/${toolCallId}`),
    enabled: !!toolCallId,
  });
}

export function useToolCallStats(
  groupBy: "tool_name" | "bot_id" | "tool_type" = "tool_name",
  botId?: string
) {
  const params = new URLSearchParams({ group_by: groupBy });
  if (botId) params.set("bot_id", botId);
  const qs = params.toString();

  return useQuery({
    queryKey: ["tool-call-stats", groupBy, botId],
    queryFn: () =>
      apiFetch<ToolCallStatsResponse>(
        `/api/v1/tool-calls/stats${qs ? `?${qs}` : ""}`
      ),
  });
}
