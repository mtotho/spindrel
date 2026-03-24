import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface ProviderItem {
  id: string;
  provider_type: string;
  display_name: string;
  base_url?: string | null;
  is_enabled: boolean;
  tpm_limit?: number | null;
  rpm_limit?: number | null;
  config: Record<string, any>;
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderCreatePayload {
  id: string;
  provider_type: string;
  display_name: string;
  api_key?: string;
  base_url?: string;
  is_enabled?: boolean;
  tpm_limit?: number | null;
  rpm_limit?: number | null;
  credentials_path?: string;
  management_key?: string;
}

export interface ProviderUpdatePayload {
  provider_type?: string;
  display_name?: string;
  api_key?: string;
  base_url?: string;
  is_enabled?: boolean;
  tpm_limit?: number | null;
  rpm_limit?: number | null;
  credentials_path?: string;
  management_key?: string;
  clear_tpm_limit?: boolean;
  clear_rpm_limit?: boolean;
}

export interface TestResult {
  ok: boolean;
  message: string;
}

export function useProviders() {
  return useQuery({
    queryKey: ["admin-providers"],
    queryFn: () => apiFetch<ProviderItem[]>("/api/v1/admin/providers"),
  });
}

export function useProvider(providerId: string | undefined) {
  return useQuery({
    queryKey: ["admin-provider", providerId],
    queryFn: () => apiFetch<ProviderItem>(`/api/v1/admin/providers/${providerId}`),
    enabled: !!providerId && providerId !== "new",
  });
}

export function useCreateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProviderCreatePayload) =>
      apiFetch<ProviderItem>("/api/v1/admin/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-providers"] });
    },
  });
}

export function useUpdateProvider(providerId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProviderUpdatePayload) =>
      apiFetch<ProviderItem>(`/api/v1/admin/providers/${providerId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-providers"] });
      qc.invalidateQueries({ queryKey: ["admin-provider", providerId] });
    },
  });
}

export function useDeleteProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (providerId: string) =>
      apiFetch(`/api/v1/admin/providers/${providerId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-providers"] });
    },
  });
}

export function useTestProvider() {
  return useMutation({
    mutationFn: (providerId: string) =>
      apiFetch<TestResult>(`/api/v1/admin/providers/${providerId}/test`, {
        method: "POST",
      }),
  });
}
