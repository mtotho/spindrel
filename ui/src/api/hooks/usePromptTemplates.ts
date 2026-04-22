import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { PromptTemplate } from "../../types/api";

export function usePromptTemplates(workspaceId?: string, category?: string, enabled = true) {
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  if (category) params.set("category", category);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return useQuery({
    queryKey: ["prompt-templates", workspaceId ?? "all", category ?? "all"],
    queryFn: () => apiFetch<PromptTemplate[]>(`/api/v1/prompt-templates${qs}`),
    enabled,
  });
}

export function usePromptTemplate(id: string | undefined) {
  return useQuery({
    queryKey: ["prompt-template", id],
    queryFn: () => apiFetch<PromptTemplate>(`/api/v1/prompt-templates/${id}`),
    enabled: !!id && id !== "new",
  });
}

export function useCreatePromptTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      content?: string;
      description?: string;
      category?: string;
      tags?: string[];
      workspace_id?: string;
      source_type?: string;
      source_path?: string;
    }) =>
      apiFetch<PromptTemplate>("/api/v1/prompt-templates", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prompt-templates"] });
    },
  });
}

export function useUpdatePromptTemplate(id: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name?: string;
      content?: string;
      description?: string;
      category?: string;
      tags?: string[];
      workspace_id?: string | null;
      source_type?: string;
      source_path?: string;
    }) =>
      apiFetch<PromptTemplate>(`/api/v1/prompt-templates/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prompt-templates"] });
      qc.invalidateQueries({ queryKey: ["prompt-template", id] });
    },
  });
}

export function useDeletePromptTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/prompt-templates/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prompt-templates"] });
    },
  });
}
