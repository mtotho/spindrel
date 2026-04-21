import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface InstallCacheStats {
  home_path: string;
  home_bytes: number;
  home_exists: boolean;
  apt_path: string;
  apt_bytes: number;
  apt_exists: boolean;
}

export interface ClearInstallCacheResult {
  cleared: string[];
  freed_bytes: number;
  errors: string[];
}

export type InstallCacheTarget = "home" | "apt" | "all";

export function useInstallCacheStats() {
  return useQuery({
    queryKey: ["admin-install-cache"],
    queryFn: () => apiFetch<InstallCacheStats>("/api/v1/admin/install-cache"),
    staleTime: 30_000,
  });
}

export function useClearInstallCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target: InstallCacheTarget = "all") =>
      apiFetch<ClearInstallCacheResult>("/api/v1/admin/install-cache/clear", {
        method: "POST",
        body: JSON.stringify({ target }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-install-cache"] });
    },
  });
}
