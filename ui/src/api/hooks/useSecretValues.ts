import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SecretValueItem {
  id: string;
  name: string;
  description: string;
  has_value: boolean;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SecretValueCreatePayload {
  name: string;
  value: string;
  description?: string;
}

export interface SecretValueUpdatePayload {
  name?: string;
  value?: string;
  description?: string;
}

export function useSecretValues() {
  return useQuery({
    queryKey: ["admin-secret-values"],
    queryFn: () => apiFetch<SecretValueItem[]>("/api/v1/admin/secret-values"),
  });
}

export function useCreateSecretValue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: SecretValueCreatePayload) =>
      apiFetch<SecretValueItem>("/api/v1/admin/secret-values", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-secret-values"] });
    },
  });
}

export function useUpdateSecretValue(secretId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: SecretValueUpdatePayload) =>
      apiFetch<SecretValueItem>(`/api/v1/admin/secret-values/${secretId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-secret-values"] });
    },
  });
}

export function useDeleteSecretValue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (secretId: string) =>
      apiFetch(`/api/v1/admin/secret-values/${secretId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-secret-values"] });
    },
  });
}
