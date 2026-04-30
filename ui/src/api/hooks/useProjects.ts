import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type {
  Channel,
  Project,
  ProjectBlueprint,
  ProjectBlueprintWrite,
  ProjectCodingRun,
  ProjectCodingRunTask,
  ProjectFromBlueprintWrite,
  ProjectInstance,
  ProjectRunReceipt,
  ProjectRuntimeEnv,
  ProjectSetup,
  ProjectSetupRun,
  ProjectWrite,
} from "../../types/api";

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => apiFetch<Project[]>("/api/v1/projects"),
  });
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => apiFetch<Project>(`/api/v1/projects/${projectId}`),
    enabled: !!projectId,
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

export function useCreateProjectCodingRun(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { channel_id: string; request?: string }) =>
      apiFetch<ProjectCodingRun>(`/api/v1/projects/${projectId}/coding-runs`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "instances"] });
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
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
    },
  });
}

export function useCreateProjectCodingRunReviewSession(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { channel_id: string; task_ids: string[]; prompt?: string; merge_method?: "squash" | "merge" | "rebase" }) =>
      apiFetch<ProjectCodingRunTask>(`/api/v1/projects/${projectId}/coding-runs/review-sessions`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "coding-runs"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "run-receipts"] });
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

export function useProjectBlueprints() {
  return useQuery({
    queryKey: ["project-blueprints"],
    queryFn: () => apiFetch<ProjectBlueprint[]>("/api/v1/projects/blueprints"),
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
