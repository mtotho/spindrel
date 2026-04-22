import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useWebhooks(enabled = true) {
    return useQuery({
        queryKey: ["admin-webhooks"],
        queryFn: () => apiFetch("/api/v1/admin/webhooks"),
        enabled,
    });
}
export function useWebhook(webhookId) {
    return useQuery({
        queryKey: ["admin-webhook", webhookId],
        queryFn: () => apiFetch(`/api/v1/admin/webhooks/${webhookId}`),
        enabled: !!webhookId && webhookId !== "new",
    });
}
export function useWebhookEvents() {
    return useQuery({
        queryKey: ["admin-webhook-events"],
        queryFn: () => apiFetch("/api/v1/admin/webhooks/events"),
    });
}
export function useCreateWebhook() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/admin/webhooks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-webhooks"] });
        },
    });
}
export function useUpdateWebhook(webhookId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/admin/webhooks/${webhookId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-webhooks"] });
            qc.invalidateQueries({ queryKey: ["admin-webhook", webhookId] });
        },
    });
}
export function useDeleteWebhook() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (webhookId) => apiFetch(`/api/v1/admin/webhooks/${webhookId}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-webhooks"] });
        },
    });
}
export function useRotateWebhookSecret(webhookId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/webhooks/${webhookId}/rotate-secret`, {
            method: "POST",
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-webhook", webhookId] });
        },
    });
}
export function useTestWebhook(webhookId) {
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/webhooks/${webhookId}/test`, {
            method: "POST",
        }),
    });
}
export function useWebhookDeliveries(webhookId, params) {
    const searchParams = new URLSearchParams();
    if (params?.event)
        searchParams.set("event", params.event);
    if (params?.limit)
        searchParams.set("limit", String(params.limit));
    if (params?.offset)
        searchParams.set("offset", String(params.offset));
    const qs = searchParams.toString();
    return useQuery({
        queryKey: ["admin-webhook-deliveries", webhookId, params],
        queryFn: () => apiFetch(`/api/v1/admin/webhooks/${webhookId}/deliveries${qs ? `?${qs}` : ""}`),
        enabled: !!webhookId && webhookId !== "new",
        refetchInterval: 10_000,
    });
}
