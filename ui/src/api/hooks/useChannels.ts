import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { Channel, ChannelSettings, ContextBreakdown, EffectiveTools, IntegrationBinding } from "../../types/api";

interface ChannelListResponse {
  channels: Channel[];
  total: number;
  page: number;
  page_size: number;
}

export function useChannels() {
  return useQuery({
    queryKey: ["channels"],
    queryFn: async () => {
      const res = await apiFetch<ChannelListResponse>("/api/v1/admin/channels-enriched?page_size=100");
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
    mutationFn: (body: { name: string; bot_id: string; private?: boolean }) =>
      apiFetch<Channel>("/api/v1/channels", {
        method: "POST",
        body: JSON.stringify(body),
      }),
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
    },
  });
}

export function useChannelEffectiveTools(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-effective-tools", channelId],
    queryFn: () => apiFetch<EffectiveTools>(`/api/v1/admin/channels/${channelId}/effective-tools`),
    enabled: !!channelId,
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

export function useAvailableIntegrations() {
  return useQuery({
    queryKey: ["available-integrations"],
    queryFn: () => apiFetch<string[]>("/api/v1/admin/channels/integrations/available"),
  });
}

// ---------------------------------------------------------------------------
// Context breakdown
// ---------------------------------------------------------------------------

export function useChannelContextBreakdown(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-context-breakdown", channelId],
    queryFn: () => apiFetch<ContextBreakdown>(`/api/v1/admin/channels/${channelId}/context-breakdown`),
    enabled: !!channelId,
  });
}
