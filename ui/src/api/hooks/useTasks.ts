import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { CronEntry } from "../../types/api";

export type StepType = "exec" | "tool" | "agent" | "user_prompt" | "foreach" | "machine_inspect" | "machine_exec";

export type ResponseSchema =
  | { type: "binary" }
  | { type: "multi_item"; items_ref?: string };

export interface StepDef {
  id: string;
  type: StepType;
  label?: string;
  prompt?: string;
  command?: string;
  working_directory?: string | null;
  tool_name?: string | null;
  tool_args?: Record<string, any> | null;
  model?: string | null;
  tools?: string[] | null;
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

export interface TaskLayout {
  version?: number;
  nodes?: Record<string, { x: number; y: number }>;
  camera?: { x: number; y: number; scale: number };
  // Forward-compatible: future keys are preserved verbatim by the backend.
  [key: string]: any;
}

export type SessionTarget =
  | { mode: "primary" }
  | { mode: "existing"; session_id: string }
  | { mode: "new_each_run" };

export type ProjectInstancePolicy =
  | { mode: "shared" }
  | { mode: "fresh" };

export interface MachineTargetGrant {
  provider_id: string;
  target_id: string;
  grant_id?: string | null;
  grant_source_task_id?: string | null;
  granted_by_user_id?: string | null;
  capabilities?: string[] | null;
  allow_agent_tools?: boolean | null;
  expires_at?: string | null;
  created_at?: string | null;
  provider_label?: string | null;
  target_label?: string | null;
  diagnostics?: MachineAutomationDiagnostic[] | null;
}

export interface MachineAutomationDiagnostic {
  severity: "info" | "warning" | "error" | string;
  code: string;
  message: string;
}

export interface MachineAutomationTargetOption {
  provider_id: string;
  provider_label?: string | null;
  target_id: string;
  driver?: string | null;
  label: string;
  hostname?: string | null;
  platform?: string | null;
  ready: boolean;
  status?: string | null;
  status_label?: string | null;
  reason?: string | null;
  checked_at?: string | null;
  handle_id?: string | null;
  capabilities?: string[] | null;
}

export interface MachineAutomationProviderOption {
  provider_id: string;
  provider_label: string;
  driver: string;
  label: string;
  target_label: string;
  description?: string | null;
  capabilities: string[];
  targets: MachineAutomationTargetOption[];
  target_count: number;
  ready_target_count: number;
}

export interface MachineAutomationOptions {
  providers: MachineAutomationProviderOption[];
  step_types: Array<{ type: "machine_inspect" | "machine_exec"; label: string; capability: "inspect" | "exec" }>;
}

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
  run_isolation?: "inline" | "sub_session";
  run_session_id?: string | null;
  project_instance_id?: string | null;
  session_target?: SessionTarget | null;
  dispatch_config?: Record<string, any> | null;
  callback_config?: Record<string, any> | null;
  execution_config?: Record<string, any> | null;
  delegation_session_id?: string | null;
  trigger_config?: Record<string, any> | null;
  machine_target_grant?: MachineTargetGrant | null;
  machine_automation_diagnostics?: MachineAutomationDiagnostic[];
  steps?: StepDef[] | null;
  step_states?: StepState[] | null;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  harness_effort?: string | null;
  skip_tool_approval?: boolean | null;
  allow_issue_reporting?: boolean | null;
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
  subscription_count?: number;
  layout?: TaskLayout;
}

export interface TaskCreatePayload {
  prompt?: string;
  bot_id: string;
  title?: string | null;
  channel_id?: string | null;
  session_target?: SessionTarget | null;
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
  harness_effort?: string | null;
  skip_tool_approval?: boolean | null;
  allow_issue_reporting?: boolean | null;
  workflow_id?: string | null;
  workflow_session_mode?: string | null;
  trigger_config?: Record<string, any> | null;
  skills?: string[] | null;
  tools?: string[] | null;
  steps?: StepDef[] | null;
  layout?: TaskLayout | null;
  post_final_to_channel?: boolean | null;
  history_mode?: "none" | "recent" | "full" | null;
  history_recent_count?: number | null;
  project_instance?: ProjectInstancePolicy | null;
  machine_target_grant?: MachineTargetGrant | null;
}

export interface TaskUpdatePayload {
  prompt?: string;
  bot_id?: string;
  title?: string | null;
  channel_id?: string | null;
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
  harness_effort?: string | null;
  skip_tool_approval?: boolean | null;
  allow_issue_reporting?: boolean | null;
  workflow_id?: string | null;
  workflow_session_mode?: string | null;
  trigger_config?: Record<string, any> | null;
  skills?: string[] | null;
  tools?: string[] | null;
  steps?: StepDef[] | null;
  layout?: TaskLayout | null;
  post_final_to_channel?: boolean | null;
  history_mode?: "none" | "recent" | "full" | null;
  history_recent_count?: number | null;
  project_instance?: ProjectInstancePolicy | null;
  session_target?: SessionTarget | null;
  machine_target_grant?: MachineTargetGrant | null;
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

export function useTaskMachineAutomationOptions() {
  return useQuery({
    queryKey: ["admin-task-machine-automation-options"],
    queryFn: () => apiFetch<MachineAutomationOptions>("/api/v1/admin/tasks/machine-automation-options"),
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });
}

export interface UseTaskOptions {
  /** Polling interval in ms. Accepts a function of the latest task row for
   *  dynamic cadence (e.g. poll only while non-terminal). Return ``false``
   *  to stop polling. */
  refetchInterval?:
    | number
    | false
    | ((task: TaskDetail | undefined) => number | false);
}

export function useTask(taskId: string | undefined, options: UseTaskOptions = {}) {
  const { refetchInterval } = options;
  return useQuery({
    queryKey: ["admin-task", taskId],
    queryFn: () => apiFetch<TaskDetail>(`/api/v1/admin/tasks/${taskId}`),
    enabled: !!taskId,
    refetchInterval:
      typeof refetchInterval === "function"
        ? (query) => refetchInterval(query.state.data as TaskDetail | undefined)
        : refetchInterval,
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

export interface RunTaskArgs {
  taskId: string;
  /** Optional runtime params merged into the child's execution_config.params
      (for system pipelines declaring a params_schema). */
  params?: Record<string, any>;
  /** Optional channel override for the child run. Required when the pipeline
      declares execution_config.requires_channel = true. */
  channel_id?: string;
  /** Optional bot override for the child run. Required when the pipeline
      declares execution_config.requires_bot = true. */
  bot_id?: string;
  /** Optional run target override for the selected channel session. */
  session_target?: SessionTarget | null;
}

export function useRunTaskNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (arg: string | RunTaskArgs) => {
      const norm: RunTaskArgs =
        typeof arg === "string" ? { taskId: arg } : arg;
      const body: Record<string, any> = {};
      if (norm.params && Object.keys(norm.params).length > 0) body.params = norm.params;
      if (norm.channel_id) body.channel_id = norm.channel_id;
      if (norm.bot_id) body.bot_id = norm.bot_id;
      if (norm.session_target) body.session_target = norm.session_target;
      return apiFetch<TaskDetail>(`/api/v1/admin/tasks/${norm.taskId}/run`, {
        method: "POST",
        ...(Object.keys(body).length > 0
          ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
          : {}),
      });
    },
    onSuccess: (_data, arg) => {
      const taskId = typeof arg === "string" ? arg : arg.taskId;
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
