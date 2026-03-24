import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { ModelGroup, CompletionItem } from "../../types/api";

export function useModelGroups() {
  return useQuery({
    queryKey: ["models"],
    queryFn: () => apiFetch<ModelGroup[]>("/api/v1/admin/models"),
    staleTime: 5 * 60 * 1000, // 5 min cache
  });
}

export function useCompletions() {
  return useQuery({
    queryKey: ["completions"],
    queryFn: () => apiFetch<CompletionItem[]>("/api/v1/admin/completions"),
    staleTime: 5 * 60 * 1000,
  });
}
