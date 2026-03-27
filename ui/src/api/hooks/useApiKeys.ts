import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiKeyCreatePayload {
  name: string;
  scopes: string[];
  expires_at?: string | null;
  store_key_value?: boolean;
}

export interface ApiKeyCreateResponse {
  key: ApiKeyItem;
  full_key: string;
}

export interface ApiKeyUpdatePayload {
  name?: string;
  scopes?: string[];
  is_active?: boolean;
  expires_at?: string | null;
}

export interface ScopeGroupsResponse {
  groups: Record<string, string[]>;
  all_scopes: string[];
}

export function useApiKeys() {
  return useQuery({
    queryKey: ["admin-api-keys"],
    queryFn: () => apiFetch<ApiKeyItem[]>("/api/v1/admin/api-keys"),
  });
}

export function useApiKey(keyId: string | undefined) {
  return useQuery({
    queryKey: ["admin-api-key", keyId],
    queryFn: () => apiFetch<ApiKeyItem>(`/api/v1/admin/api-keys/${keyId}`),
    enabled: !!keyId && keyId !== "new",
  });
}

export function useApiKeyScopes() {
  return useQuery({
    queryKey: ["admin-api-key-scopes"],
    queryFn: () => apiFetch<ScopeGroupsResponse>("/api/v1/admin/api-keys/scopes"),
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ApiKeyCreatePayload) =>
      apiFetch<ApiKeyCreateResponse>("/api/v1/admin/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-api-keys"] });
    },
  });
}

export function useUpdateApiKey(keyId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ApiKeyUpdatePayload) =>
      apiFetch<ApiKeyItem>(`/api/v1/admin/api-keys/${keyId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-api-keys"] });
      qc.invalidateQueries({ queryKey: ["admin-api-key", keyId] });
    },
  });
}

export function useDeleteApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      apiFetch(`/api/v1/admin/api-keys/${keyId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-api-keys"] });
    },
  });
}
