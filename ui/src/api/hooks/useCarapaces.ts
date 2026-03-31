import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { Carapace } from "../../types/api";

export function useCarapaces() {
  return useQuery({
    queryKey: ["carapaces"],
    queryFn: () => apiFetch<Carapace[]>("/api/v1/admin/carapaces"),
  });
}

export function useCarapace(id?: string) {
  return useQuery({
    queryKey: ["carapaces", id],
    queryFn: () => apiFetch<Carapace>(`/api/v1/admin/carapaces/${id}`),
    enabled: !!id,
  });
}

export function useCreateCarapace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Carapace> & { id: string; name: string }) =>
      apiFetch<Carapace>("/api/v1/admin/carapaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["carapaces"] });
    },
  });
}

export function useUpdateCarapace(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Carapace>) =>
      apiFetch<Carapace>(`/api/v1/admin/carapaces/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["carapaces", id] });
      qc.invalidateQueries({ queryKey: ["carapaces"] });
    },
  });
}

export function useDeleteCarapace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/admin/carapaces/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["carapaces"] });
    },
  });
}

export interface ResolvedCarapace {
  skills: { id: string; mode: string }[];
  local_tools: string[];
  mcp_tools: string[];
  pinned_tools: string[];
  system_prompt_fragments: string[];
  resolved_ids: string[];
}

export function useResolveCarapace(id?: string) {
  return useQuery({
    queryKey: ["carapaces", id, "resolve"],
    queryFn: () => apiFetch<ResolvedCarapace>(`/api/v1/admin/carapaces/${id}/resolve`),
    enabled: !!id,
  });
}
