import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface MemoryHygieneStatus {
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
}

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

export function useMemoryHygieneRuns(botId: string | undefined) {
  return useQuery({
    queryKey: ["memory-hygiene-runs", botId],
    queryFn: () =>
      apiFetch<{ runs: MemoryHygieneRun[]; total: number }>(
        `/api/v1/admin/bots/${botId}/memory-hygiene/runs`
      ),
    enabled: !!botId,
    refetchInterval: 30_000,
  });
}

export function useTriggerMemoryHygiene() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) =>
      apiFetch<{ status: string; task_id: string }>(
        `/api/v1/admin/bots/${botId}/memory-hygiene/trigger`,
        { method: "POST" }
      ),
    onSuccess: (_data, botId) => {
      qc.invalidateQueries({ queryKey: ["memory-hygiene", botId] });
      qc.invalidateQueries({ queryKey: ["memory-hygiene-runs", botId] });
    },
  });
}
