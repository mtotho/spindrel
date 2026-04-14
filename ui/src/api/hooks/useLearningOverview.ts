import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface BotDreamingStatus {
  bot_id: string;
  bot_name: string;
  enabled: boolean;
  last_run_at: string | null;
  last_task_status: string | null;
  next_run_at: string | null;
  interval_hours: number;
  model: string | null;
}

export interface LearningHygieneRun {
  id: string;
  bot_id: string;
  bot_name: string;
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
  files_affected: string[];
}

export interface MemoryFileActivity {
  bot_id: string;
  bot_name: string;
  file_path: string;
  operation: string;
  created_at: string;
  is_hygiene: boolean;
  correlation_id?: string | null;
}

export interface LearningOverview {
  total_bots: number;
  dreaming_enabled_count: number;
  total_hygiene_runs_7d: number;
  total_bot_skills: number;
  total_surfacings: number;
  total_auto_injects: number;
  bots: BotDreamingStatus[];
  recent_runs: LearningHygieneRun[];
  memory_activity: MemoryFileActivity[];
}

export function useLearningOverview() {
  return useQuery({
    queryKey: ["learning-overview"],
    queryFn: () =>
      apiFetch<LearningOverview>("/api/v1/admin/learning/overview"),
    refetchInterval: 30_000,
  });
}
