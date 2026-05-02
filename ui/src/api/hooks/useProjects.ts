import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type {
  Channel,
  Project,
  ProjectBlueprint,
  ProjectBlueprintFromCurrentResult,
  ProjectBlueprintFromCurrentWrite,
  ProjectBlueprintWrite,
  ProjectCodingRun,
  ProjectCodingRunReviewBatch,
  ProjectCodingRunReviewSessionLedger,
  ProjectCodingRunSchedule,
  ProjectCodingRunTask,
  ProjectFactoryReviewInbox,
  ProjectFromBlueprintWrite,
  ProjectInstance,
  ProjectRunReceipt,
  ProjectRuntimeEnv,
  ProjectDependencyStackState,
  ProjectSetup,
  ProjectSetupRun,
  ProjectWrite,
} from "../../types/api";
import type { MachineTargetGrant } from "./useTasks";

export function useProjects(enabled = true) {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => apiFetch<Project[]>("/api/v1/projects"),
    enabled,
  });
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => apiFetch<Project>(`/api/v1/projects/${projectId}`),
    enabled: !!projectId,
  });
}

export function useProjectFactoryReviewInbox(limit = 50) {
  return useQuery({
    queryKey: ["projects", "review-inbox", limit],
    queryFn: () => apiFetch<ProjectFactoryReviewInbox>(`/api/v1/projects/review-inbox?limit=${limit}`),
    refetchInterval: 60_000,
  });
}

export function useProjectChannels(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "channels"],
    queryFn: () => apiFetch<Pick<Channel, "id" | "name" | "bot_id">[]>(`/api/v1/projects/${projectId}/channels`),
    enabled: !!projectId,
  });
}

export function useProjectSetup(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "setup"],
    queryFn: () => apiFetch<ProjectSetup>(`/api/v1/projects/${projectId}/setup`),
    enabled: !!projectId,
  });
}

export function useProjectRuntimeEnv(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "runtime-env"],
    queryFn: () => apiFetch<ProjectRuntimeEnv>(`/api/v1/projects/${projectId}/runtime-env`),
    enabled: !!projectId,
  });
}

export function useProjectDependencyStack(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "dependency-stack"],
    queryFn: () => apiFetch<ProjectDependencyStackState>(`/api/v1/projects/${projectId}/dependency-stack`),
    enabled: !!projectId,
  });
}

export function useManageProjectDependencyStack(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { action: string; service?: string | null; command?: string | null; command_name?: string | null; tail?: number | null; keep_volumes?: boolean }) =>
      apiFetch<Record<string, any>>(`/api/v1/projects/${projectId}/dependency-stack`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "dependency-stack"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
    },
  });
}

export function useProjectInstances(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "instances"],
    queryFn: () => apiFetch<ProjectInstance[]>(`/api/v1/projects/${projectId}/instances`),
    enabled: !!projectId,
  });
}

export function useProjectRunReceipts(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "run-receipts"],
    queryFn: () => apiFetch<ProjectRunReceipt[]>(`/api/v1/projects/${projectId}/run-receipts`),
    enabled: !!projectId,
  });
}

export function useProjectCodingRuns(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "coding-runs"],
    queryFn: () => apiFetch<ProjectCodingRun[]>(`/api/v1/projects/${projectId}/coding-runs`),
    enabled: !!projectId,
  });
}

export function useProjectCodingRun(projectId: string | undefined, taskId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "coding-runs", taskId],
    queryFn: () => apiFetch<ProjectCodingRun>(`/api/v1/projects/${projectId}/coding-runs/${taskId}`),
    enabled: !!projectId && !!taskId,
  });
}

export function useProjectCodingRunReviewBatches(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "coding-runs", "review-batches"],
    queryFn: () => apiFetch<ProjectCodingRunReviewBatch[]>(`/api/v1/projects/${projectId}/coding-runs/review-batches`),
    enabled: !!projectId,
  });
}

export function useProjectCodingRunReviewSessions(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "coding-runs", "review-sessions"],
    queryFn: () => apiFetch<ProjectCodingRunReviewSessionLedger[]>(`/api/v1/projects/${projectId}/coding-runs/review-sessions`),
    enabled: !!projectId,
  });
}

export function useProjectCodingRunSchedules(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "coding-run-schedules"],
    queryFn: () => apiFetch<ProjectCodingRunSchedule[]>(`/api/v1/projects/${projectId}/coding-run-schedules`),
    enabled: !!projectId,
  });
}

export function useCreateProjectCodingRunSchedule(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { channel_id: string; title?: string; request?: string; scheduled_at?: string | null; recurrence?: string; machine_target_grant?: MachineTargetGrant | null }) =>
      apiFetch<ProjectCodingRunSchedule>(`/api/v1/projects/${projectId}/coding-run-schedules`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-run-schedules"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
    },
  });
}

export function useUpdateProjectCodingRunSchedule(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      scheduleId: string;
      channel_id?: string;
      title?: string;
      request?: string;
      scheduled_at?: string | null;
      recurrence?: string;
      enabled?: boolean;
      machine_target_grant?: MachineTargetGrant | null;
    }) => {
      const { scheduleId, ...body } = data;
      return apiFetch<ProjectCodingRunSchedule>(`/api/v1/projects/${projectId}/coding-run-schedules/${scheduleId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-run-schedules"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
    },
  });
}

export function useRunProjectCodingRunScheduleNow(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId: string) =>
      apiFetch<ProjectCodingRun>(`/api/v1/projects/${projectId}/coding-run-schedules/${scheduleId}/run-now`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-run-schedules"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
    },
  });
}

export function useDisableProjectCodingRunSchedule(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId: string) =>
      apiFetch<ProjectCodingRunSchedule>(`/api/v1/projects/${projectId}/coding-run-schedules/${scheduleId}`, {
        method: "DELETE",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-run-schedules"] }),
  });
}

export function useCreateProjectCodingRun(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { channel_id: string; request?: string; repo_path?: string | null; machine_target_grant?: MachineTargetGrant | null; source_work_pack_id?: string | null }) =>
      apiFetch<ProjectCodingRun>(`/api/v1/projects/${projectId}/coding-runs`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-batches"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-sessions"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
      qc.invalidateQueries({ queryKey: ["projects", "review-inbox"] });
    },
  });
}

export function useContinueProjectCodingRun(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { taskId: string; feedback: string }) =>
      apiFetch<ProjectCodingRun>(`/api/v1/projects/${projectId}/coding-runs/${data.taskId}/continue`, {
        method: "POST",
        body: JSON.stringify({ feedback: data.feedback }),
      }),
    onSuccess: (run, variables) => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", variables.taskId] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", run.task.id] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-batches"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-sessions"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
      qc.invalidateQueries({ queryKey: ["projects", "review-inbox"] });
    },
  });
}

function useProjectCodingRunAction(projectId: string | undefined, action: "refresh" | "reviewed" | "cleanup") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      apiFetch<ProjectCodingRun>(`/api/v1/projects/${projectId}/coding-runs/${taskId}/${action}`, {
        method: "POST",
      }),
    onSuccess: (run, taskId) => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", taskId] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", run.task.id] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-batches"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-sessions"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "instances"] });
      qc.invalidateQueries({ queryKey: ["projects", "review-inbox"] });
    },
  });
}

export function useRefreshProjectCodingRun(projectId: string | undefined) {
  return useProjectCodingRunAction(projectId, "refresh");
}

export function useMarkProjectCodingRunReviewed(projectId: string | undefined) {
  return useProjectCodingRunAction(projectId, "reviewed");
}

export function useMarkProjectCodingRunsReviewed(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { task_ids: string[]; note?: string }) =>
      apiFetch<ProjectCodingRun[]>(`/api/v1/projects/${projectId}/coding-runs/reviewed`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-batches"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-sessions"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
      qc.invalidateQueries({ queryKey: ["projects", "review-inbox"] });
    },
  });
}

export function useCreateProjectCodingRunReviewSession(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { channel_id: string; task_ids: string[]; prompt?: string; merge_method?: "squash" | "merge" | "rebase"; machine_target_grant?: MachineTargetGrant | null }) =>
      apiFetch<ProjectCodingRunTask>(`/api/v1/projects/${projectId}/coding-runs/review-sessions`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-batches"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-sessions"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
      qc.invalidateQueries({ queryKey: ["projects", "review-inbox"] });
    },
  });
}

export function useCleanupProjectCodingRun(projectId: string | undefined) {
  return useProjectCodingRunAction(projectId, "cleanup");
}

export function useCreateProjectInstance(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<ProjectInstance>(`/api/v1/projects/${projectId}/instances`, {
        method: "POST",
        body: JSON.stringify({ owner_kind: "manual" }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "instances"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId] });
    },
  });
}

export function useCleanupProjectInstance(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (instanceId: string) =>
      apiFetch<ProjectInstance>(`/api/v1/projects/${projectId}/instances/${instanceId}/cleanup`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "instances"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-batches"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
    },
  });
}

export function useProjectBlueprints(enabled = true) {
  return useQuery({
    queryKey: ["project-blueprints"],
    queryFn: () => apiFetch<ProjectBlueprint[]>("/api/v1/projects/blueprints"),
    enabled,
  });
}

export function useProjectBlueprint(blueprintId: string | undefined) {
  return useQuery({
    queryKey: ["project-blueprints", blueprintId],
    queryFn: () => apiFetch<ProjectBlueprint>(`/api/v1/projects/blueprints/${blueprintId}`),
    enabled: !!blueprintId,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProjectWrite) =>
      apiFetch<Project>("/api/v1/projects", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useCreateProjectBlueprint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProjectBlueprintWrite) =>
      apiFetch<ProjectBlueprint>("/api/v1/projects/blueprints", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project-blueprints"] }),
  });
}

export function useUpdateProjectBlueprint(blueprintId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProjectBlueprintWrite) =>
      apiFetch<ProjectBlueprint>(`/api/v1/projects/blueprints/${blueprintId}`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-blueprints"] });
      qc.invalidateQueries({ queryKey: ["project-blueprints", blueprintId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useDeleteProjectBlueprint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (blueprintId: string) =>
      apiFetch<void>(`/api/v1/projects/blueprints/${blueprintId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-blueprints"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useCreateProjectFromBlueprint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProjectFromBlueprintWrite) =>
      apiFetch<Project>("/api/v1/projects/from-blueprint", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: (project) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["projects", project.id] });
    },
  });
}

export function useCreateProjectBlueprintFromCurrent(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProjectBlueprintFromCurrentWrite = { apply_to_project: true }) =>
      apiFetch<ProjectBlueprintFromCurrentResult>(`/api/v1/projects/${projectId}/blueprint-from-current`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["project-blueprints"] });
      qc.invalidateQueries({ queryKey: ["project-blueprints", result.blueprint.id] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "setup"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "runtime-env"] });
    },
  });
}

export function useUpdateProject(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProjectWrite) =>
      apiFetch<Project>(`/api/v1/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId] });
    },
  });
}

export function useUpdateProjectSecretBindings(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (bindings: Record<string, string | null>) =>
      apiFetch<Project>(`/api/v1/projects/${projectId}/secret-bindings`, {
        method: "PATCH",
        body: JSON.stringify({ bindings }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "setup"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "runtime-env"] });
    },
  });
}

export function useRunProjectSetup(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<ProjectSetupRun>(`/api/v1/projects/${projectId}/setup/runs`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "setup"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId] });
    },
  });
}
