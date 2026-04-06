import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface MemoryHygieneStatus {
  enabled: boolean;
  interval_hours: number;
  only_if_active: boolean;
  has_custom_prompt: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  last_task_status: string | null;
  last_task_id: string | null;
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
    },
  });
}
