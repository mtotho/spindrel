import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useTools(enabled = true) {
    return useQuery({
        queryKey: ["admin-tools"],
        queryFn: () => apiFetch("/api/v1/admin/tools"),
        enabled,
    });
}
export function useTool(toolId) {
    return useQuery({
        queryKey: ["admin-tool", toolId],
        queryFn: () => apiFetch(`/api/v1/admin/tools/${toolId}`),
        enabled: !!toolId,
    });
}
export function usePublicToolSignature(toolName) {
    return useQuery({
        queryKey: ["tool-signature", toolName],
        queryFn: () => apiFetch(`/api/v1/tools/${encodeURIComponent(toolName ?? "")}/signature`),
        enabled: !!toolName,
    });
}
export function executeTool(toolName, args, opts) {
    const body = { arguments: args };
    if (opts?.bot_id)
        body.bot_id = opts.bot_id;
    if (opts?.channel_id)
        body.channel_id = opts.channel_id;
    return apiFetch(`/api/v1/admin/tools/${encodeURIComponent(toolName)}/execute`, { method: "POST", body: JSON.stringify(body) });
}
