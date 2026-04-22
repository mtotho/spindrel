import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useApiKeys(enabled = true) {
    return useQuery({
        queryKey: ["admin-api-keys"],
        queryFn: () => apiFetch("/api/v1/admin/api-keys"),
        enabled,
    });
}
export function useApiKey(keyId) {
    return useQuery({
        queryKey: ["admin-api-key", keyId],
        queryFn: () => apiFetch(`/api/v1/admin/api-keys/${keyId}`),
        enabled: !!keyId && keyId !== "new",
    });
}
export function useApiKeyScopes() {
    return useQuery({
        queryKey: ["admin-api-key-scopes"],
        queryFn: () => apiFetch("/api/v1/admin/api-keys/scopes"),
    });
}
export function useCreateApiKey() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/admin/api-keys", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-api-keys"] });
        },
    });
}
export function useUpdateApiKey(keyId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/admin/api-keys/${keyId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-api-keys"] });
            qc.invalidateQueries({ queryKey: ["admin-api-key", keyId] });
        },
    });
}
export function useDeleteApiKey() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (keyId) => apiFetch(`/api/v1/admin/api-keys/${keyId}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-api-keys"] });
        },
    });
}
