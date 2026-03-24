import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface LogRow {
  kind: string;
  id: string;
  created_at?: string | null;
  correlation_id?: string | null;
  session_id?: string | null;
  bot_id?: string | null;
  client_id?: string | null;
  // tool_call
  tool_name?: string | null;
  tool_type?: string | null;
  arguments?: Record<string, any> | null;
  result?: string | null;
  error?: string | null;
  duration_ms?: number | null;
  // trace_event
  event_type?: string | null;
  event_name?: string | null;
  count?: number | null;
  data?: Record<string, any> | null;
}

export interface LogListResponse {
  rows: LogRow[];
  total: number;
  page: number;
  page_size: number;
  bot_ids: string[];
}

export interface TraceEvent {
  kind: string;
  created_at?: string | null;
  tool_name?: string | null;
  tool_type?: string | null;
  arguments?: Record<string, any> | null;
  result?: string | null;
  error?: string | null;
  duration_ms?: number | null;
  event_type?: string | null;
  event_name?: string | null;
  count?: number | null;
  data?: Record<string, any> | null;
  role?: string | null;
  content?: string | null;
}

export interface TraceDetailResponse {
  events: TraceEvent[];
  correlation_id: string;
  session_id?: string | null;
  bot_id?: string | null;
  client_id?: string | null;
  time_range_start?: string | null;
  time_range_end?: string | null;
}

export interface LogsParams {
  event_type?: string;
  bot_id?: string;
  session_id?: string;
  channel_id?: string;
  page?: number;
  page_size?: number;
}

export function useLogs(params: LogsParams) {
  const qs = new URLSearchParams();
  if (params.event_type) qs.set("event_type", params.event_type);
  if (params.bot_id) qs.set("bot_id", params.bot_id);
  if (params.session_id) qs.set("session_id", params.session_id);
  if (params.channel_id) qs.set("channel_id", params.channel_id);
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  const query = qs.toString();

  return useQuery({
    queryKey: ["admin-logs", params],
    queryFn: () =>
      apiFetch<LogListResponse>(`/api/v1/admin/logs${query ? `?${query}` : ""}`),
  });
}

export function useTrace(correlationId: string | undefined) {
  return useQuery({
    queryKey: ["admin-trace", correlationId],
    queryFn: () =>
      apiFetch<TraceDetailResponse>(`/api/v1/admin/traces/${correlationId}`),
    enabled: !!correlationId,
  });
}
