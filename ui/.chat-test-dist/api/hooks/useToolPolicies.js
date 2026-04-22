import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useToolPolicies(botId, toolName, enabled = true) {
    const params = new URLSearchParams();
    if (botId)
        params.set("bot_id", botId);
    if (toolName)
        params.set("tool_name", toolName);
    const qs = params.toString();
    return useQuery({
        queryKey: ["tool-policies", botId, toolName],
        queryFn: () => apiFetch(`/api/v1/tool-policies${qs ? `?${qs}` : ""}`),
        enabled,
    });
}
export function useToolPolicy(ruleId) {
    return useQuery({
        queryKey: ["tool-policy", ruleId],
        queryFn: () => apiFetch(`/api/v1/tool-policies/${ruleId}`),
        enabled: false, // No single-get endpoint; we filter from list
    });
}
export function useCreateToolPolicy() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/tool-policies", {
            method: "POST",
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["tool-policies"] });
        },
    });
}
export function useUpdateToolPolicy(ruleId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/tool-policies/${ruleId}`, {
            method: "PUT",
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["tool-policies"] });
        },
    });
}
export function useDeleteToolPolicy() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (ruleId) => apiFetch(`/api/v1/tool-policies/${ruleId}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["tool-policies"] });
        },
    });
}
export function useTestToolPolicy() {
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/tool-policies/test", {
            method: "POST",
            body: JSON.stringify(data),
        }),
    });
}
export function usePolicySettings() {
    return useQuery({
        queryKey: ["tool-policy-settings"],
        queryFn: () => apiFetch("/api/v1/tool-policies/settings"),
    });
}
export function useUpdatePolicySettings() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/tool-policies/settings", {
            method: "PUT",
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["tool-policy-settings"] });
        },
    });
}
