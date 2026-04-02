import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface UsageLimit {
  id: string;
  scope_type: string;
  scope_value: string;
  period: string;
  limit_usd: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface UsageLimitStatus {
  id: string;
  scope_type: string;
  scope_value: string;
  period: string;
  limit_usd: number;
  current_spend: number;
  percentage: number;
  enabled: boolean;
}

export interface UsageLimitCreatePayload {
  scope_type: string;
  scope_value: string;
  period: string;
  limit_usd: number;
  enabled?: boolean;
}

export interface UsageLimitUpdatePayload {
  limit_usd?: number;
  enabled?: boolean;
}

export function useUsageLimits() {
  return useQuery({
    queryKey: ["usage-limits"],
    queryFn: () => apiFetch<UsageLimit[]>("/api/v1/admin/limits/"),
  });
}

export function useUsageLimitsStatus() {
  return useQuery({
    queryKey: ["usage-limits-status"],
    queryFn: () => apiFetch<UsageLimitStatus[]>("/api/v1/admin/limits/status"),
    refetchInterval: 60_000,
  });
}

export function useCreateUsageLimit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UsageLimitCreatePayload) =>
      apiFetch<UsageLimit>("/api/v1/admin/limits/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["usage-limits"] });
      qc.invalidateQueries({ queryKey: ["usage-limits-status"] });
    },
  });
}

export function useUpdateUsageLimit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: UsageLimitUpdatePayload & { id: string }) =>
      apiFetch<UsageLimit>(`/api/v1/admin/limits/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["usage-limits"] });
      qc.invalidateQueries({ queryKey: ["usage-limits-status"] });
    },
  });
}

export function useDeleteUsageLimit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/admin/limits/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["usage-limits"] });
      qc.invalidateQueries({ queryKey: ["usage-limits-status"] });
    },
  });
}
