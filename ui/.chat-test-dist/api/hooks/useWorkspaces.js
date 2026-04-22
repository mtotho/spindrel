import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useWorkspaces(enabled = true) {
    return useQuery({
        queryKey: ["workspaces"],
        queryFn: () => apiFetch("/api/v1/workspaces"),
        enabled,
    });
}
export function useWorkspace(workspaceId) {
    return useQuery({
        queryKey: ["workspaces", workspaceId],
        queryFn: () => apiFetch(`/api/v1/workspaces/${workspaceId}`),
        enabled: !!workspaceId,
    });
}
export function useCreateWorkspace() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/workspaces", {
            method: "POST",
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspaces"] });
        },
    });
}
export function useUpdateWorkspace(workspaceId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/workspaces/${workspaceId}`, {
            method: "PUT",
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspaces"] });
            qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
            qc.invalidateQueries({ queryKey: ["workspace-indexing", workspaceId] });
            qc.invalidateQueries({ queryKey: ["workspace-index-status", workspaceId] });
        },
    });
}
export function useDeleteWorkspace() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (workspaceId) => apiFetch(`/api/v1/workspaces/${workspaceId}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspaces"] });
        },
    });
}
// Bot management
export function useUpdateWorkspaceBot(workspaceId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/workspaces/${workspaceId}/bots/${data.bot_id}`, {
            method: "PUT",
            body: JSON.stringify({ role: data.role, cwd_override: data.cwd_override, write_access: data.write_access }),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
            qc.invalidateQueries({ queryKey: ["bots"] });
        },
    });
}
// File browser
export function useWorkspaceFiles(workspaceId, path = "/") {
    return useQuery({
        queryKey: ["workspace-files", workspaceId, path],
        queryFn: () => apiFetch(`/api/v1/workspaces/${workspaceId}/files?path=${encodeURIComponent(path)}`),
        enabled: !!workspaceId,
    });
}
// File content operations
export function useWorkspaceFileContent(workspaceId, path) {
    return useQuery({
        queryKey: ["workspace-file-content", workspaceId, path],
        queryFn: () => apiFetch(`/api/v1/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(path)}`),
        enabled: !!workspaceId && !!path,
    });
}
export function useWriteWorkspaceFile(workspaceId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(data.path)}`, { method: "PUT", body: JSON.stringify({ content: data.content }) }),
        onSuccess: (_data, vars) => {
            qc.invalidateQueries({ queryKey: ["workspace-file-content", workspaceId, vars.path] });
            qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
        },
    });
}
export function useMkdirWorkspace(workspaceId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (path) => apiFetch(`/api/v1/workspaces/${workspaceId}/files/mkdir?path=${encodeURIComponent(path)}`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
        },
    });
}
export function useDeleteWorkspaceFile(workspaceId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (path) => apiFetch(`/api/v1/workspaces/${workspaceId}/files?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
            qc.invalidateQueries({ queryKey: ["workspace-file-content", workspaceId] });
        },
    });
}
export function useMoveWorkspaceFile(workspaceId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/workspaces/${workspaceId}/files/move`, { method: "POST", body: JSON.stringify(data) }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
            qc.invalidateQueries({ queryKey: ["workspace-file-content", workspaceId] });
        },
    });
}
// File upload (multipart — cannot use apiFetch which sets JSON content-type)
export function useUploadWorkspaceFile(workspaceId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async ({ file, targetDir }) => {
            const { useAuthStore } = await import("../../stores/auth");
            const { serverUrl } = useAuthStore.getState();
            const { getAuthToken } = await import("../../stores/auth");
            if (!serverUrl)
                throw new Error("Server not configured");
            const formData = new FormData();
            formData.append("file", file);
            formData.append("target_dir", targetDir);
            const token = getAuthToken();
            const res = await fetch(`${serverUrl}/api/v1/workspaces/${workspaceId}/files/upload`, {
                method: "POST",
                headers: token ? { Authorization: `Bearer ${token}` } : {},
                body: formData,
            });
            if (!res.ok) {
                const body = await res.text().catch(() => null);
                throw new Error(`Upload failed (${res.status}): ${body}`);
            }
            return res.json();
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
        },
    });
}
export function useWorkspaceIndexStatus(workspaceId) {
    return useQuery({
        queryKey: ["workspace-index-status", workspaceId],
        queryFn: () => apiFetch(`/api/v1/workspaces/${workspaceId}/files/index-status`),
        enabled: !!workspaceId,
        staleTime: 30_000,
    });
}
export function useWorkspaceIndexing(workspaceId) {
    return useQuery({
        queryKey: ["workspace-indexing", workspaceId],
        queryFn: () => apiFetch(`/api/v1/workspaces/${workspaceId}/indexing`),
        enabled: !!workspaceId,
        staleTime: 30_000,
    });
}
// Update bot indexing config (segments, patterns, etc.) from workspace page
export function useUpdateBotIndexing(workspaceId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/workspaces/${workspaceId}/bots/${data.bot_id}/indexing`, {
            method: "PUT",
            body: JSON.stringify(data.indexing),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["workspace-indexing", workspaceId] });
            qc.invalidateQueries({ queryKey: ["workspace-index-status", workspaceId] });
            qc.invalidateQueries({ queryKey: ["bots"] });
        },
    });
}
// Cron jobs
export function useWorkspaceCronJobs(workspaceId) {
    return useQuery({
        queryKey: ["workspace-cron-jobs", workspaceId],
        queryFn: () => apiFetch(`/api/v1/workspaces/${workspaceId}/cron-jobs`),
        enabled: !!workspaceId,
    });
}
// Reindex
export function useReindexWorkspace(workspaceId) {
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/workspaces/${workspaceId}/reindex`, { method: "POST" }),
    });
}
