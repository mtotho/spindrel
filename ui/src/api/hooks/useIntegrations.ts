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

export interface ProcessStatus {
  integration_id: string;
  status: "running" | "stopped";
  pid: number | null;
  uptime_seconds: number | null;
  exit_code: number | null;
  restart_count: number;
}

export interface PythonDependency {
  package: string;
  installed: boolean;
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
  has_process: boolean;
  process_status: ProcessStatus | null;
  env_vars: IntegrationEnvVar[];
  python_dependencies?: PythonDependency[];
  deps_installed?: boolean;
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

// ---------------------------------------------------------------------------
// Dependency installation
// ---------------------------------------------------------------------------

export function useInstallDeps(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ installed: boolean; message: string }>(
        `/api/v1/admin/integrations/${id}/install-deps`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Process control hooks
// ---------------------------------------------------------------------------

export function useStartProcess(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<ProcessStatus>(
        `/api/v1/admin/integrations/${id}/process/start`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integration-process", id] });
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}

export function useStopProcess(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<ProcessStatus>(
        `/api/v1/admin/integrations/${id}/process/stop`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integration-process", id] });
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}

export function useRestartProcess(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<ProcessStatus>(
        `/api/v1/admin/integrations/${id}/process/restart`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integration-process", id] });
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}

export function useAutoStart(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["admin-integration-autostart", id],
    queryFn: () =>
      apiFetch<{ integration_id: string; auto_start: boolean }>(
        `/api/v1/admin/integrations/${id}/process/auto-start`
      ),
    enabled,
  });
}

export function useSetAutoStart(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (autoStart: boolean) =>
      apiFetch(`/api/v1/admin/integrations/${id}/process/auto-start`, {
        method: "PUT",
        body: JSON.stringify({ enabled: autoStart }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integration-autostart", id] });
    },
  });
}
