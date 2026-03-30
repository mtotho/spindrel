import { useQuery } from "@tanstack/react-query";
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

export function useIntegrations() {
  return useQuery({
    queryKey: ["admin-integrations"],
    queryFn: () =>
      apiFetch<{ integrations: IntegrationItem[] }>(
        "/api/v1/admin/integrations"
      ),
  });
}
