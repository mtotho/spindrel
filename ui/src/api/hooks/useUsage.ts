import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface UsageParams {
  after?: string;
  before?: string;
  bot_id?: string;
  model?: string;
  provider_id?: string;
  channel_id?: string;
  [key: string]: string | number | undefined;
}

export interface CostByDimension {
  label: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost: number | null;
  has_cost_data: boolean;
}

export interface UsageSummary {
  total_calls: number;
  total_tokens: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost: number | null;
  cost_by_model: CostByDimension[];
  cost_by_bot: CostByDimension[];
  cost_by_provider: CostByDimension[];
  models_without_cost_data: string[];
  calls_without_cost_data: number;
}

export interface UsageLogEntry {
  id: string;
  created_at: string;
  correlation_id: string | null;
  model: string | null;
  provider_id: string | null;
  provider_name: string | null;
  bot_id: string | null;
  channel_id: string | null;
  channel_name: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost: number | null;
  has_cost_data: boolean;
  duration_ms: number | null;
}

export interface UsageLogsResponse {
  entries: UsageLogEntry[];
  total: number;
  page: number;
  page_size: number;
  bot_ids: string[];
  model_names: string[];
  provider_ids: string[];
}

export interface BreakdownGroup {
  label: string;
  calls: number;
  tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost: number | null;
}

export interface UsageBreakdownResponse {
  group_by: string;
  groups: BreakdownGroup[];
}

export interface TimeseriesPoint {
  bucket: string;
  cost: number | null;
  tokens: number;
  calls: number;
}

export interface UsageTimeseriesResponse {
  bucket_size: string;
  points: TimeseriesPoint[];
}

export interface UsageAnomalyMetric {
  tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  calls: number;
  cost: number | null;
  has_cost_data: boolean;
}

export interface UsageAnomalySource {
  source_type: string;
  title?: string | null;
  task_id?: string | null;
  task_type?: string | null;
  bot_id?: string | null;
  channel_id?: string | null;
  channel_name?: string | null;
  model?: string | null;
  provider_id?: string | null;
  provider_name?: string | null;
}

export interface UsageAnomalySignal {
  id: string;
  kind: string;
  label: string;
  severity: "info" | "warning" | "danger";
  reason: string;
  created_at?: string | null;
  bucket?: string | null;
  correlation_id?: string | null;
  dimension?: string | null;
  dimension_value?: string | null;
  metric: UsageAnomalyMetric;
  baseline?: UsageAnomalyMetric | null;
  ratio?: number | null;
  cost_confidence: "metered" | "plan" | "local" | "missing" | "unknown" | string;
  source: UsageAnomalySource;
}

export interface UsageAnomaliesResponse {
  window_start: string;
  window_end: string;
  baseline_start: string;
  baseline_end: string;
  bucket_size: string;
  time_spikes: UsageAnomalySignal[];
  trace_bursts: UsageAnomalySignal[];
  contributors: UsageAnomalySignal[];
}

function buildQS(params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "" && v !== null) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export function useUsageSummary(params: UsageParams) {
  return useQuery({
    queryKey: ["usage-summary", params],
    queryFn: () =>
      apiFetch<UsageSummary>(`/api/v1/admin/usage/summary${buildQS(params)}`),
  });
}

export function useUsageLogs(params: UsageParams & { page?: number; page_size?: number }) {
  return useQuery({
    queryKey: ["usage-logs", params],
    queryFn: () =>
      apiFetch<UsageLogsResponse>(`/api/v1/admin/usage/logs${buildQS(params)}`),
  });
}

export function useUsageBreakdown(params: UsageParams & { group_by?: string }) {
  return useQuery({
    queryKey: ["usage-breakdown", params],
    queryFn: () =>
      apiFetch<UsageBreakdownResponse>(`/api/v1/admin/usage/breakdown${buildQS(params)}`),
  });
}

export function useUsageTimeSeries(params: UsageParams & { bucket?: string }) {
  return useQuery({
    queryKey: ["usage-timeseries", params],
    queryFn: () =>
      apiFetch<UsageTimeseriesResponse>(`/api/v1/admin/usage/timeseries${buildQS(params)}`),
  });
}

export function useUsageAnomalies(params: UsageParams & { source_type?: string }) {
  return useQuery({
    queryKey: ["usage-anomalies", params],
    queryFn: () =>
      apiFetch<UsageAnomaliesResponse>(`/api/v1/admin/usage/anomalies${buildQS(params)}`),
  });
}
