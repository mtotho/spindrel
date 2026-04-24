import { useMutation, useQuery } from "@tanstack/react-query";
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
  // Skill review fields
  skill_review_enabled: boolean;
  skill_review_last_run_at: string | null;
  skill_review_last_task_status: string | null;
  skill_review_next_run_at: string | null;
  skill_review_interval_hours: number;
  skill_review_model: string | null;
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
  job_type: string;
}

export interface MemoryFileActivity {
  bot_id: string;
  bot_name: string;
  file_path: string;
  operation: string;
  created_at: string;
  is_hygiene: boolean;
  correlation_id?: string | null;
  job_type?: string | null;
  source_file?: SourceFileTarget | null;
}

export interface LearningOverview {
  total_bots: number;
  dreaming_enabled_count: number;
  hygiene_runs: number;
  total_bot_skills: number;
  surfacings: number;
  auto_injects: number;
  days: number;
  bots: BotDreamingStatus[];
  recent_runs: LearningHygieneRun[];
  memory_activity: MemoryFileActivity[];
}

export type LearningSearchSource = "memory" | "bot_knowledge" | "channel_knowledge" | "history";

export interface SourceFileTarget {
  kind: "workspace_file";
  workspace_id: string;
  path: string;
  display_path: string;
  owner_type: "bot" | "channel";
  owner_id: string;
  owner_name: string;
}

export interface LearningSearchRequest {
  query: string;
  sources?: LearningSearchSource[];
  bot_ids?: string[];
  channel_ids?: string[];
  days?: number;
  top_k_per_source?: number;
}

export interface LearningSearchResult {
  id: string;
  source: LearningSearchSource;
  title: string;
  snippet: string;
  score?: number | null;
  bot_id?: string | null;
  bot_name?: string | null;
  channel_id?: string | null;
  channel_name?: string | null;
  file_path?: string | null;
  section?: number | null;
  created_at?: string | null;
  correlation_id?: string | null;
  open_url?: string | null;
  source_file?: SourceFileTarget | null;
  metadata: Record<string, unknown>;
}

export interface LearningSearchResponse {
  query: string;
  results: LearningSearchResult[];
}

export interface KnowledgeLibraryItem {
  source: "bot_knowledge" | "channel_knowledge";
  owner_id: string;
  owner_name: string;
  path_prefix: string;
  file_count: number;
  chunk_count: number;
  last_indexed_at?: string | null;
  open_url?: string | null;
}

export interface KnowledgeLibraryResponse {
  items: KnowledgeLibraryItem[];
}

export function useLearningOverview(days = 0) {
  return useQuery({
    queryKey: ["learning-overview", days],
    queryFn: () =>
      apiFetch<LearningOverview>(`/api/v1/admin/learning/overview?days=${days}`),
    refetchInterval: 30_000,
  });
}

export interface DailyActivityPoint {
  date: string;
  surfacings: number;
  auto_injects: number;
  memory_writes: number;
}

export function useLearningActivity(days = 14) {
  return useQuery({
    queryKey: ["learning-activity", days],
    queryFn: () =>
      apiFetch<DailyActivityPoint[]>(`/api/v1/admin/learning/activity?days=${days}`),
    refetchInterval: 60_000,
  });
}

export function useLearningSearch() {
  return useMutation({
    mutationFn: (body: LearningSearchRequest) =>
      apiFetch<LearningSearchResponse>("/api/v1/admin/learning/search", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  });
}

export function useLearningMemoryActivity(days = 30) {
  return useQuery({
    queryKey: ["learning-memory-activity", days],
    queryFn: () =>
      apiFetch<MemoryFileActivity[]>(`/api/v1/admin/learning/memory-activity?days=${days}`),
    refetchInterval: 30_000,
  });
}

export function useKnowledgeLibrary() {
  return useQuery({
    queryKey: ["learning-knowledge-library"],
    queryFn: () =>
      apiFetch<KnowledgeLibraryResponse>("/api/v1/admin/learning/knowledge-library"),
    refetchInterval: 60_000,
  });
}
