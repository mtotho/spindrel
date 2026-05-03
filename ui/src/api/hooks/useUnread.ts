import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../client";
import { getAuthToken } from "../../stores/auth";
import { getApiBase, isApiConfigured } from "../client";
import { useChannelReadStore } from "../../stores/channelRead";
import { toast } from "../../stores/toast";
import { mergeUnreadStateUpdates } from "../../lib/unreadStateCache";
import { unreadStateHref } from "../../lib/unreadNavigation";

export interface SessionReadState {
  user_id: string;
  session_id: string;
  channel_id: string | null;
  last_read_message_id: string | null;
  last_read_at: string | null;
  first_unread_at: string | null;
  latest_unread_at: string | null;
  latest_unread_message_id: string | null;
  latest_unread_correlation_id: string | null;
  unread_agent_reply_count: number;
  reminder_due_at: string | null;
  reminder_sent_at: string | null;
}

export interface UnreadStateResponse {
  states: SessionReadState[];
  channels: {
    channel_id: string | null;
    unread_agent_reply_count: number;
    latest_unread_at: string | null;
  }[];
}

export interface UnreadNotificationTarget {
  id: string;
  label: string;
  kind: string;
  config: Record<string, unknown>;
}

export interface UnreadNotificationRule {
  id: string;
  user_id: string;
  channel_id: string | null;
  enabled: boolean;
  target_mode: "inherit" | "replace";
  target_ids: string[];
  immediate_enabled: boolean;
  reminder_enabled: boolean;
  reminder_delay_minutes: number;
  preview_policy: "none" | "short" | "full";
}

interface UnreadRulesResponse {
  rules: UnreadNotificationRule[];
  targets: UnreadNotificationTarget[];
}

interface MarkReadResponse {
  states?: SessionReadState[];
  updated?: number;
}

interface VisibleResponse {
  state?: SessionReadState;
}

function applyUnreadState(data: UnreadStateResponse) {
  const counts: Record<string, number> = {};
  for (const row of data.channels) {
    if (row.channel_id) counts[row.channel_id] = row.unread_agent_reply_count;
  }
  useChannelReadStore.getState().setMany(counts);
}

function applyReadState(state: SessionReadState) {
  if (!state.channel_id) return;
  // The event is per-session. Refetch soon for exact channel rollup; this
  // immediate update keeps badges responsive for the common one-session case.
  useChannelReadStore.getState().setChannelUnread(state.channel_id, state.unread_agent_reply_count);
}

function mergeReadStatesIntoUnreadCache(
  queryClient: ReturnType<typeof useQueryClient>,
  states: SessionReadState[],
): boolean {
  let merged = false;
  queryClient.setQueryData<UnreadStateResponse>(["unread-state"], (current) => {
    const next = mergeUnreadStateUpdates(current, states) as UnreadStateResponse | undefined;
    merged = !!next;
    if (next) applyUnreadState(next);
    return next;
  });
  if (!merged) {
    for (const state of states) applyReadState(state);
  }
  return merged;
}

export function useUnreadState() {
  const query = useQuery({
    queryKey: ["unread-state"],
    queryFn: () => apiFetch<UnreadStateResponse>("/api/v1/unread/state"),
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });
  useEffect(() => {
    if (query.data) applyUnreadState(query.data);
  }, [query.data]);
  return query;
}

export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { session_id?: string; channel_id?: string; message_id?: string; source?: string; surface?: string }) =>
      apiFetch<MarkReadResponse>("/api/v1/unread/read", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      if (data.states?.length) {
        mergeReadStatesIntoUnreadCache(queryClient, data.states);
        queryClient.invalidateQueries({ queryKey: ["recent-sessions"] });
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["unread-state"] });
      queryClient.invalidateQueries({ queryKey: ["recent-sessions"] });
    },
  });
}

export function useMarkSessionVisible() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { session_id: string; surface?: string; mark_read?: boolean }) =>
      apiFetch<VisibleResponse>("/api/v1/unread/visible", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      if (data.state) {
        mergeReadStatesIntoUnreadCache(queryClient, [data.state]);
      }
    },
  });
}

export function useUnreadRules() {
  return useQuery({
    queryKey: ["unread-rules"],
    queryFn: () => apiFetch<UnreadRulesResponse>("/api/v1/unread/rules"),
  });
}

export function useUpdateUnreadRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      channel_id?: string | null;
      enabled: boolean;
      target_mode: "inherit" | "replace";
      target_ids: string[];
      immediate_enabled: boolean;
      reminder_enabled: boolean;
      reminder_delay_minutes: number;
      preview_policy: "none" | "short" | "full";
    }) =>
      apiFetch<UnreadNotificationRule>("/api/v1/unread/rules", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["unread-rules"] });
    },
  });
}

export function useUnreadEvents() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const lastSeqRef = useRef<number | null>(null);
  const lastToastAtBySession = useRef<Record<string, number>>({});

  useEffect(() => {
    if (!isApiConfigured()) return;

    let stopped = false;
    let retryCount = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let ctrl: AbortController | null = null;

    function connect() {
      if (stopped) return;
      const token = getAuthToken();
      ctrl = new AbortController();
      const since = lastSeqRef.current != null ? `?since=${lastSeqRef.current}` : "";
      fetch(`${getApiBase()}/api/v1/unread/events${since}`, {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          Accept: "text/event-stream",
        },
        signal: ctrl.signal,
      })
        .then(async (res) => {
          if (!res.ok || !res.body) throw new Error(`unread SSE failed: ${res.status}`);
          retryCount = 0;
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!stopped) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              try {
                const wire = JSON.parse(line.slice(6));
                if (typeof wire.seq === "number") lastSeqRef.current = wire.seq;
                if (wire.kind !== "read_state_updated") continue;
                const state = wire.payload?.state as SessionReadState | undefined;
                if (!state) continue;
                mergeReadStatesIntoUnreadCache(queryClient, [state]);
                if (state.unread_agent_reply_count > 0 && state.channel_id) {
                  const now = Date.now();
                  const lastToastAt = lastToastAtBySession.current[state.session_id] ?? 0;
                  if (now - lastToastAt > 10_000) {
                    lastToastAtBySession.current[state.session_id] = now;
                    toast({
                      kind: "info",
                      message: "New agent reply",
                      action: {
                        label: "Open",
                        onClick: () => navigate(unreadStateHref(state) ?? `/channels/${state.channel_id}`),
                      },
                      durationMs: 6000,
                    });
                  }
                }
              } catch {
                // Ignore malformed frames and keep the stream alive.
              }
            }
          }
          if (!stopped) retryTimer = setTimeout(connect, 1000);
        })
        .catch(() => {
          if (stopped || ctrl?.signal.aborted) return;
          const delay = Math.min(1000 * 2 ** retryCount, 30000);
          retryCount = Math.min(retryCount + 1, 10);
          retryTimer = setTimeout(connect, delay);
        });
    }

    connect();
    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      ctrl?.abort();
    };
  }, [navigate, queryClient]);
}
