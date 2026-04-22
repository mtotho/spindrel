import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useProviders(enabled = true) {
    return useQuery({
        queryKey: ["admin-providers"],
        queryFn: () => apiFetch("/api/v1/admin/providers"),
        enabled,
    });
}
export function useProvider(providerId) {
    return useQuery({
        queryKey: ["admin-provider", providerId],
        queryFn: () => apiFetch(`/api/v1/admin/providers/${providerId}`),
        enabled: !!providerId && providerId !== "new",
    });
}
export function useCreateProvider() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/admin/providers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-providers"] });
        },
    });
}
export function useUpdateProvider(providerId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/admin/providers/${providerId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-providers"] });
            qc.invalidateQueries({ queryKey: ["admin-provider", providerId] });
        },
    });
}
export function useDeleteProvider() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (providerId) => apiFetch(`/api/v1/admin/providers/${providerId}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-providers"] });
        },
    });
}
export function useTestProvider() {
    return useMutation({
        mutationFn: (providerId) => apiFetch(`/api/v1/admin/providers/${providerId}/test`, {
            method: "POST",
        }),
    });
}
export function useTestProviderInline() {
    return useMutation({
        mutationFn: (data) => apiFetch("/api/v1/admin/providers/test-inline", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
    });
}
export function useProviderModels(providerId) {
    return useQuery({
        queryKey: ["admin-provider-models", providerId],
        queryFn: () => apiFetch(`/api/v1/admin/providers/${providerId}/models`),
        enabled: !!providerId && providerId !== "new",
    });
}
export function useAddProviderModel(providerId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => apiFetch(`/api/v1/admin/providers/${providerId}/models`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-provider-models", providerId] });
            qc.invalidateQueries({ queryKey: ["models"] });
        },
    });
}
export function useDeleteProviderModel(providerId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (modelPk) => apiFetch(`/api/v1/admin/providers/${providerId}/models/${modelPk}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-provider-models", providerId] });
            qc.invalidateQueries({ queryKey: ["models"] });
        },
    });
}
export function useProviderTypeCapabilities(providerType) {
    return useQuery({
        queryKey: ["provider-type-capabilities", providerType],
        queryFn: () => apiFetch(`/api/v1/admin/provider-types/${providerType}/capabilities`),
        enabled: !!providerType,
    });
}
export function useProviderCapabilities(providerId) {
    return useQuery({
        queryKey: ["provider-capabilities", providerId],
        queryFn: () => apiFetch(`/api/v1/admin/providers/${providerId}/capabilities`),
        enabled: !!providerId && providerId !== "new",
    });
}
export function useSyncProviderModels(providerId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch(`/api/v1/admin/providers/${providerId}/sync-models`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-provider-models", providerId] });
            qc.invalidateQueries({ queryKey: ["models"] });
        },
    });
}
export function usePullModel(providerId) {
    return useMutation({
        mutationFn: (modelName) => apiFetch(`/api/v1/admin/providers/${providerId}/pull-model`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_name: modelName }),
        }),
    });
}
export function useDeleteRemoteModel(providerId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (modelName) => apiFetch(`/api/v1/admin/providers/${providerId}/remote-models/${encodeURIComponent(modelName)}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["admin-provider-models", providerId] });
            qc.invalidateQueries({ queryKey: ["models"] });
            qc.invalidateQueries({ queryKey: ["running-models", providerId] });
        },
    });
}
export function useRunningModels(providerId, enabled = true) {
    return useQuery({
        queryKey: ["running-models", providerId],
        queryFn: () => apiFetch(`/api/v1/admin/providers/${providerId}/running-models`),
        enabled: !!providerId && providerId !== "new" && enabled,
        refetchInterval: 10_000,
    });
}
export function useRemoteModelInfo(providerId, modelName) {
    return useQuery({
        queryKey: ["remote-model-info", providerId, modelName],
        queryFn: () => apiFetch(`/api/v1/admin/providers/${providerId}/remote-models/${encodeURIComponent(modelName)}/info`),
        enabled: !!providerId && providerId !== "new" && !!modelName,
    });
}
export function useOpenAIOAuthStatus(providerId, enabled = true) {
    return useQuery({
        queryKey: ["openai-oauth-status", providerId],
        queryFn: () => apiFetch(`/api/v1/admin/providers/openai-oauth/status/${providerId}`),
        enabled: !!providerId && providerId !== "new" && enabled,
    });
}
export function useStartOpenAIOAuth() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (providerId) => apiFetch(`/api/v1/admin/providers/openai-oauth/start/${providerId}`, { method: "POST" }),
        onSuccess: (_data, providerId) => {
            qc.invalidateQueries({ queryKey: ["openai-oauth-status", providerId] });
        },
    });
}
export function usePollOpenAIOAuth() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (providerId) => apiFetch(`/api/v1/admin/providers/openai-oauth/poll/${providerId}`, { method: "POST" }),
        onSuccess: (data, providerId) => {
            if (data.status === "success") {
                qc.invalidateQueries({ queryKey: ["openai-oauth-status", providerId] });
                qc.invalidateQueries({ queryKey: ["admin-provider", providerId] });
            }
        },
    });
}
export function useDisconnectOpenAIOAuth() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (providerId) => apiFetch(`/api/v1/admin/providers/openai-oauth/disconnect/${providerId}`, { method: "POST" }),
        onSuccess: (_data, providerId) => {
            qc.invalidateQueries({ queryKey: ["openai-oauth-status", providerId] });
            qc.invalidateQueries({ queryKey: ["admin-provider", providerId] });
        },
    });
}
