import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { StorageBreakdown, PurgeResult } from "@/src/types/api";

export function useStorageBreakdown() {
  return useQuery<StorageBreakdown>({
    queryKey: ["storage", "breakdown"],
    queryFn: () => apiFetch("/api/v1/admin/storage/breakdown"),
  });
}

export function usePurgeStorage() {
  const qc = useQueryClient();
  return useMutation<PurgeResult>({
    mutationFn: () => apiFetch("/api/v1/admin/storage/purge", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["storage"] });
    },
  });
}
