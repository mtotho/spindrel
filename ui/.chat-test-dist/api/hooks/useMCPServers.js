import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useMCPServers(enabled = true) {
    return useQuery({
        queryKey: ["admin-mcp-servers"],
        queryFn: () => apiFetch("/api/v1/admin/mcp-servers"),
        enabled,
    });
}
export function useMCPServer(serverId) {
    return useQuery({
        queryKey: ["admin-mcp-server", serverId],
        queryFn: () => apiFetch(`/api/v1/admin/mcp-servers/${serverId}`),
        enabled: !!serverId && serverId !== "new",
    });
}
export function useCreateMCPServer() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/admin/mcp-servers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-mcp-servers"] });
            qc.invalidateQueries({ queryKey: ["admin-tools"] });
        },
    });
}
export function useUpdateMCPServer(serverId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/admin/mcp-servers/${serverId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-mcp-servers"] });
            qc.invalidateQueries({ queryKey: ["admin-mcp-server", serverId] });
            qc.invalidateQueries({ queryKey: ["admin-tools"] });
        },
    });
}
export function useDeleteMCPServer() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (serverId) => apiFetch(`/api/v1/admin/mcp-servers/${serverId}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-mcp-servers"] });
            qc.invalidateQueries({ queryKey: ["admin-tools"] });
        },
    });
}
export function useTestMCPServer() {
    return useMutation({
        mutationFn: (serverId) => apiFetch(`/api/v1/admin/mcp-servers/${serverId}/test`, {
            method: "POST",
        }),
    });
}
export function useTestMCPServerInline() {
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/admin/mcp-servers/test-inline", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
    });
}
