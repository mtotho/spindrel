import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { SpikeConfig, SpikeStatus, SpikeAlertList, AvailableTargetsResponse } from "../../types/api";

export function useSpikeConfig() {
  return useQuery({
    queryKey: ["spike-config"],
    queryFn: () => apiFetch<SpikeConfig>("/api/v1/admin/spike-alerts/config"),
  });
}

export function useUpdateSpikeConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<SpikeConfig>) =>
      apiFetch<SpikeConfig>("/api/v1/admin/spike-alerts/config", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["spike-config"] });
      qc.invalidateQueries({ queryKey: ["spike-status"] });
    },
  });
}

export function useSpikeStatus() {
  return useQuery({
    queryKey: ["spike-status"],
    queryFn: () => apiFetch<SpikeStatus>("/api/v1/admin/spike-alerts/status"),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useSpikeAlertHistory(page: number = 1, pageSize: number = 20) {
  return useQuery({
    queryKey: ["spike-alert-history", page, pageSize],
    queryFn: () =>
      apiFetch<SpikeAlertList>(
        `/api/v1/admin/spike-alerts/history?page=${page}&page_size=${pageSize}`,
      ),
  });
}

export function useTestSpikeAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; alert_id?: string; targets_attempted?: number; targets_succeeded?: number }>(
        "/api/v1/admin/spike-alerts/test",
        { method: "POST" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["spike-alert-history"] });
      qc.invalidateQueries({ queryKey: ["spike-config"] });
    },
  });
}

export function useAvailableTargets() {
  return useQuery({
    queryKey: ["spike-available-targets"],
    queryFn: () => apiFetch<AvailableTargetsResponse>("/api/v1/admin/spike-alerts/targets/available"),
  });
}
