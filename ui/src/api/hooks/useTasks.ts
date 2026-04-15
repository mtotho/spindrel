import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { CronEntry } from "../../types/api";

export interface TaskDetail {
  id: string;
  status: string;
  bot_id: string;
  prompt: string;
  title?: string | null;
  prompt_template_id?: string | null;
  workspace_file_path?: string | null;
  workspace_id?: string | null;
  result?: string | null;
  error?: string | null;
  dispatch_type: string;
  task_type: string;
  recurrence?: string | null;
  client_id?: string | null;
  session_id?: string | null;
  channel_id?: string | null;
  parent_task_id?: string | null;
  dispatch_config?: Record<string, any> | null;
  callback_config?: Record<string, any> | null;
  execution_config?: Record<string, any> | null;
  delegation_session_id?: string | null;
  trigger_config?: Record<string, any> | null;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  fallback_models?: { model: string; provider_id?: string | null }[] | null;
  workflow_id?: string | null;
  workflow_session_mode?: string | null;
  max_run_seconds?: number | null;
  trigger_rag_loop?: boolean;
  retry_count: number;
  correlation_id?: string | null;
  run_count: number;
  created_at: string;
  scheduled_at?: string | null;
  run_at?: string | null;
  completed_at?: string | null;
  is_schedule?: boolean;
}

export interface TaskCreatePayload {
  prompt?: string;
  bot_id: string;
  title?: string | null;
  channel_id?: string | null;
  prompt_template_id?: string | null;
  workspace_file_path?: string | null;
  workspace_id?: string | null;
  scheduled_at?: string | null;
  recurrence?: string | null;
  task_type?: string;
  fallback_models?: { model: string; provider_id?: string | null }[] | null;
  max_run_seconds?: number | null;
  trigger_rag_loop?: boolean;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  workflow_id?: string | null;
  workflow_session_mode?: string | null;
  trigger_config?: Record<string, any> | null;
  skills?: string[] | null;
  tools?: string[] | null;
}

export interface TaskUpdatePayload {
  prompt?: string;
  bot_id?: string;
  title?: string | null;
  prompt_template_id?: string | null;
  workspace_file_path?: string | null;
  workspace_id?: string | null;
  status?: string;
  scheduled_at?: string | null;
  recurrence?: string | null;
  task_type?: string;
  fallback_models?: { model: string; provider_id?: string | null }[] | null;
  max_run_seconds?: number | null;
  trigger_rag_loop?: boolean;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  workflow_id?: string | null;
  workflow_session_mode?: string | null;
  trigger_config?: Record<string, any> | null;
  skills?: string[] | null;
  tools?: string[] | null;
}

// ---------------------------------------------------------------------------
// Trigger events
// ---------------------------------------------------------------------------

export interface TriggerEventOption {
  type: string;
  label: string;
  description?: string;
}

export interface TriggerEventSource {
  source: string;
  label: string;
  events: TriggerEventOption[];
}

export function useTriggerEvents() {
  return useQuery({
    queryKey: ["admin-trigger-events"],
    queryFn: () => apiFetch<{ sources: TriggerEventSource[] }>("/api/v1/admin/tasks/trigger-events"),
    staleTime: 5 * 60_000,
  });
}

export function useTask(taskId: string | undefined) {
  return useQuery({
    queryKey: ["admin-task", taskId],
    queryFn: () => apiFetch<TaskDetail>(`/api/v1/admin/tasks/${taskId}`),
    enabled: !!taskId,
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: TaskCreatePayload) =>
      apiFetch<TaskDetail>("/api/v1/admin/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
      qc.invalidateQueries({ queryKey: ["channel-workflow-connections"] });
    },
  });
}

export function useUpdateTask(taskId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: TaskUpdatePayload) =>
      apiFetch<TaskDetail>(`/api/v1/admin/tasks/${taskId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
      qc.invalidateQueries({ queryKey: ["admin-task", taskId] });
      qc.invalidateQueries({ queryKey: ["channel-workflow-connections"] });
    },
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      apiFetch(`/api/v1/admin/tasks/${taskId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
      qc.invalidateQueries({ queryKey: ["channel-workflow-connections"] });
    },
  });
}

export function useTaskChildren(taskId: string | undefined) {
  return useQuery({
    queryKey: ["admin-task-children", taskId],
    queryFn: () => apiFetch<TaskDetail[]>(`/api/v1/admin/tasks/${taskId}/children`),
    enabled: !!taskId,
  });
}

export function useCronJobs(workspaceId?: string) {
  const params = workspaceId ? `?workspace_id=${workspaceId}` : "";
  return useQuery({
    queryKey: ["admin-cron-jobs", workspaceId ?? "all"],
    queryFn: () =>
      apiFetch<{ cron_jobs: CronEntry[]; errors: string[] }>(
        `/api/v1/admin/cron-jobs${params}`
      ),
  });
}
