import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { CronEntry } from "../../types/api";

export type StepType = "exec" | "tool" | "agent" | "user_prompt" | "foreach";

export type ResponseSchema =
  | { type: "binary" }
  | { type: "multi_item"; items_ref?: string };

export interface StepDef {
  id: string;
  type: StepType;
  label?: string;
  prompt?: string;
  working_directory?: string | null;
  tool_name?: string | null;
  tool_args?: Record<string, any> | null;
  model?: string | null;
  tools?: string[] | null;
  carapaces?: string[] | null;
  when?: Record<string, any> | null;
  on_failure?: "abort" | "continue";
  result_max_chars?: number;
  // user_prompt
  title?: string;
  widget_template?: Record<string, any> | null;
  widget_args?: Record<string, any> | null;
  response_schema?: ResponseSchema | null;
  // foreach
  over?: string;
  do?: StepDef[];
}

export type StepStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "skipped"
  | "awaiting_user_input";

export interface StepState {
  status: StepStatus;
  result?: string | null;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  task_id?: string | null;
  // user_prompt runtime payload
  widget_envelope?: Record<string, any> | null;
  response_schema?: ResponseSchema | null;
  // foreach runtime payload — sub-states parallel to sub-steps, one array per iteration
  items?: any[] | null;
  iterations?: StepState[][] | null;
}

export type TaskSource = "user" | "system";

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
  steps?: StepDef[] | null;
  step_states?: StepState[] | null;
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
  source?: TaskSource;
  last_run_status?: string | null;
  last_run_at?: string | null;
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
  steps?: StepDef[] | null;
  post_final_to_channel?: boolean | null;
  history_mode?: "none" | "recent" | "full" | null;
  history_recent_count?: number | null;
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
  steps?: StepDef[] | null;
  post_final_to_channel?: boolean | null;
  history_mode?: "none" | "recent" | "full" | null;
  history_recent_count?: number | null;
}

// ---------------------------------------------------------------------------
// Trigger events
// ---------------------------------------------------------------------------

export interface TriggerEventOption {
  type: string;
  label: string;
  description?: string;
  category?: string;
}

export interface TriggerEventSource {
  source: string;
  label: string;
  events: TriggerEventOption[];
  integration_type?: string;
  binding_id?: string;
  disabled?: boolean;
  activated?: boolean;
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

export function useRunTaskNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      apiFetch<TaskDetail>(`/api/v1/admin/tasks/${taskId}/run`, { method: "POST" }),
    onSuccess: (_data, taskId) => {
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
      qc.invalidateQueries({ queryKey: ["admin-task", taskId] });
      qc.invalidateQueries({ queryKey: ["admin-task-children", taskId] });
    },
  });
}

export function useTaskChildren(taskId: string | undefined, refetchInterval?: number | false) {
  return useQuery({
    queryKey: ["admin-task-children", taskId],
    queryFn: () => apiFetch<TaskDetail[]>(`/api/v1/admin/tasks/${taskId}/children`),
    enabled: !!taskId,
    refetchInterval: refetchInterval ?? false,
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
