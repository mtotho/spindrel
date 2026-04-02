import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { ModelGroup, CompletionItem } from "../../types/api";

export function useModelGroups() {
  return useQuery({
    queryKey: ["models"],
    queryFn: () => apiFetch<ModelGroup[]>("/api/v1/admin/models"),
    staleTime: 5 * 60 * 1000, // 5 min cache
  });
}

export function useEmbeddingModelGroups() {
  return useQuery({
    queryKey: ["embedding-models"],
    queryFn: () => apiFetch<ModelGroup[]>("/api/v1/admin/embedding-models"),
    staleTime: 5 * 60 * 1000,
    refetchInterval: (query) => {
      const data = query.state.data;
      const hasDownloading = data?.some((g) =>
        g.models.some((m) => m.download_status === "downloading")
      );
      return hasDownloading ? 3000 : false;
    },
  });
}

export function useDownloadEmbeddingModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (modelId: string) =>
      apiFetch<{ operation_id: string; model_id: string }>(
        "/api/v1/admin/embedding-models/download",
        { method: "POST", body: JSON.stringify({ model_id: modelId }) }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["embedding-models"] });
    },
  });
}

export function useCompletions() {
  return useQuery({
    queryKey: ["completions"],
    queryFn: () => apiFetch<CompletionItem[]>("/api/v1/admin/completions"),
    staleTime: 5 * 60 * 1000,
  });
}
