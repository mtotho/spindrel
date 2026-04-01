import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { Workflow, WorkflowRun } from "../../types/api";

export function useWorkflows() {
  return useQuery({
    queryKey: ["workflows"],
    queryFn: () => apiFetch<Workflow[]>("/api/v1/admin/workflows"),
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

// --- Workflow Runs ---

export function useWorkflowRuns(workflowId?: string) {
  return useQuery({
    queryKey: ["workflow-runs", workflowId],
    queryFn: () => apiFetch<WorkflowRun[]>(`/api/v1/admin/workflows/${workflowId}/runs`),
    enabled: !!workflowId,
  });
}

export function useWorkflowRun(runId?: string) {
  return useQuery({
    queryKey: ["workflow-run", runId],
    queryFn: () => apiFetch<WorkflowRun>(`/api/v1/admin/workflow-runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (query) => {
      const run = query.state.data;
      if (run && (run.status === "running" || run.status === "awaiting_approval")) return 3000;
      return false;
    },
  });
}

export function useTriggerWorkflow(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { params: Record<string, any>; bot_id?: string; channel_id?: string }) =>
      apiFetch<WorkflowRun>(`/api/v1/admin/workflows/${workflowId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflow-runs", workflowId] });
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
    },
  });
}
