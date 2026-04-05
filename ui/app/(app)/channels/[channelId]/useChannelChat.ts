import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { useChatStream, useCancelChat, useSessionStatus } from "@/src/api/hooks/useChat";
import { useChannelEvents } from "@/src/api/hooks/useChannelEvents";
import { useChannelWorkflowRuns } from "@/src/api/hooks/useWorkflows";
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
  const startStreaming = useChatStore((s) => s.startStreaming);
  const handleSSEEvent = useChatStore((s) => s.handleSSEEvent);
  const finishStreaming = useChatStore((s) => s.finishStreaming);
  const clearProcessing = useChatStore((s) => s.clearProcessing);
  const setError = useChatStore((s) => s.setError);

  // Subscribe to real-time channel events (messages from integrations, other tabs, etc.)
  useChannelEvents(channelId);

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
  // Ref for checking active state inside async callbacks (avoids stale closures)
  const isActiveRef = useRef(false);
  isActiveRef.current = chatState.isStreaming || chatState.isProcessing;

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
  // IMPORTANT: Only depend on [channelId, pages] -- NOT streaming/processing state.
  // Streaming state is checked as a guard inside, but must not be a trigger.
  // If it were a dep, finishing a stream would re-run this effect with stale pages
  // (the invalidateQueries refetch hasn't completed yet), overwriting the synthetic
  // message that finishStreaming() just materialized.
  useEffect(() => {
    if (channelId && pages && !chatState.isStreaming && !chatState.isProcessing) {
      const allMessages = [...pages.pages].reverse().flatMap((p) => p.messages)
        .filter((m) => {
          if (m.role !== "user" && m.role !== "assistant") return false;
          const meta = (m as any).metadata ?? {};
          // Hide passive dispatch echoes (ambient messages bot didn't respond to)
          // But show delegated child responses (they arrive as passive with delegated_by attribution)
          if (meta.passive && !meta.delegated_by) return false;
          // Hide heartbeat trigger prompts (injected user messages), but keep bot responses
          if (m.role === "user" && meta.is_heartbeat) return false;
          // Hide member-mention trigger prompts (bot-to-bot @-mention system messages)
          if (meta.hidden) return false;
          // Hide assistant messages with no displayable content (tool-call-only messages)
          // BUT keep messages that have attachments so download links are visible
          if (m.role === "assistant" && !extractDisplayText(m.content)
              && (!m.attachments || m.attachments.length === 0)) return false;
          return true;
        });
      setMessages(channelId, allMessages);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId, pages]);

  // Poll session status while background processing is active
  const { data: sessionStatus } = useSessionStatus(channelId, chatState.isProcessing);

  // When background processing completes, clear state and refetch messages
  useEffect(() => {
    if (
      chatState.isProcessing &&
      sessionStatus &&
      !sessionStatus.processing &&
      sessionStatus.pending_tasks === 0
    ) {
      if (channelId) clearProcessing(channelId);
      queryClient.invalidateQueries({ queryKey: ["session-messages"] });

      // Fire queued message now that processing is done
      const queued = queuedRequestRef.current;
      if (queued) {
        queuedRequestRef.current = null;
        setIsQueued(false);
        setTimeout(() => {
          startStreaming(queued.channelId);
          lastRequestRef.current[queued.channelId] = queued.request;
          chatStream.mutate(queued.request);
        }, 50);
      }
    }
  }, [chatState.isProcessing, sessionStatus, channelId, clearProcessing, queryClient, startStreaming]);

  // Refetch messages when background workflow runs change (heartbeats, scheduled tasks
  // post lifecycle messages that wouldn't otherwise be picked up by SSE).
  const { data: channelWorkflowRuns } = useChannelWorkflowRuns(channelId);
  const prevRunsRef = useRef<string>("");
  useEffect(() => {
    if (!channelId || !channelWorkflowRuns) return;
    const sig = channelWorkflowRuns.map((r) => `${r.id}:${r.status}`).join(",");
    if (prevRunsRef.current && prevRunsRef.current !== sig) {
      queryClient.invalidateQueries({ queryKey: ["session-messages"] });
    }
    prevRunsRef.current = sig;
  }, [channelId, channelWorkflowRuns, queryClient]);

  // ---- Per-channel pending buffers so concurrent streams don't mix deltas ----
  const pendingTextRef = useRef<Record<string, string>>({});
  const pendingThinkRef = useRef<Record<string, string>>({});
  const rafRef = useRef<Record<string, number>>({});
  const lastRequestRef = useRef<Record<string, ChatRequest>>({});

  /** Flush buffered text/thinking deltas for a specific channel */
  const flushChannel = useCallback((chId: string) => {
    rafRef.current[chId] = 0;
    const text = pendingTextRef.current[chId];
    const think = pendingThinkRef.current[chId];
    if (text) {
      handleSSEEvent(chId, { event: "text_delta", data: { delta: text } });
      pendingTextRef.current[chId] = "";
    }
    if (think) {
      handleSSEEvent(chId, { event: "thinking", data: { delta: think } });
      pendingThinkRef.current[chId] = "";
    }
  }, [handleSSEEvent]);

  const cancelChat = useCancelChat();

  const chatStream = useChatStream({
    onEvent: (event) => {
      if (!channelId) return;
      // Batch text and thinking deltas -- flush at ~60fps instead of per-token
      if (event.event === "text_delta") {
        pendingTextRef.current[channelId] = (pendingTextRef.current[channelId] ?? "") + ((event.data as any).delta ?? "");
        if (!rafRef.current[channelId]) {
          const chId = channelId;
          rafRef.current[chId] = requestAnimationFrame(() => flushChannel(chId));
        }
        return;
      }
      if (event.event === "thinking") {
        pendingThinkRef.current[channelId] = (pendingThinkRef.current[channelId] ?? "") + ((event.data as any).delta ?? "");
        if (!rafRef.current[channelId]) {
          const chId = channelId;
          rafRef.current[chId] = requestAnimationFrame(() => flushChannel(chId));
        }
        return;
      }
      // Flush pending text before processing other events (tool_start, response, etc.)
      if (pendingTextRef.current[channelId] || pendingThinkRef.current[channelId]) {
        cancelAnimationFrame(rafRef.current[channelId] || 0);
        flushChannel(channelId);
      }
      handleSSEEvent(channelId, event);
    },
    onError: (error) => {
      if (channelId) {
        // Flush any pending text for this channel
        if (pendingTextRef.current[channelId] || pendingThinkRef.current[channelId]) {
          cancelAnimationFrame(rafRef.current[channelId] || 0);
          flushChannel(channelId);
        }
        // Finish streaming first so any partial content is preserved in messages
        finishStreaming(channelId);
        setError(channelId, error.message);
      }
      // Clear queue on error — don't auto-send into an errored state.
      // Also remove the optimistic user message so it doesn't sit orphaned.
      if (queuedRequestRef.current) {
        const { optimisticMsgId, channelId: qCh } = queuedRequestRef.current;
        queuedRequestRef.current = null;
        setIsQueued(false);
        const msgs = useChatStore.getState().channels[qCh]?.messages ?? [];
        setMessages(qCh, msgs.filter((m) => m.id !== optimisticMsgId));
      }
      // SSE dropped but server likely still processed the message.
      // Refetch messages after a short delay so the response appears.
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
      }, 2000);
    },
    onComplete: () => {
      if (channelId) {
        // Flush any pending text for this channel
        if (pendingTextRef.current[channelId] || pendingThinkRef.current[channelId]) {
          cancelAnimationFrame(rafRef.current[channelId] || 0);
          flushChannel(channelId);
        }
        // Only finishStreaming if we're still the local stream.
        // If a member bot's stream_start already arrived (via useChannelEvents),
        // isLocalStream was cleared and we're now observing — don't interrupt that.
        const ch = useChatStore.getState().getChannel(channelId);
        if (ch.isLocalStream) {
          finishStreaming(channelId);
        }
      }
      // Refetch messages to get real DB records (with attachments, full metadata, etc.)
      // persist_turn runs before the SSE connection closes, so data is ready.
      queryClient.invalidateQueries({ queryKey: ["session-messages"] });

      // Auto-send queued message now that the stream is done
      const queued = queuedRequestRef.current;
      if (queued) {
        queuedRequestRef.current = null;
        setIsQueued(false);
        setTimeout(() => {
          startStreaming(queued.channelId);
          lastRequestRef.current[queued.channelId] = queued.request;
          chatStream.mutate(queued.request);
        }, 50);
      }
    },
  });

  const handleCancel = useCallback(() => {
    if (!channel || !channelId) return;
    // Send server-side cancel (sets flag + cancels queued tasks)
    cancelChat.mutate({
      client_id: channel.client_id ?? "",
      bot_id: channel.bot_id,
    });
    // Abort local SSE for THIS channel immediately so UI is responsive
    chatStream.abort(channelId);
    // Flush pending RAF deltas so partial content isn't lost
    if (pendingTextRef.current[channelId] || pendingThinkRef.current[channelId]) {
      cancelAnimationFrame(rafRef.current[channelId] || 0);
      flushChannel(channelId);
    }
    // Materialize partial streaming content as a message, then clear streaming state
    finishStreaming(channelId);
    // Also clear any background processing state
    clearProcessing(channelId);
    // Refetch messages to replace synthetic messages with clean DB data
    queryClient.invalidateQueries({ queryKey: ["session-messages"] });

    // If there's a queued message, fire it now (user stopped the stream,
    // so the queue should proceed immediately)
    const queued = queuedRequestRef.current;
    if (queued) {
      queuedRequestRef.current = null;
      setIsQueued(false);
      setTimeout(() => {
        startStreaming(queued.channelId);
        lastRequestRef.current[queued.channelId] = queued.request;
        chatStream.mutate(queued.request);
      }, 100);
    }
  }, [channel, channelId, flushChannel, finishStreaming, clearProcessing, queryClient, startStreaming]);

  const handleRetry = useCallback(() => {
    const req = channelId ? lastRequestRef.current[channelId] : undefined;
    if (!channelId || !req) return;
    setError(channelId, "");
    startStreaming(channelId);
    chatStream.mutate(req);
  }, [channelId, setError, startStreaming]);

  const doSend = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;

      // If viewing a file in non-split mode, auto-enable split so the user sees the response
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

      startStreaming(channelId);

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
      chatStream.mutate(request);

      setTurnModelOverride(undefined);
      setTurnProviderIdOverride(undefined);
    },
    [channelId, channel, activeFile, turnModelOverride, turnProviderIdOverride]
  );

  /** Queue a message to send after the current stream/processing finishes. */
  const queueMessage = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;

      // If viewing a file in non-split mode, auto-enable split
      if (activeFile && !useUIStore.getState().fileExplorerSplit) {
        useUIStore.getState().toggleFileExplorerSplit();
      }

      // If replacing an existing queued message, remove the old optimistic message
      if (queuedRequestRef.current) {
        const oldId = queuedRequestRef.current.optimisticMsgId;
        const oldCh = queuedRequestRef.current.channelId;
        const msgs = useChatStore.getState().channels[oldCh]?.messages ?? [];
        setMessages(oldCh, msgs.filter((m) => m.id !== oldId));
      }

      // Add optimistic user message
      const msgId = `msg-${Date.now()}`;
      addMessage(channelId, {
        id: msgId,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      });

      // Build and store the request for later
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

      // Pre-flight secret check -- fail-open on error
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
    [channelId, channel, doSend, queueMessage]
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

      startStreaming(channelId);

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
      chatStream.mutate(request);

      setTurnModelOverride(undefined);
      setTurnProviderIdOverride(undefined);
    },
    [channelId, channel, activeFile, turnModelOverride, turnProviderIdOverride]
  );

  /** Cancel + send immediately (bypasses queue). */
  const handleSendNow = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;
      // Clear any pending queue
      queuedRequestRef.current = null;
      setIsQueued(false);
      // Cancel current stream, then send
      handleCancel();
      // doSend adds message + starts new stream after cancel settles
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
    // Remove the optimistic user message
    const msgs = useChatStore.getState().channels[qCh]?.messages ?? [];
    setMessages(qCh, msgs.filter((m) => m.id !== optimisticMsgId));
  }, [setMessages]);

  // Reset queue when channel changes
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
