import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { ChannelSessionCatalogItem } from "@/src/lib/channelSessionSurfaces";
import type { SessionProjectInstance } from "@/src/types/api";

export interface ScratchSessionResponse {
  session_id: string;
  parent_channel_id: string;
  bot_id: string;
  created_at: string;
  is_current: boolean;
  title?: string | null;
  summary?: string | null;
  message_count?: number;
  section_count?: number;
  session_scope?: string;
}

export interface ScratchHistoryItem {
  session_id: string;
  bot_id: string;
  created_at: string;
  last_active: string;
  is_current: boolean;
  message_count: number;
  preview?: string;
  title?: string | null;
  summary?: string | null;
  section_count?: number;
  session_scope?: string;
}

export interface SessionSummaryResponse {
  session_id: string;
  bot_id: string;
  channel_id?: string | null;
  parent_channel_id?: string | null;
  session_type: string;
  title?: string | null;
  summary?: string | null;
  created_at: string;
  last_active: string;
  message_count: number;
  section_count: number;
  is_current: boolean;
  session_scope: string;
  project_instance_id?: string | null;
  project_id?: string | null;
  project_instance_status?: string | null;
  project_root_path?: string | null;
}

function scratchCurrentKey(parentChannelId: string, botId: string) {
  return ["scratch-current", parentChannelId, botId] as const;
}

function scratchHistoryKey(parentChannelId: string) {
  return ["scratch-history", parentChannelId] as const;
}

export function channelSessionCatalogKey(channelId: string) {
  return ["channel-session-catalog", channelId] as const;
}

function channelSessionSearchKey(channelId: string, query: string) {
  return ["channel-session-search", channelId, query] as const;
}

export function useScratchSession(
  parentChannelId: string | null | undefined,
  botId: string | null | undefined,
) {
  const enabled = !!parentChannelId && !!botId;
  return useQuery({
    queryKey: enabled
      ? scratchCurrentKey(parentChannelId!, botId!)
      : ["scratch-current", "disabled"],
    queryFn: async (): Promise<ScratchSessionResponse> => {
      const qs = new URLSearchParams({
        parent_channel_id: parentChannelId!,
        bot_id: botId!,
      });
      return apiFetch<ScratchSessionResponse>(
        `/api/v1/sessions/scratch/current?${qs.toString()}`,
      );
    },
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useResetScratchSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: { parent_channel_id: string; bot_id: string }) =>
      apiFetch<ScratchSessionResponse>("/api/v1/sessions/scratch/reset", {
        method: "POST",
        body: JSON.stringify(req),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({
        queryKey: scratchCurrentKey(vars.parent_channel_id, vars.bot_id),
      });
      qc.invalidateQueries({
        queryKey: scratchHistoryKey(vars.parent_channel_id),
      });
      qc.invalidateQueries({
        queryKey: channelSessionCatalogKey(vars.parent_channel_id),
      });
    },
  });
}

export function useScratchHistory(
  parentChannelId: string | null | undefined,
) {
  return useQuery({
    queryKey: parentChannelId
      ? scratchHistoryKey(parentChannelId)
      : ["scratch-history", "disabled"],
    queryFn: async (): Promise<ScratchHistoryItem[]> => {
      const qs = new URLSearchParams({
        parent_channel_id: parentChannelId!,
      });
      return apiFetch<ScratchHistoryItem[]>(
        `/api/v1/sessions/scratch/list?${qs.toString()}`,
      );
    },
    enabled: !!parentChannelId,
    staleTime: 60_000,
  });
}

export function useChannelSessionCatalog(channelId: string | null | undefined) {
  return useQuery({
    queryKey: channelId ? channelSessionCatalogKey(channelId) : ["channel-session-catalog", "disabled"],
    queryFn: async (): Promise<ChannelSessionCatalogItem[]> => {
      const data = await apiFetch<{ sessions: ChannelSessionCatalogItem[] }>(
        `/api/v1/channels/${channelId}/sessions?limit=100`,
      );
      return data.sessions;
    },
    enabled: !!channelId,
    staleTime: 60_000,
  });
}

export function useChannelSessionSearch(
  channelId: string | null | undefined,
  query: string,
) {
  const q = query.trim();
  return useQuery({
    queryKey: channelId && q.length >= 2
      ? channelSessionSearchKey(channelId, q)
      : ["channel-session-search", "disabled"],
    queryFn: async (): Promise<ChannelSessionCatalogItem[]> => {
      const params = new URLSearchParams({ q, limit: "100" });
      const data = await apiFetch<{ query: string; sessions: ChannelSessionCatalogItem[] }>(
        `/api/v1/channels/${channelId}/sessions/search?${params.toString()}`,
      );
      return data.sessions;
    },
    enabled: !!channelId && q.length >= 2,
    staleTime: 30_000,
  });
}

export function useSessionSummary(
  sessionId: string | null | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: sessionId ? ["session-summary", sessionId] : ["session-summary", "disabled"],
    queryFn: () => apiFetch<SessionSummaryResponse>(`/api/v1/sessions/${sessionId}/summary`),
    enabled: !!sessionId && enabled,
    staleTime: 60_000,
  });
}

function sessionProjectInstanceKey(sessionId: string) {
  return ["session-project-instance", sessionId] as const;
}

function invalidateSessionWorkSurface(
  qc: ReturnType<typeof useQueryClient>,
  sessionId: string,
  data?: SessionProjectInstance,
) {
  qc.invalidateQueries({ queryKey: sessionProjectInstanceKey(sessionId) });
  qc.invalidateQueries({ queryKey: ["session-summary", sessionId] });
  qc.invalidateQueries({ queryKey: ["session-header-stats"] });
  qc.invalidateQueries({ queryKey: ["session-harness-status", sessionId] });
  if (data?.project_id) {
    qc.invalidateQueries({ queryKey: ["projects", data.project_id, "instances"] });
  }
}

export function useSessionProjectInstance(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: sessionId ? sessionProjectInstanceKey(sessionId) : ["session-project-instance", "disabled"],
    queryFn: () => apiFetch<SessionProjectInstance>(`/api/v1/sessions/${sessionId}/project-instance`),
    enabled: !!sessionId,
    staleTime: 30_000,
  });
}

export function useCreateSessionProjectInstance(sessionId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SessionProjectInstance>(`/api/v1/sessions/${sessionId}/project-instance`, {
        method: "POST",
      }),
    onSuccess: (data) => {
      if (sessionId) invalidateSessionWorkSurface(qc, sessionId, data);
    },
  });
}

export function useClearSessionProjectInstance(sessionId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SessionProjectInstance>(`/api/v1/sessions/${sessionId}/project-instance`, {
        method: "DELETE",
      }),
    onSuccess: (data) => {
      if (sessionId) invalidateSessionWorkSurface(qc, sessionId, data);
    },
  });
}

export function useRenameSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: { session_id: string; title: string; parent_channel_id?: string; bot_id?: string }) =>
      apiFetch<{ session_id: string; title?: string | null; summary?: string | null }>(`/api/v1/sessions/${req.session_id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: req.title }),
      }),
    onSuccess: (_data, vars) => {
      if (vars.parent_channel_id) {
        qc.invalidateQueries({ queryKey: scratchHistoryKey(vars.parent_channel_id) });
        qc.invalidateQueries({ queryKey: channelSessionCatalogKey(vars.parent_channel_id) });
      }
      if (vars.parent_channel_id && vars.bot_id) {
        qc.invalidateQueries({
          queryKey: scratchCurrentKey(vars.parent_channel_id, vars.bot_id),
        });
      }
    },
  });
}

export function usePromoteScratchSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: { session_id: string; parent_channel_id: string; bot_id?: string }) =>
      apiFetch<{ primary_session_id: string; demoted_session_id: string; channel_id: string }>(
        `/api/v1/sessions/${req.session_id}/promote-to-primary`,
        { method: "POST" },
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: scratchHistoryKey(vars.parent_channel_id) });
      qc.invalidateQueries({ queryKey: channelSessionCatalogKey(vars.parent_channel_id) });
      if (vars.bot_id) {
        qc.invalidateQueries({
          queryKey: scratchCurrentKey(vars.parent_channel_id, vars.bot_id),
        });
      }
      qc.invalidateQueries({ queryKey: ["channels", vars.parent_channel_id] });
    },
  });
}
