import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useBots() {
    return useQuery({
        queryKey: ["bots"],
        queryFn: () => apiFetch("/bots"),
    });
}
/** Full bot configs via admin endpoint (includes tools, skills, memory, etc.) */
export function useAdminBots() {
    return useQuery({
        queryKey: ["admin-bots"],
        queryFn: async () => {
            const res = await apiFetch("/api/v1/admin/bots");
            return res.bots;
        },
    });
}
export function useBot(botId) {
    return useQuery({
        queryKey: ["bots", botId],
        queryFn: () => apiFetch(`/api/v1/admin/bots/${botId}`),
        enabled: !!botId,
    });
}
export function useBotEditorData(botId) {
    return useQuery({
        queryKey: ["bot-editor", botId],
        queryFn: () => apiFetch(`/api/v1/admin/bots/${botId}/editor-data`),
        enabled: !!botId,
    });
}
export function useUpdateBot(botId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/admin/bots/${botId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["bots", botId] });
            qc.invalidateQueries({ queryKey: ["bot-editor", botId] });
            qc.invalidateQueries({ queryKey: ["bots"] });
        },
    });
}
export function useCreateBot() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/admin/bots", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["bots"] });
        },
    });
}
export function useDeleteBot() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ botId, force }) => apiFetch(`/api/v1/admin/bots/${botId}${force ? "?force=true" : ""}`, {
            method: "DELETE",
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["bots"] });
            qc.invalidateQueries({ queryKey: ["admin-bots"] });
        },
    });
}
export function useBotSandboxStatus(botId, enabled = true) {
    return useQuery({
        queryKey: ["bot-sandbox", botId],
        queryFn: () => apiFetch(`/api/v1/admin/bots/${botId}/sandbox`),
        enabled: !!botId && enabled,
        refetchInterval: 30_000,
    });
}
export function useRecreateBotSandbox(botId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/bots/${botId}/sandbox/recreate`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["bot-sandbox", botId] });
        },
    });
}
