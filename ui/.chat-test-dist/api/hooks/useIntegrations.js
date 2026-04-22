import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
// ---------------------------------------------------------------------------
// Docs page hook (generic — serves markdown from docs/ directory)
// ---------------------------------------------------------------------------
export function useDocsPage(path) {
    return useQuery({
        queryKey: ["admin-docs", path],
        queryFn: () => apiFetch(`/api/v1/admin/docs?path=${encodeURIComponent(path)}`),
        staleTime: 5 * 60 * 1000,
    });
}
export function useIntegrations(enabled = true) {
    return useQuery({
        queryKey: ["admin-integrations"],
        queryFn: () => apiFetch("/api/v1/admin/integrations"),
        enabled,
    });
}
export function useIntegrationSettings(id) {
    return useQuery({
        queryKey: ["admin-integration-settings", id],
        queryFn: () => apiFetch(`/api/v1/admin/integrations/${id}/settings`),
        enabled: !!id,
    });
}
export function useUpdateIntegrationSettings(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (settings) => apiFetch(`/api/v1/admin/integrations/${id}/settings`, {
            method: "PUT",
            body: JSON.stringify({ settings }),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-integration-settings", id] });
            qc.invalidateQueries({ queryKey: ["admin-integrations"] });
        },
    });
}
export function useDeleteIntegrationSetting(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (key) => apiFetch(`/api/v1/admin/integrations/${id}/settings/${key}`, {
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
export function useInstallDeps(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/integrations/${id}/install-deps`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-integrations"] });
        },
    });
}
export function useInstallNpmDeps(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/integrations/${id}/install-npm-deps`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-integrations"] });
        },
    });
}
export function useInstallSystemDep(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (aptPackage) => apiFetch(`/api/v1/admin/integrations/${id}/install-system-deps`, { method: "POST", body: JSON.stringify({ apt_package: aptPackage }) }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-integrations"] });
        },
    });
}
export function useOAuthStatus(id, statusEndpoint) {
    return useQuery({
        queryKey: ["admin-integration-oauth-status", id],
        queryFn: () => apiFetch(statusEndpoint),
        enabled: !!statusEndpoint,
        staleTime: 30_000,
    });
}
export function useOAuthDisconnect(id, disconnectEndpoint) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => {
            if (!disconnectEndpoint)
                return Promise.reject(new Error("No disconnect endpoint"));
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
export function useStartProcess(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/integrations/${id}/process/start`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-integration-process", id] });
            qc.invalidateQueries({ queryKey: ["admin-integrations"] });
        },
    });
}
export function useStopProcess(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/integrations/${id}/process/stop`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-integration-process", id] });
            qc.invalidateQueries({ queryKey: ["admin-integrations"] });
        },
    });
}
export function useRestartProcess(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/integrations/${id}/process/restart`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-integration-process", id] });
            qc.invalidateQueries({ queryKey: ["admin-integrations"] });
        },
    });
}
export function useAutoStart(id, enabled) {
    return useQuery({
        queryKey: ["admin-integration-autostart", id],
        queryFn: () => apiFetch(`/api/v1/admin/integrations/${id}/process/auto-start`),
        enabled,
    });
}
export function useSetAutoStart(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (autoStart) => apiFetch(`/api/v1/admin/integrations/${id}/process/auto-start`, {
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
        queryFn: () => apiFetch("/api/v1/admin/integrations/icons"),
        staleTime: 600_000, // 10 min — icons rarely change
    });
}
export function useSidebarSections(enabled = true) {
    return useQuery({
        queryKey: ["admin-sidebar-sections"],
        queryFn: () => apiFetch("/api/v1/admin/integrations/sidebar-sections"),
        enabled,
        staleTime: 300_000, // 5 min — sidebar sections rarely change
    });
}
export function useIntegrationApiKey(id, enabled) {
    return useQuery({
        queryKey: ["admin-integration-api-key", id],
        queryFn: () => apiFetch(`/api/v1/admin/integrations/${id}/api-key`),
        enabled,
    });
}
export function useProvisionIntegrationApiKey(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/integrations/${id}/api-key`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({
                queryKey: ["admin-integration-api-key", id],
            });
        },
    });
}
export function useRevokeIntegrationApiKey(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/integrations/${id}/api-key`, {
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
export function useIntegrationTasks(id, opts) {
    const params = new URLSearchParams();
    if (opts?.status)
        params.set("status", opts.status);
    if (opts?.limit)
        params.set("limit", String(opts.limit));
    const qs = params.toString();
    return useQuery({
        queryKey: ["admin-integration-tasks", id, opts?.status, opts?.limit],
        queryFn: () => apiFetch(`/api/v1/admin/integrations/${id}/tasks${qs ? `?${qs}` : ""}`),
        enabled: !!id,
        refetchInterval: 15_000,
    });
}
export function useCancelIntegrationTasks(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/integrations/${id}/cancel-pending-tasks`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({
                queryKey: ["admin-integration-tasks", id],
            });
        },
    });
}
export function useProcessLogs(id) {
    return useQuery({
        queryKey: ["admin-integration-process-logs", id],
        queryFn: () => apiFetch(`/api/v1/admin/integrations/${id}/process/logs`),
        enabled: !!id,
        refetchInterval: 5_000,
    });
}
export function useDeviceStatus(id) {
    return useQuery({
        queryKey: ["admin-integration-device-status", id],
        queryFn: () => apiFetch(`/api/v1/admin/integrations/${id}/device-status`),
        enabled: !!id,
        refetchInterval: 10_000,
    });
}
export function useSetIntegrationStatus(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (status) => apiFetch(`/api/v1/admin/integrations/${id}/status`, {
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
export function useIntegrationDebugAction(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (action) => {
            const url = `/integrations/${id}/${action.endpoint}`;
            if (action.method === "GET") {
                return apiFetch(url);
            }
            return apiFetch(url, {
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
export function useIntegrationManifest(id) {
    return useQuery({
        queryKey: ["admin-integration-manifest", id],
        queryFn: () => apiFetch(`/api/v1/admin/integrations/${id}/manifest`),
        enabled: !!id,
    });
}
export function useIntegrationYaml(id) {
    return useQuery({
        queryKey: ["admin-integration-yaml", id],
        queryFn: () => apiFetch(`/api/v1/admin/integrations/${id}/yaml`),
        enabled: !!id,
    });
}
export function useUpdateIntegrationYaml(id) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (yaml) => apiFetch(`/api/v1/admin/integrations/${id}/yaml`, {
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
