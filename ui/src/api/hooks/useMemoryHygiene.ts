import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface JobStatus {
  enabled: boolean;
  interval_hours: number;
  only_if_active: boolean;
  has_custom_prompt: boolean;
  resolved_prompt: string;
  extra_instructions: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  last_task_status: string | null;
  last_task_id: string | null;
  model: string | null;
  model_provider_id: string | null;
  target_hour: number;
}

/** Combined response from GET /bots/{id}/memory-hygiene */
export interface MemoryHygieneStatus {
  memory_hygiene: JobStatus;
  skill_review: JobStatus;
  // Legacy flat fields (memory_hygiene values) for backward compat
  enabled: boolean;
  interval_hours: number;
  only_if_active: boolean;
  has_custom_prompt: boolean;
  resolved_prompt: string;
  last_run_at: string | null;
  next_run_at: string | null;
  last_task_status: string | null;
  last_task_id: string | null;
  model: string | null;
  model_provider_id: string | null;
  target_hour: number;
}

export type HygieneJobType = "memory_hygiene" | "skill_review";

export interface MemoryHygieneRun {
  id: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  result?: string | null;
  error?: string | null;
  correlation_id?: string | null;
  tool_calls: {
    tool_name: string;
    tool_type: string;
    iteration?: number | null;
    duration_ms?: number | null;
    error?: string | null;
  }[];
  total_tokens: number;
  iterations: number;
  duration_ms?: number | null;
  job_type: string;
}

export function useMemoryHygieneStatus(botId: string | undefined) {
  return useQuery({
    queryKey: ["memory-hygiene", botId],
    queryFn: () =>
      apiFetch<MemoryHygieneStatus>(
        `/api/v1/admin/bots/${botId}/memory-hygiene`
      ),
    enabled: !!botId,
    refetchInterval: 30_000,
  });
}

export function useMemoryHygieneRuns(botId: string | undefined, jobType: string = "all") {
  return useQuery({
    queryKey: ["memory-hygiene-runs", botId, jobType],
    queryFn: () =>
      apiFetch<{ runs: MemoryHygieneRun[]; total: number }>(
        `/api/v1/admin/bots/${botId}/memory-hygiene/runs?job_type=${jobType}`
      ),
    enabled: !!botId,
    refetchInterval: 30_000,
  });
}

export function useTriggerMemoryHygiene() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, jobType = "memory_hygiene" }: { botId: string; jobType?: HygieneJobType }) =>
      apiFetch<{ status: string; task_id: string; job_type: string }>(
        `/api/v1/admin/bots/${botId}/memory-hygiene/trigger?job_type=${jobType}`,
        { method: "POST" }
      ),
    onSuccess: (_data, { botId }) => {
      qc.invalidateQueries({ queryKey: ["memory-hygiene", botId] });
      qc.invalidateQueries({ queryKey: ["memory-hygiene-runs", botId] });
      qc.invalidateQueries({ queryKey: ["learning-overview"] });
    },
  });
}
