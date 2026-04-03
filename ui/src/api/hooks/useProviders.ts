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
  billing_type: string;
  plan_cost?: number | null;
  plan_period?: string | null;
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
  management_key?: string;
  billing_type?: string;
  plan_cost?: number | null;
  plan_period?: string | null;
}

export interface ProviderUpdatePayload {
  provider_type?: string;
  display_name?: string;
  api_key?: string;
  base_url?: string;
  is_enabled?: boolean;
  tpm_limit?: number | null;
  rpm_limit?: number | null;
  management_key?: string;
  clear_tpm_limit?: boolean;
  clear_rpm_limit?: boolean;
  billing_type?: string;
  plan_cost?: number | null;
  plan_period?: string | null;
  clear_plan_cost?: boolean;
}

export interface TestResult {
  ok: boolean;
  message: string;
}

export interface ProviderListResponse {
  providers: ProviderItem[];
  env_fallback_base_url?: string | null;
  env_fallback_has_key: boolean;
}

export function useProviders(enabled = true) {
  return useQuery({
    queryKey: ["admin-providers"],
    queryFn: () => apiFetch<ProviderListResponse>("/api/v1/admin/providers"),
    enabled,
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

export interface TestInlinePayload {
  provider_type: string;
  api_key?: string;
  base_url?: string;
}

export function useTestProviderInline() {
  return useMutation({
    mutationFn: (data: TestInlinePayload) =>
      apiFetch<TestResult>("/api/v1/admin/providers/test-inline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
  });
}

// ---------------------------------------------------------------------------
// Provider Models (DB-backed model lists)
// ---------------------------------------------------------------------------

export interface ProviderModelItem {
  id: number;
  provider_id: string;
  model_id: string;
  display_name?: string | null;
  max_tokens?: number | null;
  input_cost_per_1m?: string | null;
  output_cost_per_1m?: string | null;
  no_system_messages?: boolean;
  supports_tools?: boolean;
  created_at: string;
}

export interface ProviderModelCreatePayload {
  model_id: string;
  display_name?: string;
  max_tokens?: number | null;
  input_cost_per_1m?: string;
  output_cost_per_1m?: string;
  no_system_messages?: boolean;
  supports_tools?: boolean;
}

export function useProviderModels(providerId: string | undefined) {
  return useQuery({
    queryKey: ["admin-provider-models", providerId],
    queryFn: () =>
      apiFetch<ProviderModelItem[]>(
        `/api/v1/admin/providers/${providerId}/models`
      ),
    enabled: !!providerId && providerId !== "new",
  });
}

export function useAddProviderModel(providerId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProviderModelCreatePayload) =>
      apiFetch<ProviderModelItem>(
        `/api/v1/admin/providers/${providerId}/models`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-provider-models", providerId] });
      qc.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useDeleteProviderModel(providerId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (modelPk: number) =>
      apiFetch(
        `/api/v1/admin/providers/${providerId}/models/${modelPk}`,
        { method: "DELETE" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-provider-models", providerId] });
      qc.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Provider Capabilities
// ---------------------------------------------------------------------------

export interface ProviderCapabilities {
  list_models: boolean;
  pull_model: boolean;
  delete_model: boolean;
  model_info: boolean;
  running_models: boolean;
  pricing: boolean;
  requires_base_url: boolean;
  requires_api_key: boolean;
  management_key: boolean;
}

export function useProviderTypeCapabilities(providerType: string | undefined) {
  return useQuery({
    queryKey: ["provider-type-capabilities", providerType],
    queryFn: () =>
      apiFetch<ProviderCapabilities>(
        `/api/v1/admin/provider-types/${providerType}/capabilities`
      ),
    enabled: !!providerType,
  });
}

export function useProviderCapabilities(providerId: string | undefined) {
  return useQuery({
    queryKey: ["provider-capabilities", providerId],
    queryFn: () =>
      apiFetch<ProviderCapabilities>(
        `/api/v1/admin/providers/${providerId}/capabilities`
      ),
    enabled: !!providerId && providerId !== "new",
  });
}

// ---------------------------------------------------------------------------
// Model sync, pull, delete, running, info
// ---------------------------------------------------------------------------

export interface SyncModelsResult {
  created: number;
  updated: number;
  total: number;
}

export function useSyncProviderModels(providerId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SyncModelsResult>(
        `/api/v1/admin/providers/${providerId}/sync-models`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-provider-models", providerId] });
      qc.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function usePullModel(providerId: string | undefined) {
  return useMutation({
    mutationFn: (modelName: string) =>
      apiFetch(
        `/api/v1/admin/providers/${providerId}/pull-model`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_name: modelName }),
        }
      ),
  });
}

export function useDeleteRemoteModel(providerId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (modelName: string) =>
      apiFetch(
        `/api/v1/admin/providers/${providerId}/remote-models/${encodeURIComponent(modelName)}`,
        { method: "DELETE" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-provider-models", providerId] });
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["running-models", providerId] });
    },
  });
}

export interface RunningModel {
  name: string;
  model: string;
  size: number;
  size_vram: number;
  digest: string;
  expires_at: string;
  details: Record<string, any>;
}

export function useRunningModels(providerId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["running-models", providerId],
    queryFn: () =>
      apiFetch<RunningModel[]>(
        `/api/v1/admin/providers/${providerId}/running-models`
      ),
    enabled: !!providerId && providerId !== "new" && enabled,
    refetchInterval: 10_000,
  });
}

export function useRemoteModelInfo(
  providerId: string | undefined,
  modelName: string | undefined
) {
  return useQuery({
    queryKey: ["remote-model-info", providerId, modelName],
    queryFn: () =>
      apiFetch<Record<string, any>>(
        `/api/v1/admin/providers/${providerId}/remote-models/${encodeURIComponent(modelName!)}/info`
      ),
    enabled: !!providerId && providerId !== "new" && !!modelName,
  });
}
