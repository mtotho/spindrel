import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface TaskDetail {
  id: string;
  status: string;
  bot_id: string;
  prompt: string;
  prompt_template_id?: string | null;
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
  retry_count: number;
  run_count: number;
  created_at: string;
  scheduled_at?: string | null;
  run_at?: string | null;
  completed_at?: string | null;
  is_schedule?: boolean;
}

export interface TaskCreatePayload {
  prompt: string;
  bot_id: string;
  channel_id?: string | null;
  prompt_template_id?: string | null;
  scheduled_at?: string | null;
  recurrence?: string | null;
  task_type?: string;
  trigger_rag_loop?: boolean;
  model_override?: string | null;
  model_provider_id_override?: string | null;
}

export interface TaskUpdatePayload {
  prompt?: string;
  bot_id?: string;
  prompt_template_id?: string | null;
  status?: string;
  scheduled_at?: string | null;
  recurrence?: string | null;
  task_type?: string;
  trigger_rag_loop?: boolean;
  model_override?: string | null;
  model_provider_id_override?: string | null;
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
    },
  });
}
