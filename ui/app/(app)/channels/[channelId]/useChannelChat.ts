import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { useSubmitChat, useCancelChat, useSessionStatus } from "@/src/api/hooks/useChat";
import { useChannelEvents } from "@/src/api/hooks/useChannelEvents";
import { useSecretCheck, type SecretCheckResult } from "@/src/api/hooks/useSecretCheck";
import { apiFetch } from "@/src/api/client";
import { extractDisplayText } from "@/src/components/chat/MessageBubble";
import type { PendingFile } from "@/src/components/chat/MessageInput";
import type { ChatAttachment, ChatFileMetadata, ChatRequest, Message } from "@/src/types/api";
import { type MessagePage, PAGE_SIZE } from "./chatUtils";

export interface UseChannelChatOptions {
  channelId: string | undefined;
  channel: {
    active_session_id?: string | null;
    bot_id: string;
    client_id?: string | null;
    model_override?: string | null;
  } | undefined;
  activeFile: string | null;
}

export interface UseChannelChatReturn {
  /** Chat store state for this channel */
  chatState: ReturnType<typeof useChatStore.getState>["channels"][string];
  /** Flattened messages from DB, in chronological order (newest last) */
  invertedData: Message[];
  /** TanStack Query loading state */
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean | undefined;
  /** Handlers */
  handleSend: (text: string, files?: PendingFile[]) => void;
  handleSendAudio: (audioBase64: string, audioFormat: string, message?: string) => void;
  handleCancel: () => void;
  handleRetry: () => void;
  handleSlashCommand: (id: string) => Promise<void>;
  handleLoadMore: () => void;
  handleListLayout: (e: any) => void;
  handleContentSizeChange: (w: number, h: number) => void;
  /** Model override state */
  turnModelOverride: string | undefined;
  turnProviderIdOverride: string | null | undefined;
  handleModelOverrideChange: (m: string | undefined, providerId?: string | null) => void;
  /** Secret warning dialog state */
  secretWarning: { result: SecretCheckResult; text: string; files?: PendingFile[] } | null;
  setSecretWarning: React.Dispatch<React.SetStateAction<{ result: SecretCheckResult; text: string; files?: PendingFile[] } | null>>;
  /** Direct send (bypasses secret check -- used after user confirms) */
  doSend: (text: string, files?: PendingFile[]) => void;
  /** Error setter (for clearing) */
  setError: (channelId: string, error: string) => void;
  /** Queue state */
  isQueued: boolean;
  /** Cancel + send immediately (interrupts current response) */
  handleSendNow: (text: string, files?: PendingFile[]) => void;
  /** Cancel queued message without sending */
  cancelQueue: () => void;
}

export function useChannelChat({ channelId, channel, activeFile }: UseChannelChatOptions): UseChannelChatReturn {
  const queryClient = useQueryClient();
  const router = useRouter();

  const chatState = useChatStore((s) => s.getChannel(channelId!));
  const setMessages = useChatStore((s) => s.setMessages);
  const addMessage = useChatStore((s) => s.addMessage);
  const clearProcessing = useChatStore((s) => s.clearProcessing);
  const setError = useChatStore((s) => s.setError);

  // Subscribe to typed channel-events bus events. This is the SOLE source
  // of streaming UI state — POST /chat just acknowledges the turn.
  useChannelEvents(channelId, channel?.bot_id);

  const [turnModelOverride, setTurnModelOverride] = useState<string | undefined>();
  const [turnProviderIdOverride, setTurnProviderIdOverride] = useState<string | null | undefined>();
  const handleModelOverrideChange = useCallback((m: string | undefined, providerId?: string | null) => {
    setTurnModelOverride(m);
    setTurnProviderIdOverride(m ? providerId : undefined);
  }, []);

  const [secretWarning, setSecretWarning] = useState<{
    result: SecretCheckResult;
    text: string;
    files?: PendingFile[];
  } | null>(null);
  const secretCheck = useSecretCheck();

  // ---- Message queue (send while bot is responding) ----
  const queuedRequestRef = useRef<{
    request: ChatRequest;
    channelId: string;
    optimisticMsgId: string;
  } | null>(null);
  const [isQueued, setIsQueued] = useState(false);
  // Ref for checking active state inside async callbacks (avoids stale closures).
  const isActiveRef = useRef(false);
  const turnsCount = Object.keys(chatState.turns).length;
  isActiveRef.current = turnsCount > 0 || chatState.isProcessing;

  // ---- Message fetching ----
  const {
    data: pages,
    isLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["session-messages", channel?.active_session_id],
    queryFn: async ({ pageParam }) => {
      if (!channel?.active_session_id) return { messages: [], has_more: false };
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (pageParam) params.set("before", pageParam);
      return apiFetch<MessagePage>(
        `/sessions/${channel.active_session_id}/messages?${params}`
      );
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more || lastPage.messages.length === 0) return undefined;
      return lastPage.messages[0].id;
    },
    enabled: !!channel?.active_session_id,
  });

  // Sync DB messages into the chat store when new page data arrives.
  // Suppressed while a turn is streaming so we don't clobber the synthetic
  // streamingContent message before it's materialized.
  useEffect(() => {
    if (channelId && pages && turnsCount === 0 && !chatState.isProcessing) {
      const allMessages = [...pages.pages].reverse().flatMap((p) => p.messages)
        .filter((m) => {
          if (m.role !== "user" && m.role !== "assistant") return false;
          const meta = (m as any).metadata ?? {};
          if (meta.passive && !meta.delegated_by) return false;
          if (m.role === "user" && meta.is_heartbeat) return false;
          if (meta.hidden) return false;
          if (m.role === "assistant" && !extractDisplayText(m.content)
              && (!m.attachments || m.attachments.length === 0)) return false;
          return true;
        });

      // Preserve synthetic messages from finishTurn() when the DB doesn't
      // yet have a corresponding assistant row. Two cases:
      //   1. correlation_id match — happy path, drop the synthetic (DB
      //      caught up).
      //   2. no correlation_id match AND no recent DB assistant — likely
      //      a persist failure or in-flight commit. Keep the synthetic so
      //      the user doesn't lose visible content.
      const currentMessages = useChatStore.getState().channels[channelId]?.messages ?? [];
      const dbCorrelationIds = new Set(
        allMessages.map((m) => m.correlation_id).filter(Boolean)
      );
      const newestDbAssistantTs = allMessages
        .filter((m) => m.role === "assistant")
        .reduce<string | null>(
          (acc, m) => (acc === null || m.created_at > acc ? m.created_at : acc),
          null,
        );
      const syntheticToKeep = currentMessages.filter((m) => {
        if (!(m.id.startsWith("turn-") || m.id.startsWith("msg-"))) return false;
        if (m.role !== "assistant") return false;
        // Drop if DB has a row with the same correlation_id.
        if (m.correlation_id && dbCorrelationIds.has(m.correlation_id)) return false;
        // Drop if DB has a NEWER assistant row (the canonical one).
        if (newestDbAssistantTs && m.created_at <= newestDbAssistantTs) return false;
        return true;
      });

      setMessages(channelId, [...allMessages, ...syntheticToKeep]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId, pages]);

  // Poll session status while background processing is active
  const { data: sessionStatus } = useSessionStatus(channelId, chatState.isProcessing);

  const submitChat = useSubmitChat();
  const cancelChat = useCancelChat();
  const lastRequestRef = useRef<Record<string, ChatRequest>>({});

  // ---- Bus-driven queue advance ----
  // When the channel's turn count drops to zero AND there's a queued
  // request, fire it. This replaces the legacy `chatStream.onComplete`
  // callback hook.
  const prevTurnsCountRef = useRef(turnsCount);
  useEffect(() => {
    const wasActive = prevTurnsCountRef.current > 0;
    const nowIdle = turnsCount === 0 && !chatState.isProcessing;
    prevTurnsCountRef.current = turnsCount;

    if (wasActive && nowIdle && queuedRequestRef.current) {
      const queued = queuedRequestRef.current;
      queuedRequestRef.current = null;
      setIsQueued(false);
      lastRequestRef.current[queued.channelId] = queued.request;
      submitChat.mutate(queued.request);
    }
  }, [turnsCount, chatState.isProcessing, submitChat]);

  // When background processing completes, clear state and refetch.
  useEffect(() => {
    if (
      chatState.isProcessing &&
      sessionStatus &&
      !sessionStatus.processing &&
      sessionStatus.pending_tasks === 0
    ) {
      if (channelId) clearProcessing(channelId);
      queryClient.invalidateQueries({ queryKey: ["session-messages"] });
    }
  }, [chatState.isProcessing, sessionStatus, channelId, clearProcessing, queryClient]);

  const handleCancel = useCallback(() => {
    if (!channel || !channelId) return;
    // Server-side cancel — releases the session lock and the turn worker
    // publishes TURN_ENDED(error="cancelled"), which useChannelEvents
    // catches and runs finishTurn for us.
    cancelChat.mutate({
      client_id: channel.client_id ?? "",
      bot_id: channel.bot_id,
    });
    // Local fast-path cleanup so the UI flips back to idle immediately
    // even before the bus event arrives.
    const ch = useChatStore.getState().getChannel(channelId);
    for (const turnId of Object.keys(ch.turns)) {
      useChatStore.getState().finishTurn(channelId, turnId);
    }
    clearProcessing(channelId);
    queryClient.invalidateQueries({ queryKey: ["session-messages"] });

    // If there's a queued message, fire it now.
    const queued = queuedRequestRef.current;
    if (queued) {
      queuedRequestRef.current = null;
      setIsQueued(false);
      setTimeout(() => {
        lastRequestRef.current[queued.channelId] = queued.request;
        submitChat.mutate(queued.request);
      }, 100);
    }
  }, [channel, channelId, cancelChat, clearProcessing, queryClient, submitChat]);

  const handleRetry = useCallback(() => {
    const req = channelId ? lastRequestRef.current[channelId] : undefined;
    if (!channelId || !req) return;
    setError(channelId, "");
    submitChat.mutate(req);
  }, [channelId, setError, submitChat]);

  const doSend = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;

      // If viewing a file in non-split mode, auto-enable split.
      if (activeFile && !useUIStore.getState().fileExplorerSplit) {
        useUIStore.getState().toggleFileExplorerSplit();
      }

      addMessage(channelId, {
        id: `msg-${Date.now()}`,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      });

      let attachments: ChatAttachment[] | undefined;
      let file_metadata: ChatFileMetadata[] | undefined;
      if (files && files.length > 0) {
        attachments = [];
        file_metadata = [];
        for (const pf of files) {
          if (pf.file.type.startsWith("image/")) {
            attachments.push({
              type: "image",
              content: pf.base64,
              mime_type: pf.file.type,
              name: pf.file.name,
            });
          }
          file_metadata.push({
            filename: pf.file.name,
            mime_type: pf.file.type,
            size_bytes: pf.file.size,
            file_data: pf.base64,
          });
        }
      }

      const request: ChatRequest = {
        message: text,
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
        ...(turnModelOverride ? { model_override: turnModelOverride } : {}),
        ...(turnProviderIdOverride != null ? { model_provider_id_override: turnProviderIdOverride } : {}),
        ...(attachments?.length ? { attachments } : {}),
        ...(file_metadata?.length ? { file_metadata } : {}),
      };
      lastRequestRef.current[channelId] = request;
      submitChat.mutate(request);

      setTurnModelOverride(undefined);
      setTurnProviderIdOverride(undefined);
    },
    [channelId, channel, activeFile, turnModelOverride, turnProviderIdOverride, addMessage, submitChat]
  );

  /** Queue a message to send after the current stream/processing finishes. */
  const queueMessage = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;

      if (activeFile && !useUIStore.getState().fileExplorerSplit) {
        useUIStore.getState().toggleFileExplorerSplit();
      }

      // If replacing an existing queued message, remove the old optimistic message.
      if (queuedRequestRef.current) {
        const oldId = queuedRequestRef.current.optimisticMsgId;
        const oldCh = queuedRequestRef.current.channelId;
        const msgs = useChatStore.getState().channels[oldCh]?.messages ?? [];
        setMessages(oldCh, msgs.filter((m) => m.id !== oldId));
      }

      // Add optimistic user message.
      const msgId = `msg-${Date.now()}`;
      addMessage(channelId, {
        id: msgId,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      });

      let attachments: ChatAttachment[] | undefined;
      let file_metadata: ChatFileMetadata[] | undefined;
      if (files && files.length > 0) {
        attachments = [];
        file_metadata = [];
        for (const pf of files) {
          if (pf.file.type.startsWith("image/")) {
            attachments.push({
              type: "image",
              content: pf.base64,
              mime_type: pf.file.type,
              name: pf.file.name,
            });
          }
          file_metadata.push({
            filename: pf.file.name,
            mime_type: pf.file.type,
            size_bytes: pf.file.size,
            file_data: pf.base64,
          });
        }
      }

      const request: ChatRequest = {
        message: text,
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
        ...(turnModelOverride ? { model_override: turnModelOverride } : {}),
        ...(turnProviderIdOverride != null ? { model_provider_id_override: turnProviderIdOverride } : {}),
        ...(attachments?.length ? { attachments } : {}),
        ...(file_metadata?.length ? { file_metadata } : {}),
      };

      queuedRequestRef.current = { request, channelId, optimisticMsgId: msgId };
      setIsQueued(true);

      setTurnModelOverride(undefined);
      setTurnProviderIdOverride(undefined);
    },
    [channelId, channel, activeFile, turnModelOverride, turnProviderIdOverride, addMessage, setMessages],
  );

  const handleSend = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;

      secretCheck.mutate(text, {
        onSuccess: (result) => {
          if (result.has_secrets) {
            setSecretWarning({ result, text, files });
          } else if (isActiveRef.current) {
            queueMessage(text, files);
          } else {
            doSend(text, files);
          }
        },
        onError: () => {
          if (isActiveRef.current) {
            queueMessage(text, files);
          } else {
            doSend(text, files);
          }
        },
      });
    },
    [channelId, channel, doSend, queueMessage, secretCheck]
  );

  const handleSendAudio = useCallback(
    (audioBase64: string, audioFormat: string, message?: string) => {
      if (!channelId || !channel) return;

      if (activeFile && !useUIStore.getState().fileExplorerSplit) {
        useUIStore.getState().toggleFileExplorerSplit();
      }

      addMessage(channelId, {
        id: `msg-${Date.now()}`,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: message || "[voice message]",
        created_at: new Date().toISOString(),
      });

      const request: ChatRequest = {
        message: message || "",
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
        audio_data: audioBase64,
        audio_format: audioFormat,
        ...(turnModelOverride ? { model_override: turnModelOverride } : {}),
        ...(turnProviderIdOverride != null ? { model_provider_id_override: turnProviderIdOverride } : {}),
      };
      lastRequestRef.current[channelId] = request;
      submitChat.mutate(request);

      setTurnModelOverride(undefined);
      setTurnProviderIdOverride(undefined);
    },
    [channelId, channel, activeFile, turnModelOverride, turnProviderIdOverride, addMessage, submitChat]
  );

  /** Cancel + send immediately (bypasses queue). */
  const handleSendNow = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;
      queuedRequestRef.current = null;
      setIsQueued(false);
      handleCancel();
      setTimeout(() => doSend(text, files), 50);
    },
    [channelId, channel, handleCancel, doSend],
  );

  /** Cancel the queued message (remove optimistic message, keep current stream running). */
  const cancelQueue = useCallback(() => {
    if (!queuedRequestRef.current) return;
    const { optimisticMsgId, channelId: qCh } = queuedRequestRef.current;
    queuedRequestRef.current = null;
    setIsQueued(false);
    const msgs = useChatStore.getState().channels[qCh]?.messages ?? [];
    setMessages(qCh, msgs.filter((m) => m.id !== optimisticMsgId));
  }, [setMessages]);

  // Reset queue when channel changes.
  useEffect(() => {
    queuedRequestRef.current = null;
    setIsQueued(false);
  }, [channelId]);

  // Slash command handler
  const handleSlashCommand = useCallback(
    async (id: string) => {
      if (!channelId) return;
      switch (id) {
        case "stop":
          handleCancel();
          break;
        case "context":
          router.push(`/channels/${channelId}/settings#context` as any);
          break;
        case "clear":
          try {
            await apiFetch(`/channels/${channelId}/reset`, { method: "POST" });
            setMessages(channelId, []);
            queryClient.invalidateQueries({ queryKey: ["session-messages"] });
            queryClient.invalidateQueries({ queryKey: ["channel", channelId] });
          } catch (err) {
            console.error("Failed to reset session:", err);
          }
          break;
        case "compact":
          try {
            await apiFetch(`/channels/${channelId}/compact`, { method: "POST" });
            queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          } catch (err) {
            console.error("Failed to compact:", err);
          }
          break;
      }
    },
    [channelId, router, setMessages, queryClient, handleCancel],
  );

  // Reverse for inverted FlatList
  const invertedData = useMemo(
    () => [...chatState.messages].reverse(),
    [chatState.messages],
  );

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Auto-load older pages when content doesn't fill the viewport
  const listHeightRef = useRef(0);
  const handleListLayout = useCallback((e: any) => {
    listHeightRef.current = e.nativeEvent.layout.height;
  }, []);
  const handleContentSizeChange = useCallback((_w: number, h: number) => {
    if (h < listHeightRef.current && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return {
    chatState,
    invertedData,
    isLoading,
    isFetchingNextPage,
    hasNextPage,
    handleSend,
    handleSendAudio,
    handleCancel,
    handleRetry,
    handleSlashCommand,
    handleLoadMore,
    handleListLayout,
    handleContentSizeChange,
    turnModelOverride,
    turnProviderIdOverride,
    handleModelOverrideChange,
    secretWarning,
    setSecretWarning,
    doSend,
    setError,
    isQueued,
    handleSendNow,
    cancelQueue,
  };
}
