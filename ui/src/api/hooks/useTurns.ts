import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface TurnToolCall {
  tool_name: string;
  tool_type: string;
  iteration?: number | null;
  duration_ms?: number | null;
  error?: string | null;
  arguments_preview?: string | null;
  result_preview?: string | null;
}

export interface TurnError {
  event_name?: string | null;
  message?: string | null;
  created_at?: string | null;
}

export interface TurnSummary {
  correlation_id: string;
  created_at: string;
  bot_id?: string | null;
  model?: string | null;
  channel_id?: string | null;
  channel_name?: string | null;
  session_id?: string | null;
  user_message?: string | null;
  response_preview?: string | null;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  iterations: number;
  duration_ms?: number | null;
  llm_duration_ms: number;
  has_error: boolean;
  tool_call_count: number;
  tool_calls: TurnToolCall[];
  errors: TurnError[];
}

export interface TurnsListResponse {
  turns: TurnSummary[];
  total: number;
  count: number;
}

export interface TurnsParams {
  count?: number;
  channel_id?: string;
  bot_id?: string;
  after?: string;
  before?: string;
  has_error?: boolean;
  has_tool_calls?: boolean;
  search?: string;
}

export function useTurns(params: TurnsParams) {
  const qs = new URLSearchParams();
  if (params.count) qs.set("count", String(params.count));
  if (params.channel_id) qs.set("channel_id", params.channel_id);
  if (params.bot_id) qs.set("bot_id", params.bot_id);
  if (params.after) qs.set("after", params.after);
  if (params.before) qs.set("before", params.before);
  if (params.has_error === true) qs.set("has_error", "true");
  if (params.has_error === false) qs.set("has_error", "false");
  if (params.has_tool_calls === true) qs.set("has_tool_calls", "true");
  if (params.has_tool_calls === false) qs.set("has_tool_calls", "false");
  if (params.search) qs.set("search", params.search);
  const query = qs.toString();

  return useQuery({
    queryKey: ["admin-turns", params],
    queryFn: () =>
      apiFetch<TurnsListResponse>(`/api/v1/admin/turns${query ? `?${query}` : ""}`),
  });
}
