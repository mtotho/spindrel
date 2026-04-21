import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { useSubmitChat, useCancelChat, useSessionStatus } from "@/src/api/hooks/useChat";
import { useChannelEvents } from "@/src/api/hooks/useChannelEvents";
import { useChannelState } from "@/src/api/hooks/useChannelState";
import { useUpdateChannelSettings } from "@/src/api/hooks/useChannels";
import { useSecretCheck, type SecretCheckResult } from "@/src/api/hooks/useSecretCheck";
import { apiFetch } from "@/src/api/client";
import { extractDisplayText } from "@/src/components/chat/MessageBubble";
import type { PendingFile } from "@/src/components/chat/MessageInput";
import type { ChatAttachment, ChatFileMetadata, ChatRequest, Message } from "@/src/types/api";
import { useSlashCommandExecutor } from "@/src/components/chat/useSlashCommandExecutor";
import { type MessagePage, PAGE_SIZE } from "./chatUtils";

export interface UseChannelChatOptions {
  channelId: string | undefined;
  channel: {
    active_session_id?: string | null;
    bot_id: string;
    client_id?: string | null;
    model_override?: string | null;
    model_provider_id_override?: string | null;
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
  const navigate = useNavigate();

  const chatState = useChatStore((s) => s.getChannel(channelId!));
  const setMessages = useChatStore((s) => s.setMessages);
  const addMessage = useChatStore((s) => s.addMessage);
  const clearProcessing = useChatStore((s) => s.clearProcessing);
  const setError = useChatStore((s) => s.setError);

  // Snapshot-seed the chat store with in-flight turns BEFORE the SSE stream
  // starts delivering deltas. The snapshot + SSE together replace the 256-
  // event replay buffer: refresh, mobile tab-wake, or background approvals
  // all show up inline instead of dropping to the ApprovalToast fallback.
  useChannelState(channelId, channel?.bot_id);

  // Subscribe to typed channel-events bus events. This is the SOLE source
  // of streaming UI state — POST /chat just acknowledges the turn.
  //
  // The parent-channel view filters events by ``active_session_id``: Phase 1's
  // sub-session bus bridge republishes pipeline-child TURN_STARTED / TURN_ENDED
  // (and step-output NEW_MESSAGE) on the parent channel's bus so the run-view
  // modal can subscribe to the same SSE stream. Without this filter, those
  // bridged events drive the parent channel's chat store and a phantom
  // streaming indicator for the child bot (e.g. orchestrator running an audit
  // pipeline) appears in the channel. Events with ``payload.session_id``
  // undefined (legacy non-sub-session publishes) pass through unchanged.
  useChannelEvents(channelId, channel?.bot_id, {
    sessionFilter: channel?.active_session_id ?? undefined,
  });

  // Model override is persisted on the channel itself. The picker reads the
  // channel's current values and writes back via PATCH /channels/:id/settings.
  // Optimistic cache update keeps the pill responsive while the mutation flies.
  const turnModelOverride = channel?.model_override ?? undefined;
  const turnProviderIdOverride = channel?.model_provider_id_override ?? undefined;
  const updateChannelSettings = useUpdateChannelSettings(channelId ?? "");
  const handleModelOverrideChange = useCallback((m: string | undefined, providerId?: string | null) => {
    if (!channelId) return;
    queryClient.setQueryData<any>(["channels", channelId], (old: any) =>
      old ? { ...old, model_override: m ?? null, model_provider_id_override: m ? (providerId ?? null) : null } : old,
    );
    updateChannelSettings.mutate({
      model_override: m ?? null,
      model_provider_id_override: m ? (providerId ?? null) : null,
    });
  }, [channelId, updateChannelSettings, queryClient]);

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
  // streamingContent message before it's materialized — EXCEPT on initial
  // load (empty store), because opening a channel mid-turn gets rehydrated
  // turns from the /state snapshot before the message page lands, and
  // skipping the sync there leaves the UI stuck on "Send a message to
  // start the conversation" until the turn finishes.
  useEffect(() => {
    const storeEmpty = (chatState.messages?.length ?? 0) === 0;
    const canSync = turnsCount === 0 && !chatState.isProcessing;
    if (channelId && pages && (canSync || storeEmpty)) {
      const allMessages = [...pages.pages].reverse().flatMap((p) => p.messages)
        .filter((m) => {
          const meta = (m as any).metadata ?? {};
          // Task-run envelopes render via a custom card. Keep them regardless
          // of role/content — the renderer pulls everything from metadata.
          if (meta.kind === "task_run") return true;
          if (m.role !== "user" && m.role !== "assistant") return false;
          if (meta.passive && !meta.delegated_by) return false;
          if (m.role === "user" && meta.is_heartbeat) return false;
          if (meta.hidden) return false;
          if (m.role === "assistant" && !extractDisplayText(m.content)
              && (!m.attachments || m.attachments.length === 0)) return false;
          return true;
        });

      // Preserve synthetic messages from finishTurn() only when the DB
      // genuinely doesn't have a corresponding assistant row. Two
      // drop signals, evaluated in order:
      //
      //   1. correlation_id match — happy path. Synthetics currently
      //      have no correlation_id (the field isn't threaded from
      //      turn_started into TurnState), so this rarely fires in
      //      practice; retained as a forward-compat hook.
      //   2. content-prefix match — the authoritative signal. If the
      //      DB has an assistant row whose normalized content starts
      //      with the same first ~120 chars as the synthetic, the DB
      //      row IS the canonical version of it. Prefix tolerance
      //      matters because the persisted row can be a SUPERSET of
      //      the streaming accumulator (multi-chunk assistant text
      //      straddling a tool call — the streaming buffer captured
      //      only the pre-tool prefix, and the DB has the full
      //      concatenation). Immune to clock skew, which is what the
      //      previous strict `m.created_at <= newestDbAssistantTs`
      //      check was broken by: when the browser wall clock is even
      //      a few milliseconds ahead of the server DB commit time,
      //      every synthetic survives indefinitely and the user sees
      //      a permanent duplicate of every bot reply on the web UI.
      //
      // A timestamp-window fallback was considered and rejected: it
      // false-positives on the genuine persist-failure case (send A,
      // bot replies persisted; minutes later send B, bot replies but
      // persist_turn fails → synthetic B must be kept, but a timestamp
      // window centered on the DB's newest assistant would drop it
      // because row A is within the window of B).
      const currentMessages = useChatStore.getState().channels[channelId]?.messages ?? [];
      const dbCorrelationIds = new Set(
        allMessages.map((m) => m.correlation_id).filter(Boolean)
      );

      const CONTENT_PREFIX_LEN = 120;
      const normalizeForPrefix = (raw: unknown): string => {
        if (typeof raw !== "string") return "";
        return extractDisplayText(raw).trim().replace(/\s+/g, "").slice(0, CONTENT_PREFIX_LEN);
      };
      const dbAssistantPrefixes = new Set<string>();
      for (const m of allMessages) {
        if (m.role !== "assistant") continue;
        const p = normalizeForPrefix(m.content);
        if (p) dbAssistantPrefixes.add(p);
      }

      const syntheticToKeep = currentMessages.filter((m) => {
        if (!(m.id.startsWith("turn-") || m.id.startsWith("msg-"))) return false;
        if (m.role !== "assistant") return false;
        // (1) Drop if DB has a row with the same correlation_id.
        if (m.correlation_id && dbCorrelationIds.has(m.correlation_id)) return false;
        // (2) Drop if DB has an assistant row whose content prefix matches.
        const prefix = normalizeForPrefix(m.content);
        if (prefix && dbAssistantPrefixes.has(prefix)) return false;
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

  const syncCancelledState = useCallback(() => {
    if (!channelId) return;
    const ch = useChatStore.getState().getChannel(channelId);
    for (const turnId of Object.keys(ch.turns)) {
      useChatStore.getState().finishTurn(channelId, turnId);
    }
    clearProcessing(channelId);
    queryClient.invalidateQueries({ queryKey: ["session-messages"] });
  }, [channelId, clearProcessing, queryClient]);

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
    syncCancelledState();

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
  }, [channel, channelId, cancelChat, submitChat, syncCancelledState]);

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
        ...(attachments?.length ? { attachments } : {}),
        ...(file_metadata?.length ? { file_metadata } : {}),
      };
      lastRequestRef.current[channelId] = request;
      submitChat.mutate(request);
    },
    [channelId, channel, activeFile, addMessage, submitChat]
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
        ...(attachments?.length ? { attachments } : {}),
        ...(file_metadata?.length ? { file_metadata } : {}),
      };

      queuedRequestRef.current = { request, channelId, optimisticMsgId: msgId };
      setIsQueued(true);
    },
    [channelId, channel, activeFile, addMessage, setMessages],
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
      };
      lastRequestRef.current[channelId] = request;
      submitChat.mutate(request);
    },
    [channelId, channel, activeFile, addMessage, submitChat]
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

  const handleSlashCommand = useSlashCommandExecutor({
    availableCommands: ["stop", "context", "scratch", "clear", "compact"],
    channelId: channelId ?? undefined,
    sessionId: channel?.active_session_id ?? undefined,
    onSyntheticMessage: (message) => {
      if (!channelId) return;
      addMessage(channelId, message);
    },
    onScratch: async () => {
      if (!channelId || !channel?.bot_id) return;
      const qs = new URLSearchParams({
        parent_channel_id: channelId,
        bot_id: channel.bot_id,
      });
      const scratch = await apiFetch<{ session_id: string }>(
        `/sessions/scratch/current?${qs.toString()}`,
      );
      navigate(`/channels/${channelId}/session/${scratch.session_id}?scratch=true`);
    },
    onClear: async () => {
      if (!channelId) return;
      try {
        await apiFetch(`/channels/${channelId}/reset`, { method: "POST" });
        setMessages(channelId, []);
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        queryClient.invalidateQueries({ queryKey: ["channel", channelId] });
      } catch (err) {
        console.error("Failed to reset session:", err);
      }
    },
    onSideEffect: async (result) => {
      if (!channelId) return;
      if (result.command_id === "stop") {
        syncCancelledState();
        return;
      }
      if (result.command_id === "compact") {
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
      }
    },
  });

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
