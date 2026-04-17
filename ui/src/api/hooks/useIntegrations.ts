import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface IntegrationEnvVar {
  key: string;
  required: boolean;
  description: string;
  is_set: boolean;
  default?: string | null;
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

export interface NpmDependency {
  package: string;
  binary_name: string;
  installed: boolean;
}

export interface SystemDependency {
  binary: string;
  apt_package: string;
  install_hint: string;
  installed: boolean;
}

export interface OAuthConfig {
  auth_start: string;
  status: string;
  disconnect: string;
  scope_services: string[];
}

export interface DebugAction {
  id: string;
  label: string;
  description?: string;
  endpoint: string;
  method: "GET" | "POST" | "PUT" | "DELETE";
  style?: "default" | "warning" | "danger";
}

export interface IntegrationItem {
  id: string;
  name: string;
  source: "integration" | "package" | "external";
  has_router: boolean;
  has_dispatcher: boolean;
  has_renderer: boolean;
  has_hooks: boolean;
  has_tools: boolean;
  has_skills: boolean;
  has_carapaces: boolean;
  tool_names?: string[];
  tool_files?: string[];
  skill_files?: string[];
  carapace_files?: string[];
  has_tool_widgets: boolean;
  tool_widget_names?: string[];
  has_process: boolean;
  process_launchable?: boolean;
  process_description?: string | null;
  process_status: ProcessStatus | null;
  env_vars: IntegrationEnvVar[];
  python_dependencies?: PythonDependency[];
  deps_installed?: boolean;
  npm_dependencies?: NpmDependency[];
  npm_deps_installed?: boolean;
  system_dependencies?: SystemDependency[];
  system_deps_installed?: boolean;
  oauth?: OAuthConfig;
  webhook: IntegrationWebhook | null;
  api_permissions: string | string[] | null;
  icon?: string;
  lifecycle_status: "available" | "enabled";
  status: "ready" | "partial" | "not_configured";
  readme: string | null;
  debug_actions?: DebugAction[];
  events?: { type: string; label: string; description?: string; category?: string }[];
}

export interface IntegrationTaskItem {
  id: string;
  status: string;
  prompt: string;
  title: string | null;
  created_at: string | null;
  completed_at: string | null;
  error: string | null;
  bot_id: string;
  task_type: string;
}

export interface IntegrationSettingItem {
  key: string;
  description: string;
  required: boolean;
  secret: boolean;
  value: string;
  source: "db" | "env" | "default";
  is_set: boolean;
  default?: string | null;
  type?: string;
}

// ---------------------------------------------------------------------------
// Docs page hook (generic — serves markdown from docs/ directory)
// ---------------------------------------------------------------------------

export function useDocsPage(path: string) {
  return useQuery({
    queryKey: ["admin-docs", path],
    queryFn: () =>
      apiFetch<{ content: string; path: string }>(
        `/api/v1/admin/docs?path=${encodeURIComponent(path)}`
      ),
    staleTime: 5 * 60 * 1000,
  });
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

export function useInstallNpmDeps(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ installed: boolean; message: string }>(
        `/api/v1/admin/integrations/${id}/install-npm-deps`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}

export function useInstallSystemDep(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (aptPackage: string) =>
      apiFetch<{ installed: boolean; message: string }>(
        `/api/v1/admin/integrations/${id}/install-system-deps`,
        { method: "POST", body: JSON.stringify({ apt_package: aptPackage }) }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}

// ---------------------------------------------------------------------------
// OAuth status hooks
// ---------------------------------------------------------------------------

export interface OAuthStatus {
  connected: boolean;
  scopes: string[];
  email: string | null;
}

export function useOAuthStatus(id: string, statusEndpoint: string | undefined) {
  return useQuery({
    queryKey: ["admin-integration-oauth-status", id],
    queryFn: () => apiFetch<OAuthStatus>(statusEndpoint!),
    enabled: !!statusEndpoint,
    staleTime: 30_000,
  });
}

export function useOAuthDisconnect(id: string, disconnectEndpoint: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => {
      if (!disconnectEndpoint) return Promise.reject(new Error("No disconnect endpoint"));
      return apiFetch(disconnectEndpoint, { method: "POST" });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integration-oauth-status", id] });
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

// ---------------------------------------------------------------------------
// Integration icons (lightweight id -> lucide icon name mapping)
// ---------------------------------------------------------------------------

export function useIntegrationIcons() {
  return useQuery({
    queryKey: ["integration-icons"],
    queryFn: () =>
      apiFetch<{ icons: Record<string, string> }>(
        "/api/v1/admin/integrations/icons"
      ),
    staleTime: 600_000, // 10 min — icons rarely change
  });
}

// ---------------------------------------------------------------------------
// Sidebar sections declared by integrations
// ---------------------------------------------------------------------------

export interface SidebarSectionItem {
  label: string;
  href: string;
  icon: string;
}

export interface SidebarSection {
  integration_id: string;
  id: string;
  title: string;
  icon: string;
  items: SidebarSectionItem[];
  readiness_endpoint: string | null;
  readiness_field: string | null;
}

export function useSidebarSections() {
  return useQuery({
    queryKey: ["admin-sidebar-sections"],
    queryFn: () =>
      apiFetch<{ sections: SidebarSection[] }>(
        "/api/v1/admin/integrations/sidebar-sections"
      ),
    staleTime: 300_000, // 5 min — sidebar sections rarely change
  });
}

// ---------------------------------------------------------------------------
// Integration API key hooks
// ---------------------------------------------------------------------------

export interface IntegrationApiKeyInfo {
  provisioned: boolean;
  key_prefix?: string;
  scopes?: string[];
  created_at?: string | null;
  last_used_at?: string | null;
}

export interface IntegrationApiKeyProvisionResult {
  key_prefix: string;
  key_value: string | null;
  scopes: string[];
  created_at: string | null;
}

export function useIntegrationApiKey(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["admin-integration-api-key", id],
    queryFn: () =>
      apiFetch<IntegrationApiKeyInfo>(
        `/api/v1/admin/integrations/${id}/api-key`
      ),
    enabled,
  });
}

export function useProvisionIntegrationApiKey(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<IntegrationApiKeyProvisionResult>(
        `/api/v1/admin/integrations/${id}/api-key`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["admin-integration-api-key", id],
      });
    },
  });
}

export function useRevokeIntegrationApiKey(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch(`/api/v1/admin/integrations/${id}/api-key`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["admin-integration-api-key", id],
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Integration task feed & bulk cancel
// ---------------------------------------------------------------------------

export function useIntegrationTasks(
  id: string,
  opts?: { status?: string; limit?: number }
) {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return useQuery({
    queryKey: ["admin-integration-tasks", id, opts?.status, opts?.limit],
    queryFn: () =>
      apiFetch<{
        tasks: IntegrationTaskItem[];
        stats: Record<string, number>;
      }>(`/api/v1/admin/integrations/${id}/tasks${qs ? `?${qs}` : ""}`),
    enabled: !!id,
    refetchInterval: 15_000,
  });
}

export function useCancelIntegrationTasks(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ cancelled: number }>(
        `/api/v1/admin/integrations/${id}/cancel-pending-tasks`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["admin-integration-tasks", id],
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Process logs (ring buffer)
// ---------------------------------------------------------------------------

export interface ProcessLogLine {
  ts: string;
  text: string;
  index: number;
}

export function useProcessLogs(id: string) {
  return useQuery({
    queryKey: ["admin-integration-process-logs", id],
    queryFn: () =>
      apiFetch<{ lines: ProcessLogLine[]; total: number }>(
        `/api/v1/admin/integrations/${id}/process/logs`
      ),
    enabled: !!id,
    refetchInterval: 5_000,
  });
}

// ---------------------------------------------------------------------------
// Device / connection status
// ---------------------------------------------------------------------------

export interface DeviceStatusInfo {
  device_id: string;
  label: string;
  protocol: string;
  uri: string;
  status: "connected" | "disconnected" | "connecting" | "error";
  detail: string | null;
  last_activity: string | null;
  metadata: Record<string, unknown>;
}

export interface DeviceStatusResponse {
  devices: DeviceStatusInfo[];
  updated_at: string | null;
  stale: boolean;
}

export function useDeviceStatus(id: string) {
  return useQuery({
    queryKey: ["admin-integration-device-status", id],
    queryFn: () =>
      apiFetch<DeviceStatusResponse>(
        `/api/v1/admin/integrations/${id}/device-status`
      ),
    enabled: !!id,
    refetchInterval: 10_000,
  });
}

// ---------------------------------------------------------------------------
// Integration lifecycle status
// ---------------------------------------------------------------------------

export type IntegrationLifecycleStatus = "available" | "needs_setup" | "enabled";

export function useSetIntegrationStatus(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (status: IntegrationLifecycleStatus) =>
      apiFetch(`/api/v1/admin/integrations/${id}/status`, {
        method: "PUT",
        body: JSON.stringify({ status }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
      qc.invalidateQueries({ queryKey: ["admin-sidebar-sections"] });
      qc.invalidateQueries({ queryKey: ["admin-integration-process", id] });
      qc.invalidateQueries({ queryKey: ["admin-integration-autostart", id] });
    },
  });
}

export function useIntegrationDebugAction(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (action: {
      endpoint: string;
      method: string;
    }): Promise<Record<string, unknown>> => {
      const url = `/integrations/${id}/${action.endpoint}`;
      if (action.method === "GET") {
        return apiFetch<Record<string, unknown>>(url);
      }
      return apiFetch<Record<string, unknown>>(url, {
        method: action.method,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["admin-integration-tasks", id],
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Integration manifest / YAML hooks
// ---------------------------------------------------------------------------

export function useIntegrationManifest(id: string) {
  return useQuery({
    queryKey: ["admin-integration-manifest", id],
    queryFn: () =>
      apiFetch<{ manifest: Record<string, unknown> }>(
        `/api/v1/admin/integrations/${id}/manifest`
      ),
    enabled: !!id,
  });
}

export function useIntegrationYaml(id: string) {
  return useQuery({
    queryKey: ["admin-integration-yaml", id],
    queryFn: () =>
      apiFetch<{ yaml: string; source: string }>(
        `/api/v1/admin/integrations/${id}/yaml`
      ),
    enabled: !!id,
  });
}

export function useUpdateIntegrationYaml(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (yaml: string) =>
      apiFetch(`/api/v1/admin/integrations/${id}/yaml`, {
        method: "PUT",
        body: JSON.stringify({ yaml }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integration-yaml", id] });
      qc.invalidateQueries({ queryKey: ["admin-integration-manifest", id] });
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
    },
  });
}
