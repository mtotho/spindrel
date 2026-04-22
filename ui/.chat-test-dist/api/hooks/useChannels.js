import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import { useChatStore } from "../../stores/chat";
import { useDraftsStore } from "../../stores/drafts";
import { useChannelReadStore } from "../../stores/channelRead";
export function useChannels(opts) {
    const workspaceId = opts?.workspaceId;
    return useQuery({
        queryKey: ["channels", { workspaceId: workspaceId ?? null }],
        queryFn: async () => {
            const params = new URLSearchParams({ page_size: "100" });
            if (workspaceId) {
                params.set("workspace_id", workspaceId);
            }
            const res = await apiFetch(`/api/v1/admin/channels-enriched?${params}`);
            return res.channels;
        },
    });
}
export function useChannel(channelId) {
    return useQuery({
        queryKey: ["channels", channelId],
        queryFn: () => apiFetch(`/api/v1/channels/${channelId}`),
        enabled: !!channelId,
    });
}
export function useCreateChannel() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (body) => apiFetch("/api/v1/channels", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channels"] });
            queryClient.invalidateQueries({ queryKey: ["channel-categories"] });
        },
    });
}
export function useDeleteChannel() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (channelId) => apiFetch(`/api/v1/channels/${channelId}`, { method: "DELETE" }),
        onSuccess: (_data, channelId) => {
            queryClient.invalidateQueries({ queryKey: ["channels"] });
            // Clean up per-channel state in stores to prevent memory leaks
            useChatStore.getState().deleteChannel(channelId);
            useDraftsStore.getState().clearDraft(channelId);
            useChannelReadStore.getState().deleteChannel(channelId);
        },
    });
}
export function useEnsureOrchestrator() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: () => apiFetch("/api/v1/admin/channels/ensure-orchestrator", { method: "POST" }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channels"] });
        },
    });
}
export function useChannelSettings(channelId) {
    return useQuery({
        queryKey: ["channel-settings", channelId],
        queryFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/settings`),
        enabled: !!channelId,
    });
}
export function useUpdateChannelSettings(channelId) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (settings) => apiFetch(`/api/v1/admin/channels/${channelId}/settings`, {
            method: "PUT",
            body: JSON.stringify(settings),
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channel-settings", channelId] });
            queryClient.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
            queryClient.invalidateQueries({ queryKey: ["channels"] });
            queryClient.invalidateQueries({ queryKey: ["resolved-widget-theme", channelId] });
        },
    });
}
export function useChannelEffectiveTools(channelId) {
    return useQuery({
        queryKey: ["channel-effective-tools", channelId],
        queryFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/effective-tools`),
        enabled: !!channelId,
    });
}
export function useChannelEnrolledSkills(channelId) {
    return useQuery({
        queryKey: ["channel-enrolled-skills", channelId],
        queryFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/enrolled-skills`),
        enabled: !!channelId,
    });
}
export function useEnrollChannelSkill(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ skillId, source }) => apiFetch(`/api/v1/admin/channels/${channelId}/enrolled-skills`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ skill_id: skillId, source: source ?? "manual" }),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["channel-enrolled-skills", channelId] });
            qc.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
        },
    });
}
export function useUnenrollChannelSkill(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (skillId) => apiFetch(`/api/v1/admin/channels/${channelId}/enrolled-skills/${encodeURIComponent(skillId)}`, { method: "DELETE" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["channel-enrolled-skills", channelId] });
            qc.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
        },
    });
}
// ---------------------------------------------------------------------------
// Integration bindings
// ---------------------------------------------------------------------------
export function useChannelIntegrations(channelId) {
    return useQuery({
        queryKey: ["channel-integrations", channelId],
        queryFn: () => apiFetch(`/api/v1/channels/${channelId}/integrations`),
        enabled: !!channelId,
    });
}
export function useBindIntegration(channelId) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (body) => apiFetch(`/api/v1/channels/${channelId}/integrations`, {
            method: "POST",
            body: JSON.stringify(body),
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channel-integrations", channelId] });
            queryClient.invalidateQueries({ queryKey: ["channels"] });
        },
    });
}
export function useUnbindIntegration(channelId) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (bindingId) => apiFetch(`/api/v1/channels/${channelId}/integrations/${bindingId}`, {
            method: "DELETE",
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channel-integrations", channelId] });
            queryClient.invalidateQueries({ queryKey: ["channels"] });
        },
    });
}
export function useAdoptIntegration(channelId) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ bindingId, targetChannelId }) => apiFetch(`/api/v1/channels/${channelId}/integrations/${bindingId}/adopt`, {
            method: "POST",
            body: JSON.stringify({ target_channel_id: targetChannelId }),
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channel-integrations"] });
            queryClient.invalidateQueries({ queryKey: ["channels"] });
        },
    });
}
export function useAvailableIntegrations() {
    return useQuery({
        queryKey: ["available-integrations"],
        queryFn: () => apiFetch("/api/v1/admin/channels/integrations/available"),
    });
}
export function useBindingSuggestions(suggestionsEndpoint) {
    return useQuery({
        queryKey: ["binding-suggestions", suggestionsEndpoint],
        queryFn: () => apiFetch(suggestionsEndpoint),
        enabled: !!suggestionsEndpoint,
        staleTime: 5 * 60_000, // server caches for 5 min, no point refetching sooner
    });
}
// ---------------------------------------------------------------------------
// Integration activation
// ---------------------------------------------------------------------------
export function useActivatableIntegrations(channelId) {
    return useQuery({
        queryKey: ["activatable-integrations", channelId],
        queryFn: () => apiFetch(`/api/v1/channels/${channelId}/integrations/available`),
        enabled: !!channelId,
    });
}
export function useActivateIntegration(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (integrationType) => apiFetch(`/api/v1/channels/${channelId}/integrations/${integrationType}/activate`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["activatable-integrations", channelId] });
            qc.invalidateQueries({ queryKey: ["channel-integrations", channelId] });
            qc.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
        },
    });
}
export function useDeactivateIntegration(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (integrationType) => apiFetch(`/api/v1/channels/${channelId}/integrations/${integrationType}/deactivate`, { method: "POST" }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["activatable-integrations", channelId] });
            qc.invalidateQueries({ queryKey: ["channel-integrations", channelId] });
            qc.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
        },
    });
}
export function useUpdateActivationConfig(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ integrationType, config }) => apiFetch(`/api/v1/channels/${channelId}/integrations/${integrationType}/config`, { method: "PATCH", body: JSON.stringify({ config }) }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["activatable-integrations", channelId] });
        },
    });
}
export function useGlobalActivatableIntegrations() {
    return useQuery({
        queryKey: ["activatable-integrations-global"],
        queryFn: () => apiFetch("/api/v1/admin/integrations/activatable"),
    });
}
export function useChannelCategories() {
    return useQuery({
        queryKey: ["channel-categories"],
        queryFn: () => apiFetch("/api/v1/admin/channels/categories"),
    });
}
export function useChannelWorkspaceFiles(channelId, opts = {}) {
    const { includeArchive = false, includeData = false } = opts;
    return useQuery({
        queryKey: ["channel-workspace-files", channelId, includeArchive, includeData],
        queryFn: () => apiFetch(`/api/v1/channels/${channelId}/workspace/files?include_archive=${includeArchive}&include_data=${includeData}`),
        enabled: !!channelId,
    });
}
export function useChannelWorkspaceDataFolder(channelId, dataPrefix) {
    return useQuery({
        queryKey: ["channel-workspace-files", channelId, "data-folder", dataPrefix],
        queryFn: () => apiFetch(`/api/v1/channels/${channelId}/workspace/files?include_data=true&data_prefix=${encodeURIComponent(dataPrefix)}`),
        enabled: !!channelId && !!dataPrefix,
    });
}
export function useChannelWorkspaceFileContent(channelId, path) {
    return useQuery({
        queryKey: ["channel-workspace-file-content", channelId, path],
        queryFn: () => apiFetch(`/api/v1/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(path)}`),
        enabled: !!channelId && !!path,
    });
}
export function useWriteChannelWorkspaceFile(channelId) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ path, content }) => apiFetch(`/api/v1/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(path)}`, {
            method: "PUT",
            body: JSON.stringify({ content }),
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
            queryClient.invalidateQueries({ queryKey: ["channel-workspace-file-content", channelId] });
        },
    });
}
export function useDeleteChannelWorkspaceFile(channelId) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (path) => apiFetch(`/api/v1/channels/${channelId}/workspace/files?path=${encodeURIComponent(path)}`, {
            method: "DELETE",
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
        },
    });
}
export function useMoveChannelWorkspaceFile(channelId) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ old_path, new_path }) => apiFetch(`/api/v1/channels/${channelId}/workspace/files/move`, {
            method: "POST",
            body: JSON.stringify({ old_path, new_path }),
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
            queryClient.invalidateQueries({ queryKey: ["channel-workspace-file-content", channelId] });
        },
    });
}
export function useChannelWorkspaceFileVersions(channelId, path, enabled = true) {
    return useQuery({
        queryKey: ["channel-workspace-file-versions", channelId, path],
        queryFn: () => apiFetch(`/api/v1/channels/${channelId}/workspace/files/versions?path=${encodeURIComponent(path)}`),
        enabled: enabled && !!channelId && !!path,
    });
}
export function useRestoreChannelWorkspaceFile(channelId) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ path, version }) => apiFetch(`/api/v1/channels/${channelId}/workspace/files/restore?path=${encodeURIComponent(path)}`, {
            method: "POST",
            body: JSON.stringify({ version }),
        }),
        onSuccess: (_data, { path }) => {
            queryClient.invalidateQueries({ queryKey: ["channel-workspace-file-versions", channelId, path] });
            queryClient.invalidateQueries({ queryKey: ["channel-workspace-file-content", channelId, path] });
            queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
        },
    });
}
// ---------------------------------------------------------------------------
// Channel workspace file upload (multipart — bypasses apiFetch)
// ---------------------------------------------------------------------------
export function useUploadChannelWorkspaceFile(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async ({ file, targetDir }) => {
            const { useAuthStore, getAuthToken } = await import("../../stores/auth");
            const { serverUrl } = useAuthStore.getState();
            if (!serverUrl)
                throw new Error("Server not configured");
            const formData = new FormData();
            formData.append("file", file);
            const token = getAuthToken();
            const url = `${serverUrl}/api/v1/channels/${channelId}/workspace/files/upload?path=${encodeURIComponent(targetDir)}`;
            const res = await fetch(url, {
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
            qc.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
        },
    });
}
export function useChannelContextBreakdown(channelId, mode = "last_turn") {
    return useQuery({
        queryKey: ["channel-context-breakdown", channelId, mode],
        queryFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/context-breakdown?mode=${mode}`),
        enabled: !!channelId,
        // The endpoint re-runs the full context-assembly pipeline; tab flips /
        // route remounts shouldn't fire it back-to-back. Next-turn / new
        // messages invalidate the key explicitly elsewhere.
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
    });
}
// ---------------------------------------------------------------------------
// Context budget (lightweight — for header indicator)
// ---------------------------------------------------------------------------
export function useChannelContextBudget(channelId, sessionId) {
    return useQuery({
        queryKey: ["channel-context-budget", channelId, sessionId ?? null],
        queryFn: () => {
            const params = new URLSearchParams();
            if (sessionId)
                params.set("session_id", sessionId);
            const qs = params.toString();
            return apiFetch(`/api/v1/admin/channels/${channelId}/context-budget${qs ? `?${qs}` : ""}`);
        },
        enabled: !!channelId,
        staleTime: 60_000, // don't refetch aggressively — SSE updates will override
    });
}
export function useChannelConfigOverhead(channelId) {
    return useQuery({
        queryKey: ["channel-config-overhead", channelId],
        queryFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/config-overhead`),
        enabled: !!channelId,
        staleTime: 120_000,
    });
}
// ---------------------------------------------------------------------------
// Bot members (multi-bot channels)
// ---------------------------------------------------------------------------
export function useChannelBotMembers(channelId) {
    return useQuery({
        queryKey: ["channel-bot-members", channelId],
        queryFn: () => apiFetch(`/api/v1/channels/${channelId}/bot-members`),
        enabled: !!channelId,
    });
}
export function useAddBotMember(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (botId) => apiFetch(`/api/v1/channels/${channelId}/bot-members`, {
            method: "POST",
            body: JSON.stringify({ bot_id: botId }),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["channel-bot-members", channelId] });
            qc.invalidateQueries({ queryKey: ["channels", channelId] });
            qc.invalidateQueries({ queryKey: ["channels"] });
        },
    });
}
export function useRemoveBotMember(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (botId) => apiFetch(`/api/v1/channels/${channelId}/bot-members/${botId}`, {
            method: "DELETE",
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["channel-bot-members", channelId] });
            qc.invalidateQueries({ queryKey: ["channels", channelId] });
            qc.invalidateQueries({ queryKey: ["channels"] });
        },
    });
}
export function useUpdateBotMemberConfig(channelId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ botId, config }) => apiFetch(`/api/v1/channels/${channelId}/bot-members/${botId}/config`, {
            method: "PATCH",
            body: JSON.stringify(config),
        }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["channel-bot-members", channelId] });
        },
    });
}
