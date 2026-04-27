import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { Channel, ChannelBotMember, ChannelBotMemberConfig, ChannelSettings, ContextBreakdown, EffectiveTools, IntegrationBinding, ActivatableIntegration, ActivationResult, ConfigField } from "../../types/api";
import { useChatStore } from "../../stores/chat";
import { useDraftsStore } from "../../stores/drafts";
import { useChannelReadStore } from "../../stores/channelRead";

interface ChannelListResponse {
  channels: Channel[];
  total: number;
  page: number;
  page_size: number;
}

export function useChannels(opts?: { workspaceId?: string | null }) {
  const workspaceId = opts?.workspaceId;
  return useQuery({
    queryKey: ["channels", { workspaceId: workspaceId ?? null }],
    queryFn: async () => {
      const params = new URLSearchParams({ page_size: "100" });
      if (workspaceId) {
        params.set("workspace_id", workspaceId);
      }
      const res = await apiFetch<ChannelListResponse>(`/api/v1/admin/channels-enriched?${params}`);
      return res.channels;
    },
  });
}

export function useChannel(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channels", channelId],
    queryFn: () => apiFetch<Channel>(`/api/v1/channels/${channelId}`),
    enabled: !!channelId,
  });
}

export function useCreateChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      bot_id: string;
      private?: boolean;
      model_override?: string;
      workspace_schema_template_id?: string;
      category?: string;
      activate_integrations?: string[];
      member_bot_ids?: string[];
      user_id?: string;
    }) =>
      apiFetch<Channel>("/api/v1/channels", {
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
    mutationFn: (channelId: string) =>
      apiFetch(`/api/v1/channels/${channelId}`, { method: "DELETE" }),
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
    mutationFn: () =>
      apiFetch<{ id: string; name: string; client_id: string }>(
        "/api/v1/admin/channels/ensure-orchestrator",
        { method: "POST" },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}

export function useChannelSettings(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-settings", channelId],
    queryFn: () => apiFetch<ChannelSettings>(`/api/v1/admin/channels/${channelId}/settings`),
    enabled: !!channelId,
  });
}

export function useUpdateChannelSettings(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: Partial<ChannelSettings>) =>
      apiFetch<ChannelSettings>(`/api/v1/admin/channels/${channelId}/settings`, {
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

export function useChannelEffectiveTools(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-effective-tools", channelId],
    queryFn: () => apiFetch<EffectiveTools>(`/api/v1/admin/channels/${channelId}/effective-tools`),
    enabled: !!channelId,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export interface ChannelEnrolledSkill {
  skill_id: string;
  name: string;
  description?: string | null;
  source: string;
  enrolled_at: string;
}

export function useChannelEnrolledSkills(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-enrolled-skills", channelId],
    queryFn: () => apiFetch<ChannelEnrolledSkill[]>(`/api/v1/admin/channels/${channelId}/enrolled-skills`),
    enabled: !!channelId,
  });
}

export function useEnrollChannelSkill(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ skillId, source }: { skillId: string; source?: string }) =>
      apiFetch<{ status: string; skill_id: string; inserted: boolean }>(
        `/api/v1/admin/channels/${channelId}/enrolled-skills`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ skill_id: skillId, source: source ?? "manual" }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-enrolled-skills", channelId] });
      qc.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
    },
  });
}

export function useUnenrollChannelSkill(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) =>
      apiFetch(
        `/api/v1/admin/channels/${channelId}/enrolled-skills/${encodeURIComponent(skillId)}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-enrolled-skills", channelId] });
      qc.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
    },
  });
}

// ---------------------------------------------------------------------------
// Integration bindings
// ---------------------------------------------------------------------------

export function useChannelIntegrations(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-integrations", channelId],
    queryFn: () => apiFetch<IntegrationBinding[]>(`/api/v1/channels/${channelId}/integrations`),
    enabled: !!channelId,
  });
}

export function useBindIntegration(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { integration_type: string; client_id: string; dispatch_config?: Record<string, any>; display_name?: string }) =>
      apiFetch<IntegrationBinding>(`/api/v1/channels/${channelId}/integrations`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-integrations", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}

export function useUnbindIntegration(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (bindingId: string) =>
      apiFetch(`/api/v1/channels/${channelId}/integrations/${bindingId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-integrations", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}

export function useAdoptIntegration(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ bindingId, targetChannelId }: { bindingId: string; targetChannelId: string }) =>
      apiFetch<IntegrationBinding>(`/api/v1/channels/${channelId}/integrations/${bindingId}/adopt`, {
        method: "POST",
        body: JSON.stringify({ target_channel_id: targetChannelId }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-integrations"] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}

export type { ConfigField } from "../../types/api";

export interface BindingSuggestion {
  client_id: string;
  display_name: string;
  description?: string;
  config_values?: Record<string, any>;
}

export interface AvailableIntegration {
  type: string;
  binding?: {
    client_id_prefix: string;
    client_id_placeholder: string;
    client_id_description: string;
    display_name_placeholder: string;
    config_fields?: ConfigField[];
    event_types?: { value: string; label: string }[];
    suggestions_endpoint?: string;
  } | null;
}

export function useAvailableIntegrations() {
  return useQuery({
    queryKey: ["available-integrations"],
    queryFn: () => apiFetch<AvailableIntegration[]>("/api/v1/admin/channels/integrations/available"),
  });
}

export function useBindingSuggestions(suggestionsEndpoint: string | undefined) {
  return useQuery({
    queryKey: ["binding-suggestions", suggestionsEndpoint],
    queryFn: () => apiFetch<BindingSuggestion[]>(suggestionsEndpoint!),
    enabled: !!suggestionsEndpoint,
    staleTime: 5 * 60_000, // server caches for 5 min, no point refetching sooner
  });
}

// ---------------------------------------------------------------------------
// Integration activation
// ---------------------------------------------------------------------------

export function useActivatableIntegrations(channelId: string | undefined) {
  return useQuery({
    queryKey: ["activatable-integrations", channelId],
    queryFn: () =>
      apiFetch<ActivatableIntegration[]>(
        `/api/v1/channels/${channelId}/integrations/available`
      ),
    enabled: !!channelId,
  });
}

export function useActivateIntegration(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (integrationType: string) =>
      apiFetch<ActivationResult>(
        `/api/v1/channels/${channelId}/integrations/${integrationType}/activate`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["activatable-integrations", channelId] });
      qc.invalidateQueries({ queryKey: ["channel-integrations", channelId] });
      qc.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
    },
  });
}

export function useDeactivateIntegration(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (integrationType: string) =>
      apiFetch(
        `/api/v1/channels/${channelId}/integrations/${integrationType}/deactivate`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["activatable-integrations", channelId] });
      qc.invalidateQueries({ queryKey: ["channel-integrations", channelId] });
      qc.invalidateQueries({ queryKey: ["channel-effective-tools", channelId] });
    },
  });
}

export function useUpdateActivationConfig(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ integrationType, config }: { integrationType: string; config: Record<string, any> }) =>
      apiFetch(
        `/api/v1/channels/${channelId}/integrations/${integrationType}/config`,
        { method: "PATCH", body: JSON.stringify({ config }) }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["activatable-integrations", channelId] });
    },
  });
}

export function useGlobalActivatableIntegrations() {
  return useQuery({
    queryKey: ["activatable-integrations-global"],
    queryFn: () =>
      apiFetch<ActivatableIntegration[]>(
        "/api/v1/admin/integrations/activatable"
      ),
  });
}

export function useChannelCategories() {
  return useQuery({
    queryKey: ["channel-categories"],
    queryFn: () => apiFetch<string[]>("/api/v1/admin/channels/categories"),
  });
}

// ---------------------------------------------------------------------------
// Channel workspace files
// ---------------------------------------------------------------------------

export interface ChannelWorkspaceFile {
  name: string;
  path: string;
  size: number;
  modified_at: number;
  section: "active" | "archive" | "data";
  type?: "folder";
  count?: number;
}

export function useChannelWorkspaceFiles(
  channelId: string | undefined,
  opts: { includeArchive?: boolean; includeData?: boolean } = {},
) {
  const { includeArchive = false, includeData = false } = opts;
  return useQuery({
    queryKey: ["channel-workspace-files", channelId, includeArchive, includeData],
    queryFn: () =>
      apiFetch<{ files: ChannelWorkspaceFile[] }>(
        `/api/v1/channels/${channelId}/workspace/files?include_archive=${includeArchive}&include_data=${includeData}`
      ),
    enabled: !!channelId,
  });
}

export function useChannelWorkspaceDataFolder(
  channelId: string | undefined,
  dataPrefix: string | null,
) {
  return useQuery({
    queryKey: ["channel-workspace-files", channelId, "data-folder", dataPrefix],
    queryFn: () =>
      apiFetch<{ files: ChannelWorkspaceFile[] }>(
        `/api/v1/channels/${channelId}/workspace/files?include_data=true&data_prefix=${encodeURIComponent(dataPrefix!)}`
      ),
    enabled: !!channelId && !!dataPrefix,
  });
}

export function useChannelWorkspaceFileContent(channelId: string | undefined, path: string | null) {
  return useQuery({
    queryKey: ["channel-workspace-file-content", channelId, path],
    queryFn: () =>
      apiFetch<{ path: string; content: string }>(
        `/api/v1/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(path!)}`
      ),
    enabled: !!channelId && !!path,
  });
}

export function useWriteChannelWorkspaceFile(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      apiFetch(`/api/v1/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(path)}`, {
        method: "PUT",
        body: JSON.stringify({ content }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-file-content", channelId] });
    },
  });
}

export function useDeleteChannelWorkspaceFile(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) =>
      apiFetch(`/api/v1/channels/${channelId}/workspace/files?path=${encodeURIComponent(path)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
    },
  });
}

export function useMoveChannelWorkspaceFile(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ old_path, new_path }: { old_path: string; new_path: string }) =>
      apiFetch(`/api/v1/channels/${channelId}/workspace/files/move`, {
        method: "POST",
        body: JSON.stringify({ old_path, new_path }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-file-content", channelId] });
    },
  });
}

export interface WorkspaceFileVersion {
  version: string;   // .bak filename
  bytes: number;
  modified_at: string;  // ISO8601 UTC
}

export function useChannelWorkspaceFileVersions(channelId: string | undefined, path: string | null, enabled: boolean = true) {
  return useQuery({
    queryKey: ["channel-workspace-file-versions", channelId, path],
    queryFn: () =>
      apiFetch<{ path: string; versions: WorkspaceFileVersion[] }>(
        `/api/v1/channels/${channelId}/workspace/files/versions?path=${encodeURIComponent(path!)}`
      ),
    enabled: enabled && !!channelId && !!path,
  });
}

export function useRestoreChannelWorkspaceFile(channelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, version }: { path: string; version: string }) =>
      apiFetch<{ path: string; restored_from: string; prior_backup: string | null; bytes: number }>(
        `/api/v1/channels/${channelId}/workspace/files/restore?path=${encodeURIComponent(path)}`,
        {
          method: "POST",
          body: JSON.stringify({ version }),
        },
      ),
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

export function useUploadChannelWorkspaceFile(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, targetDir }: { file: File; targetDir: string }) => {
      const { useAuthStore, getAuthToken } = await import("../../stores/auth");
      const { serverUrl } = useAuthStore.getState();
      if (!serverUrl) throw new Error("Server not configured");

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

// ---------------------------------------------------------------------------
// Context breakdown
// ---------------------------------------------------------------------------

export type ContextBreakdownMode = "last_turn" | "next_turn";

export function useChannelContextBreakdown(
  channelId: string | undefined,
  mode: ContextBreakdownMode = "last_turn",
) {
  return useQuery({
    queryKey: ["channel-context-breakdown", channelId, mode],
    queryFn: () => apiFetch<ContextBreakdown>(`/api/v1/admin/channels/${channelId}/context-breakdown?mode=${mode}`),
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

export function useChannelContextBudget(
  channelId: string | undefined,
  sessionId?: string | null,
) {
  return useQuery<{
    utilization: number | null;
    consumed_tokens: number | null;
    total_tokens: number | null;
    gross_prompt_tokens?: number | null;
    current_prompt_tokens?: number | null;
    cached_prompt_tokens?: number | null;
    completion_tokens?: number | null;
    context_profile?: string | null;
    source?: string | null;
  }>({
    queryKey: ["channel-context-budget", channelId, sessionId ?? null],
    queryFn: () => {
      const params = new URLSearchParams();
      if (sessionId) params.set("session_id", sessionId);
      const qs = params.toString();
      return apiFetch(`/api/v1/admin/channels/${channelId}/context-budget${qs ? `?${qs}` : ""}`);
    },
    enabled: !!channelId,
    staleTime: 60_000, // don't refetch aggressively — SSE updates will override
  });
}

export interface ContextEstimateLine {
  label: string;
  chars: number;
  hint: string;
}

export interface ContextEstimate {
  lines: ContextEstimateLine[];
  total_chars: number;
  approx_tokens: number;
  context_window: number;
  overhead_pct: number | null;
  disclaimer: string;
}

export function useChannelConfigOverhead(channelId: string | undefined) {
  return useQuery<ContextEstimate>({
    queryKey: ["channel-config-overhead", channelId],
    queryFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/config-overhead`),
    enabled: !!channelId,
    staleTime: 120_000,
  });
}

// ---------------------------------------------------------------------------
// Bot members (multi-bot channels)
// ---------------------------------------------------------------------------

export function useChannelBotMembers(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-bot-members", channelId],
    queryFn: () => apiFetch<ChannelBotMember[]>(`/api/v1/channels/${channelId}/bot-members`),
    enabled: !!channelId,
  });
}

export function useAddBotMember(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) =>
      apiFetch<ChannelBotMember>(`/api/v1/channels/${channelId}/bot-members`, {
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

export function useRemoveBotMember(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) =>
      apiFetch(`/api/v1/channels/${channelId}/bot-members/${botId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-bot-members", channelId] });
      qc.invalidateQueries({ queryKey: ["channels", channelId] });
      qc.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}

export function useUpdateBotMemberConfig(channelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, config }: { botId: string; config: Partial<ChannelBotMemberConfig> }) =>
      apiFetch<ChannelBotMember>(`/api/v1/channels/${channelId}/bot-members/${botId}/config`, {
        method: "PATCH",
        body: JSON.stringify(config),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-bot-members", channelId] });
    },
  });
}
