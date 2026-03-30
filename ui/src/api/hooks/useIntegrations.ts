import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface IntegrationEnvVar {
  key: string;
  required: boolean;
  description: string;
  is_set: boolean;
}

export interface IntegrationWebhook {
  path: string;
  url: string;
  description: string;
}

export interface IntegrationItem {
  id: string;
  name: string;
  source: "integration" | "package" | "external";
  has_router: boolean;
  has_dispatcher: boolean;
  has_hooks: boolean;
  has_tools: boolean;
  has_skills: boolean;
  env_vars: IntegrationEnvVar[];
  webhook: IntegrationWebhook | null;
  status: "ready" | "partial" | "not_configured";
  readme: string | null;
}

export interface IntegrationSettingItem {
  key: string;
  description: string;
  required: boolean;
  secret: boolean;
  value: string;
  source: "db" | "env" | "default";
  is_set: boolean;
}

export function useIntegrations() {
  return useQuery({
    queryKey: ["admin-integrations"],
    queryFn: () =>
      apiFetch<{ integrations: IntegrationItem[] }>(
        "/api/v1/admin/integrations"
      ),
  });
}

export function useIntegrationSettings(id: string) {
  return useQuery({
    queryKey: ["admin-integration-settings", id],
    queryFn: () =>
      apiFetch<{ settings: IntegrationSettingItem[] }>(
        `/api/v1/admin/integrations/${id}/settings`
      ),
    enabled: !!id,
  });
}

export function useUpdateIntegrationSettings(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: Record<string, string>) =>
      apiFetch(`/api/v1/admin/integrations/${id}/settings`, {
        method: "PUT",
        body: JSON.stringify({ settings }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integration-settings", id] });
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}

export function useDeleteIntegrationSetting(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      apiFetch(`/api/v1/admin/integrations/${id}/settings/${key}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integration-settings", id] });
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}
