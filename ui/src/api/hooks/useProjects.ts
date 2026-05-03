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
  ProjectGitStatus,
  ProjectInstance,
  ProjectRunReceipt,
  ProjectRuntimeEnv,
  ProjectDependencyStackState,
  ProjectSetup,
  ProjectSetupRun,
  ProjectWrite,
} from "../../types/api";
import type { MachineTargetGrant } from "./useTasks";

export interface ProjectRunLoopPolicyInput {
  enabled: boolean;
  max_iterations?: number;
  stop_condition?: string;
  continuation_prompt?: string;
}

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

export function useProjectGitStatus(
  projectId: string | undefined,
  opts: { repoPath?: string | null; includePatch?: boolean; refetchIntervalMs?: number } = {},
) {
  const params = new URLSearchParams();
  if (opts.repoPath) params.set("repo_path", opts.repoPath);
  if (opts.includePatch) params.set("include_patch", "true");
  const query = params.toString();
  return useQuery({
    queryKey: ["projects", projectId, "git-status", opts.repoPath ?? null, !!opts.includePatch],
    queryFn: () => apiFetch<ProjectGitStatus>(`/api/v1/projects/${projectId}/git-status${query ? `?${query}` : ""}`),
    enabled: !!projectId,
    refetchInterval: opts.refetchIntervalMs ?? 15_000,
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

export interface SessionExecutionEnvironment {
  session_id: string;
  mode: string;
  status: string;
  cwd?: string | null;
  docker_status?: string | null;
  docker_endpoint?: string | null;
  project_id?: string | null;
  project_instance_id?: string | null;
  pinned?: boolean;
  expires_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, any>;
  worktree?: Record<string, any> | null;
  docker?: Record<string, any> | null;
  runtime_env?: Record<string, string>;
}

export function useSessionExecutionEnvironment(sessionId: string | undefined | null) {
  return useQuery({
    queryKey: ["session-execution-environment", sessionId],
    queryFn: () => apiFetch<SessionExecutionEnvironment>(`/api/v1/sessions/${sessionId}/execution-environment`),
    enabled: !!sessionId,
    refetchInterval: 10_000,
  });
}

export function useSessionGitStatus(
  sessionId: string | undefined | null,
  opts: { includePatch?: boolean; refetchIntervalMs?: number } = {},
) {
  const params = new URLSearchParams();
  if (opts.includePatch) params.set("include_patch", "true");
  const query = params.toString();
  return useQuery({
    queryKey: ["sessions", sessionId, "git-status", !!opts.includePatch],
    queryFn: () => apiFetch<ProjectGitStatus>(`/api/v1/sessions/${sessionId}/git-status${query ? `?${query}` : ""}`),
    enabled: !!sessionId,
    refetchInterval: opts.refetchIntervalMs ?? 15_000,
  });
}

export function useManageSessionExecutionEnvironment(sessionId: string | undefined | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { action: string; pinned?: boolean | null; ttl_seconds?: number | null }) =>
      apiFetch<Record<string, any>>(`/api/v1/sessions/${sessionId}/execution-environment/actions`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session-execution-environment", sessionId] });
      qc.invalidateQueries({ queryKey: ["recent-sessions"] });
    },
  });
}

// Generated types from openapi.json. The FastAPI models declare nested
// dict fields as `dict[str, Any]`, so the generated shapes carry
// `Record<string, unknown>` for `concurrency`, `intake`, `runs`, etc.
// Consumers narrow at point of use; do NOT redeclare the shape here.
import type { components as ApiSchemas } from "../../types/api.generated";

export type ProjectFactoryStateView = ApiSchemas["schemas"]["ProjectFactoryStateOut"];
export type ProjectOrchestrationPolicyView = ApiSchemas["schemas"]["ProjectOrchestrationPolicyOut"];

export function useProjectFactoryState(
  projectId: string | undefined,
  opts: { refetchIntervalMs?: number } = {},
) {
  return useQuery({
    queryKey: ["projects", projectId, "factory-state"],
    queryFn: () =>
      apiFetch<ProjectFactoryStateView>(`/api/v1/projects/${projectId}/factory-state`),
    enabled: !!projectId,
    refetchInterval: opts.refetchIntervalMs ?? 30_000,
  });
}

export function useProjectOrchestrationPolicy(
  projectId: string | undefined,
  opts: { refetchIntervalMs?: number } = {},
) {
  return useQuery({
    queryKey: ["projects", projectId, "orchestration-policy"],
    queryFn: () =>
      apiFetch<ProjectOrchestrationPolicyView>(
        `/api/v1/projects/${projectId}/orchestration-policy`,
      ),
    enabled: !!projectId,
    refetchInterval: opts.refetchIntervalMs ?? 30_000,
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

export function useProjectCodingRuns(projectId: string | undefined, opts: { limit?: number } = {}) {
  const limit = opts.limit ?? 25;
  return useQuery({
    queryKey: ["projects", projectId, "coding-runs", limit],
    queryFn: () => apiFetch<ProjectCodingRun[]>(`/api/v1/projects/${projectId}/coding-runs?limit=${limit}`),
    enabled: !!projectId,
    refetchInterval: 10_000,
  });
}

export function useProjectCodingRun(projectId: string | undefined, taskId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "coding-runs", taskId],
    queryFn: () => apiFetch<ProjectCodingRun>(`/api/v1/projects/${projectId}/coding-runs/${taskId}`),
    enabled: !!projectId && !!taskId,
  });
}

export function useProjectCodingRunGitStatus(
  projectId: string | undefined,
  taskId: string | undefined,
  opts: { includePatch?: boolean; refetchIntervalMs?: number } = {},
) {
  const params = new URLSearchParams();
  if (opts.includePatch) params.set("include_patch", "true");
  const query = params.toString();
  return useQuery({
    queryKey: ["projects", projectId, "coding-runs", taskId, "git-status", !!opts.includePatch],
    queryFn: () =>
      apiFetch<ProjectGitStatus>(
        `/api/v1/projects/${projectId}/coding-runs/${taskId}/git-status${query ? `?${query}` : ""}`,
      ),
    enabled: !!projectId && !!taskId,
    refetchInterval: opts.refetchIntervalMs ?? 15_000,
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
    mutationFn: (data: { channel_id: string; title?: string; request?: string; scheduled_at?: string | null; recurrence?: string; repo_path?: string | null; work_surface_mode?: string; machine_target_grant?: MachineTargetGrant | null; loop_policy?: ProjectRunLoopPolicyInput | null }) =>
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
      repo_path?: string | null;
      work_surface_mode?: string;
      enabled?: boolean;
      machine_target_grant?: MachineTargetGrant | null;
      loop_policy?: ProjectRunLoopPolicyInput | null;
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
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-run-schedules"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["recent-sessions"] });
      if (run.task?.channel_id) {
        qc.invalidateQueries({ queryKey: ["channel-session-catalog", run.task.channel_id] });
      }
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
    mutationFn: (data: { channel_id: string; request?: string; repo_path?: string | null; work_surface_mode?: string; machine_target_grant?: MachineTargetGrant | null; source_artifact?: { path: string; section?: string | null; commit_sha?: string | null } | null; loop_policy?: ProjectRunLoopPolicyInput | null }) =>
      apiFetch<ProjectCodingRun>(`/api/v1/projects/${projectId}/coding-runs`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-batches"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs", "review-sessions"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
      qc.invalidateQueries({ queryKey: ["projects", "review-inbox"] });
      qc.invalidateQueries({ queryKey: ["recent-sessions"] });
      if (run.task?.channel_id) {
        qc.invalidateQueries({ queryKey: ["channel-session-catalog", run.task.channel_id] });
      }
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

function useProjectCodingRunAction(projectId: string | undefined, action: "refresh" | "reviewed" | "cleanup" | "loop-disable" | "cancel") {
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

export function useCancelProjectCodingRun(projectId: string | undefined) {
  return useProjectCodingRunAction(projectId, "cancel");
}

export function useDisableProjectCodingRunLoop(projectId: string | undefined) {
  return useProjectCodingRunAction(projectId, "loop-disable");
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
