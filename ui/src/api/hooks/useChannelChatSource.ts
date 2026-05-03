import { useCallback, useEffect, useMemo, useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import { useChatStore } from "../../stores/chat";
import { useChannel, useUpdateChannelSettings } from "./useChannels";
import { useChannelEvents } from "./useChannelEvents";
import { useChannelState } from "./useChannelState";
import { useCancelChat, useSubmitChat } from "./useChat";
import { MessagePage, PAGE_SIZE } from "@/app/(app)/channels/[channelId]/chatUtils";
import { extractDisplayText } from "@/src/components/chat/messageUtils";
import type { ChatRequest, Message } from "../../types/api";
import { mergePersistedAndSyntheticMessages } from "@/src/components/chat/sessionMessageSync";
import { isHarnessQuestionTransportMessage } from "@/src/components/chat/harnessQuestionMessages";

function makeClientLocalId(): string {
  const cryptoObj = globalThis.crypto as Crypto | undefined;
  if (cryptoObj?.randomUUID) return `web-${cryptoObj.randomUUID()}`;
  return `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface UseChannelChatSourceReturn {
  channelId: string;
  bot_id: string | undefined;
  sessionId: string | undefined;
  chatState: ReturnType<typeof useChatStore.getState>["channels"][string];
  invertedData: Message[];
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean | undefined;
  fetchNextPage: () => Promise<unknown> | void;
  handleSend: (text: string) => void;
  handleCancel: () => void;
  syncCancelledState: () => void;
  isStreaming: boolean;
  sendError: string | null;
  modelOverride: string | undefined;
  modelProviderIdOverride: string | null | undefined;
  setModelOverride: (m: string | undefined, providerId?: string | null) => void;
}

/**
 * Minimal chat-source hook for the channel-mode dock variant of ``ChatSession``.
 *
 * Deliberately a subset of ``useChannelChat`` — read, subscribe, simple send.
 * Queue / slash commands / secret-check / audio / file-explorer side effects
 * are intentionally excluded; the full channel screen remains the canonical
 * place for those.
 *
 * Shares the ``["session-messages", active_session_id]`` TanStack query key
 * and the channel-keyed chat-store slot with the full channel view, so the
 * two mounts (on different routes) see the same transcript + in-flight turns.
 */
export function useChannelChatSource(channelId: string): UseChannelChatSourceReturn {
  const { data: channel } = useChannel(channelId);
  const activeSessionId = channel?.active_session_id ?? undefined;

  const chatState = useChatStore((s) => s.getChannel(channelId));
  const setMessages = useChatStore((s) => s.setMessages);
  const addMessage = useChatStore((s) => s.addMessage);

  useChannelEvents(channelId, channel?.bot_id, {
    sessionFilter: activeSessionId,
  });

  // Snapshot of in-flight turns + pending approvals. Mirrors the full channel
  // page (useChannelChat.ts) so the dock variant rehydrates streaming state
  // on every (re)mount — without this, dismissing the spatial-canvas mini-chat
  // mid-turn and reopening it leaves the typing/tool-call cards dark even
  // though the turn is still running on the server.
  useChannelState(channelId, channel?.bot_id);

  const {
    data: pages,
    isLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["session-messages", activeSessionId],
    queryFn: async ({ pageParam }) => {
      if (!activeSessionId) return { messages: [], has_more: false };
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (pageParam) params.set("before", pageParam);
      return apiFetch<MessagePage>(
        `/sessions/${activeSessionId}/messages?${params}`,
      );
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more || lastPage.messages.length === 0) return undefined;
      return lastPage.messages[0].id;
    },
    enabled: !!activeSessionId,
  });

  const turnsCount = Object.keys(chatState.turns).length;

  // Sync DB pages → chat-store slot. Mirrors the gate in useChannelChat:
  // skip while a turn is streaming (so synthetic content isn't clobbered),
  // but always run on initial load (empty slot) to unblock the rehydrate path.
  useEffect(() => {
    const storeEmpty = (chatState.messages?.length ?? 0) === 0;
    const canSync = turnsCount === 0 && !chatState.isProcessing;
    if (pages && (canSync || storeEmpty)) {
      const allMessages = [...pages.pages].reverse().flatMap((p) => p.messages)
        .filter((m) => {
          const meta = (m as any).metadata ?? {};
          if (meta.kind === "task_run") return true;
          if (m.role !== "user" && m.role !== "assistant") return false;
          if (meta.passive && !meta.delegated_by) return false;
          if (m.role === "user" && meta.is_heartbeat) return false;
          if (meta.hidden) return false;
          if (isHarnessQuestionTransportMessage(m)) return false;
          if (
            m.role === "assistant" &&
            !extractDisplayText(m.content) &&
            (!m.attachments || m.attachments.length === 0) &&
            !meta.tool_results &&
            (!m.tool_calls || m.tool_calls.length === 0) &&
            !meta.assistant_turn_body &&
            !meta.transcript_entries
          )
            return false;
          return true;
        });

      // Preserve synthetic streaming messages that haven't persisted yet.
      // If a fetched row matches by correlation/content but is still
      // structurally weaker (for example: missing widget/rich tool
      // presentation metadata), keep the richer synthetic row until the
      // canonical DB message catches up.
      const current = useChatStore.getState().channels[channelId]?.messages ?? [];
      setMessages(channelId, mergePersistedAndSyntheticMessages(allMessages, current));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId, pages]);

  const submitChat = useSubmitChat();
  const cancelChat = useCancelChat();
  const [sendError, setSendError] = useState<string | null>(null);

  // Model override is persisted on the channel itself. The picker reads the
  // channel's current values and writes back via PATCH /channels/:id/settings.
  const queryClient = useQueryClient();
  const updateChannelSettings = useUpdateChannelSettings(channelId);
  const modelOverride = channel?.model_override ?? undefined;
  const modelProviderIdOverride = channel?.model_provider_id_override ?? undefined;
  const setModelOverride = useCallback(
    (m: string | undefined, providerId?: string | null) => {
      queryClient.setQueryData<any>(["channels", channelId], (old: any) =>
        old ? { ...old, model_override: m ?? null, model_provider_id_override: m ? (providerId ?? null) : null } : old,
      );
      updateChannelSettings.mutate({
        model_override: m ?? null,
        model_provider_id_override: m ? (providerId ?? null) : null,
      });
    },
    [channelId, updateChannelSettings, queryClient],
  );

  const isStreaming = turnsCount > 0 || chatState.isProcessing || submitChat.isPending;

  const syncCancelledState = useCallback(() => {
    const ch = useChatStore.getState().getChannel(channelId);
    for (const turnId of Object.keys(ch.turns)) {
      useChatStore.getState().handleTurnEvent(channelId, turnId, {
        event: "error",
        data: { message: "cancelled" },
      });
      useChatStore.getState().finishTurn(channelId, turnId);
    }
    useChatStore.getState().clearProcessing(channelId);
  }, [channelId]);

  const handleCancel = useCallback(() => {
    if (!channel) return;
    cancelChat.mutate({
      client_id: channel.client_id ?? "",
      bot_id: channel.bot_id,
    });
    syncCancelledState();
  }, [cancelChat, channel, syncCancelledState]);

  const handleSend = useCallback(
    (text: string) => {
      if (!channel || !channelId) return;
      setSendError(null);
      const clientLocalId = makeClientLocalId();
      const optimisticMsgId = `msg-${clientLocalId}`;
      addMessage(channelId, {
        id: optimisticMsgId,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
        metadata: {
          source: "web",
          sender_type: "human",
          client_local_id: clientLocalId,
          local_status: "sending",
        },
      });
      const req: ChatRequest = {
        message: text,
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
        msg_metadata: {
          source: "web",
          sender_type: "human",
          client_local_id: clientLocalId,
        },
      };
      submitChat.mutate(req, {
        onSuccess: (result) => {
          if (result.queued) {
            const store = useChatStore.getState();
            const current = store.channels[channelId]?.messages ?? [];
            const localQueuedCount = current.filter((message) => {
              const meta = (message.metadata ?? {}) as Record<string, unknown>;
              return message.role === "user" && (message.id === optimisticMsgId || meta.local_status === "queued");
            }).length;
            const queuedCount = Math.max(result.queued_message_count ?? 0, localQueuedCount);
            setMessages(channelId, current.map((message) => {
              const meta = (message.metadata ?? {}) as Record<string, any>;
              const isQueuedLocal =
                message.role === "user" &&
                (message.id === optimisticMsgId || meta.local_status === "queued");
              if (!isQueuedLocal) return message;
              return {
                ...message,
                metadata: {
                  ...meta,
                  local_status: "queued",
                  queued_task_id: result.task_id,
                  queued_message_count: queuedCount,
                  queued_coalesced: result.coalesced ?? queuedCount > 1,
                },
              };
            }));
            if (result.task_id) {
              store.setProcessing(channelId, result.task_id);
            }
          }
        },
        onError: (err) =>
          setSendError(err instanceof Error ? err.message : "Failed to send"),
      });
    },
    [channel, channelId, addMessage, setMessages, submitChat],
  );

  const invertedData = useMemo(
    () => [...chatState.messages].reverse(),
    [chatState.messages],
  );

  const fetchNextPageCb = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) return fetchNextPage();
    return undefined;
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return {
    channelId,
    bot_id: channel?.bot_id,
    sessionId: activeSessionId,
    chatState,
    invertedData,
    isLoading,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage: fetchNextPageCb,
    handleSend,
    handleCancel,
    syncCancelledState,
    isStreaming,
    sendError,
    modelOverride,
    modelProviderIdOverride,
    setModelOverride,
  };
}
