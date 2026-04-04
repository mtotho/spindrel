import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { Workflow, WorkflowRun, WorkflowConnection } from "../../types/api";
import type { TasksResponse } from "../../components/shared/TaskConstants";

export function useWorkflows() {
  return useQuery({
    queryKey: ["workflows"],
    queryFn: () => apiFetch<Workflow[]>("/api/v1/admin/workflows"),
  });
}

export function useWorkflowTemplates() {
  return useQuery({
    queryKey: ["workflow-templates"],
    queryFn: () => apiFetch<Workflow[]>("/api/v1/admin/workflows/templates"),
  });
}

export function useWorkflow(id?: string) {
  return useQuery({
    queryKey: ["workflows", id],
    queryFn: () => apiFetch<Workflow>(`/api/v1/admin/workflows/${id}`),
    enabled: !!id,
  });
}

export function useCreateWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Workflow> & { id: string; name: string }) =>
      apiFetch<Workflow>("/api/v1/admin/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useUpdateWorkflow(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Workflow>) =>
      apiFetch<Workflow>(`/api/v1/admin/workflows/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflows", id] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useDeleteWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/admin/workflows/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

// --- Recent Runs (cross-workflow, for list page) ---

export function useRecentWorkflowRuns() {
  return useQuery({
    queryKey: ["workflow-runs-recent"],
    queryFn: () => apiFetch<WorkflowRun[]>("/api/v1/admin/workflow-runs/recent?limit=30"),
    refetchInterval: (query) => {
      const runs = query.state.data;
      if (runs?.some((r) => r.status === "running" || r.status === "awaiting_approval")) return 5000;
      return false;
    },
  });
}

// --- Active Runs (global, for HUD) ---

export function useActiveWorkflowRuns() {
  return useQuery({
    queryKey: ["workflow-runs-active"],
    queryFn: async () => {
      const runs = await apiFetch<WorkflowRun[]>("/api/v1/admin/workflow-runs/recent?limit=20");
      return runs.filter((r) => r.status === "running" || r.status === "awaiting_approval");
    },
    refetchInterval: (query) => {
      const runs = query.state.data;
      if (runs && runs.length > 0) return 3000;
      return 5000; // Poll frequently to catch newly started runs quickly
    },
  });
}

// --- Workflow Runs ---

export function useWorkflowRuns(workflowId?: string) {
  return useQuery({
    queryKey: ["workflow-runs", workflowId],
    queryFn: () => apiFetch<WorkflowRun[]>(`/api/v1/admin/workflows/${workflowId}/runs`),
    enabled: !!workflowId,
    refetchInterval: (query) => {
      const runs = query.state.data;
      if (runs?.some((r) => r.status === "running" || r.status === "awaiting_approval")) return 3000;
      return false;
    },
  });
}

export function useWorkflowRun(runId?: string) {
  return useQuery({
    queryKey: ["workflow-run", runId],
    queryFn: () => apiFetch<WorkflowRun>(`/api/v1/admin/workflow-runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (query) => {
      const run = query.state.data;
      if (run && (run.status === "running" || run.status === "awaiting_approval")) return 1000;
      return false;
    },
  });
}

export function useTriggerWorkflow(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { params: Record<string, any>; bot_id?: string; channel_id?: string; session_mode?: string }) =>
      apiFetch<WorkflowRun>(`/api/v1/admin/workflows/${workflowId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (run) => {
      // Seed the run cache so navigating to the new run shows data immediately
      qc.setQueryData(["workflow-run", run.id], run);
      qc.invalidateQueries({ queryKey: ["workflow-runs", workflowId] });
      qc.invalidateQueries({ queryKey: ["workflow-runs-active"] });
      qc.invalidateQueries({ queryKey: ["workflow-runs-recent"] });
      if (run.channel_id) {
        qc.invalidateQueries({ queryKey: ["channel-workflow-runs", run.channel_id] });
      }
    },
  });
}

export function useCancelWorkflowRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      apiFetch<WorkflowRun>(`/api/v1/admin/workflow-runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: (_data, runId) => {
      qc.invalidateQueries({ queryKey: ["workflow-run", runId] });
      qc.invalidateQueries({ queryKey: ["workflow-runs"] });
      qc.invalidateQueries({ queryKey: ["workflow-runs-active"] });
      qc.invalidateQueries({ queryKey: ["workflow-runs-recent"] });
      qc.invalidateQueries({ queryKey: ["channel-workflow-runs"] });
    },
  });
}

export function useApproveWorkflowStep() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, stepIndex }: { runId: string; stepIndex: number }) =>
      apiFetch<WorkflowRun>(`/api/v1/admin/workflow-runs/${runId}/steps/${stepIndex}/approve`, {
        method: "POST",
      }),
    onSuccess: (_data, { runId }) => {
      qc.invalidateQueries({ queryKey: ["workflow-run", runId] });
      qc.invalidateQueries({ queryKey: ["workflow-runs"] });
      qc.invalidateQueries({ queryKey: ["workflow-runs-recent"] });
      qc.invalidateQueries({ queryKey: ["channel-workflow-runs"] });
    },
  });
}

export function useSkipWorkflowStep() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, stepIndex }: { runId: string; stepIndex: number }) =>
      apiFetch<WorkflowRun>(`/api/v1/admin/workflow-runs/${runId}/steps/${stepIndex}/skip`, {
        method: "POST",
      }),
    onSuccess: (_data, { runId }) => {
      qc.invalidateQueries({ queryKey: ["workflow-run", runId] });
      qc.invalidateQueries({ queryKey: ["workflow-runs"] });
      qc.invalidateQueries({ queryKey: ["workflow-runs-recent"] });
      qc.invalidateQueries({ queryKey: ["channel-workflow-runs"] });
    },
  });
}

export function useRetryWorkflowStep() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, stepIndex }: { runId: string; stepIndex: number }) =>
      apiFetch<WorkflowRun>(`/api/v1/admin/workflow-runs/${runId}/steps/${stepIndex}/retry`, {
        method: "POST",
      }),
    onSuccess: (_data, { runId }) => {
      qc.invalidateQueries({ queryKey: ["workflow-run", runId] });
      qc.invalidateQueries({ queryKey: ["workflow-runs"] });
      qc.invalidateQueries({ queryKey: ["workflow-runs-recent"] });
    },
  });
}

// --- Channel Workflow Connections (heartbeat + scheduled task triggers) ---

export function useChannelWorkflowConnections(channelId?: string) {
  return useQuery({
    queryKey: ["channel-workflow-connections", channelId],
    queryFn: () => apiFetch<WorkflowConnection[]>(`/api/v1/admin/channels/${channelId}/workflow-connections`),
    enabled: !!channelId,
  });
}

// --- Channel Workflow Runs (active runs for chat strip) ---

export function useChannelWorkflowRuns(channelId?: string) {
  return useQuery({
    queryKey: ["channel-workflow-runs", channelId],
    queryFn: () => apiFetch<WorkflowRun[]>(`/api/v1/admin/channels/${channelId}/workflow-runs`),
    enabled: !!channelId,
    refetchInterval: (query) => {
      const runs = query.state.data;
      if (runs && runs.length > 0) return 3000;
      return 10000; // Poll to catch workflow runs started by background processes
    },
  });
}

// --- Workflow Run Tasks ---

const TERMINAL_STATUSES = new Set(["complete", "failed", "cancelled"]);

export function useWorkflowRunTasks(runId?: string) {
  return useQuery({
    queryKey: ["workflow-run-tasks", runId],
    queryFn: () =>
      apiFetch<TasksResponse>(
        `/api/v1/admin/tasks?workflow_run_id=${runId}&include_children=true&limit=100`,
      ),
    enabled: !!runId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.tasks.some((t) => !TERMINAL_STATUSES.has(t.status))) return 3000;
      return false;
    },
  });
}

// --- Workflow Export ---

export function useExportWorkflow(workflowId: string) {
  return useMutation({
    mutationFn: async (): Promise<string> => {
      // Use raw fetch since apiFetch always parses JSON, but export returns YAML text
      const { useAuthStore, getAuthToken } = await import("../../stores/auth");
      const { serverUrl } = useAuthStore.getState();
      if (!serverUrl) throw new Error("Server not configured");
      const token = getAuthToken();
      const resp = await fetch(`${serverUrl}/api/v1/admin/workflows/${workflowId}/export`, {
        method: "POST",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!resp.ok) throw new Error(`Export failed: ${resp.status}`);
      return resp.text();
    },
  });
}
