import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type {
  Channel,
  Project,
  ProjectBlueprint,
  ProjectBlueprintWrite,
  ProjectFromBlueprintWrite,
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
    },
  });
}
