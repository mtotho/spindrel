import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SystemHealthFinding {
  service: string;
  severity: "info" | "warning" | "error" | "critical";
  signature: string;
  dedupe_key: string;
  title: string;
  sample: string;
  first_seen: string;
  last_seen: string;
  count: number;
  kind?: string | null;
}

export interface SystemHealthSummary {
  id: string;
  generated_at: string | null;
  period_start: string | null;
  period_end: string | null;
  error_count: number;
  critical_count: number;
  trace_event_count: number;
  tool_error_count: number;
  source_counts: Record<string, number>;
  findings: SystemHealthFinding[];
  attention_item_id: string | null;
  attention_item_refs: string[];
}

interface LatestResponse {
  summary: SystemHealthSummary | null;
  message?: string;
}

interface ListResponse {
  summaries: SystemHealthSummary[];
}

export const SYSTEM_HEALTH_LATEST_KEY = ["system-health", "latest"] as const;
export const SYSTEM_HEALTH_LIST_KEY = ["system-health", "list"] as const;

export function useLatestHealthSummary() {
  return useQuery<LatestResponse>({
    queryKey: SYSTEM_HEALTH_LATEST_KEY,
    queryFn: () => apiFetch<LatestResponse>("/api/v1/system-health/summaries/latest"),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}

export function useHealthSummaries(limit = 14) {
  return useQuery<ListResponse>({
    queryKey: [...SYSTEM_HEALTH_LIST_KEY, limit] as const,
    queryFn: () =>
      apiFetch<ListResponse>(
        `/api/v1/system-health/summaries?limit=${encodeURIComponent(limit)}`,
      ),
    staleTime: 5 * 60_000,
  });
}
