import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

// ---------------------------------------------------------------------------
// Update check
// ---------------------------------------------------------------------------

export interface UpdateCheckResult {
  current: string;
  git_hash: string | null;
  latest: string | null;
  latest_url: string | null;
  published_at: string | null;
  update_available: boolean;
  error?: string;
}

export function useCheckUpdate() {
  return useQuery({
    queryKey: ["version-check-update"],
    queryFn: () =>
      apiFetch<UpdateCheckResult>("/api/v1/admin/version/check-update"),
    enabled: false, // on-demand only
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Restart server
// ---------------------------------------------------------------------------

export function useRestartServer() {
  return useMutation({
    mutationFn: () =>
      apiFetch("/api/v1/admin/operations/restart", {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      }),
  });
}

// ---------------------------------------------------------------------------
// Toggle pause
// ---------------------------------------------------------------------------

export function useTogglePause() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (paused: boolean) =>
      apiFetch("/api/v1/admin/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: { SYSTEM_PAUSED: paused } }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system-status"] });
      qc.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });
}
