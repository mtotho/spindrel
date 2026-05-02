import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useChatStore } from "@/src/stores/chat";
import { useShallow } from "zustand/react/shallow";
import { useUIStore } from "@/src/stores/ui";
import { useSubmitChat, useCancelChat, useSessionStatus } from "@/src/api/hooks/useChat";
import { useChannelEvents } from "@/src/api/hooks/useChannelEvents";
import { useChannelState } from "@/src/api/hooks/useChannelState";
import { useUpdateChannelSettings } from "@/src/api/hooks/useChannels";
import { useModelGroups } from "@/src/api/hooks/useModels";
import { useSlashCommandList } from "@/src/api/hooks/useSlashCommands";
import { useSecretCheck, type SecretCheckResult } from "@/src/api/hooks/useSecretCheck";
import { apiFetch } from "@/src/api/client";
import { extractDisplayText } from "@/src/components/chat/MessageBubble";
import type { PendingFile } from "@/src/components/chat/MessageInput";
import { resolveProviderForModel } from "@/src/components/chat/slashArgSources";
import { resolveAvailableSlashCommandIds } from "@/src/components/chat/slashCommandSurfaces";
import type { ChatAttachment, ChatFileMetadata, ChatRequest, Message } from "@/src/types/api";
import { useSlashCommandExecutor } from "@/src/components/chat/useSlashCommandExecutor";
import { applyChatStyleSideEffect } from "@/src/components/chat/slashStyleSideEffects";
import { useThemeStore } from "@/src/stores/theme";
import { isHarnessQuestionTransportMessage } from "@/src/components/chat/harnessQuestionMessages";
import { buildChatCancelRequest } from "@/src/components/chat/chatCancelRequest";
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
  onOpenSessions?: () => void;
  onOpenSessionSplit?: () => void;
  enabled?: boolean;
}

export interface UseChannelChatReturn {
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
  handleSlashCommand: (id: string, args?: string[]) => Promise<void>;
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
  queuedMessageText: string | null;
  /** Cancel + send immediately (interrupts current response) */
  handleSendNow: (text: string, files?: PendingFile[]) => void;
  /** Cancel queued message without sending */
  cancelQueue: () => void;
  /** Recall queued message into the composer for editing */
  editQueue: () => { text: string; files?: PendingFile[] } | null;
}

type PreparedChatSend = {
  request: ChatRequest;
  channelId: string;
  optimisticMsgId: string;
  clientLocalId: string;
  text: string;
  files?: PendingFile[];
};

type WorkspaceUploadMetadata = {
  filename: string;
  mime_type: string;
  size_bytes: number;
  path: string;
};

function makeClientLocalId(): string {
  const cryptoObj = globalThis.crypto as Crypto | undefined;
  if (cryptoObj?.randomUUID) return `web-${cryptoObj.randomUUID()}`;
  return `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function useChannelChat({
  channelId,
  channel,
  activeFile,
  onOpenSessions,
  onOpenSessionSplit,
  enabled = true,
}: UseChannelChatOptions): UseChannelChatReturn {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // Narrow shallow-equality subscription: re-renders only when `messages`
  // reference, `isProcessing`, or `turnsCount` change — i.e., turn boundaries
  // and DB sync, NOT the per-token text_delta churn that mutates
  // `turns[*].streamingContent`. The streaming-text subtree subscribes
  // separately via `<ChatStreamingArea>` so it doesn't bubble re-renders up
  // through this hook into the parent.
  const { messages, isProcessing, turnsCount } = useChatStore(
    useShallow((s) => {
      const c = s.getChannel(channelId!);
      return {
        messages: c.messages,
        isProcessing: c.isProcessing,
        turnsCount: Object.keys(c.turns).length,
      };
    }),
  );
  const setMessages = useChatStore((s) => s.setMessages);
  const addMessage = useChatStore((s) => s.addMessage);
  const clearProcessing = useChatStore((s) => s.clearProcessing);
  const setError = useChatStore((s) => s.setError);

  // Snapshot-seed the chat store with in-flight turns BEFORE the SSE stream
  // starts delivering deltas. The snapshot + SSE together replace the 256-
  // event replay buffer: refresh, mobile tab-wake, or background approvals
  // all show up inline instead of dropping to the ApprovalToast fallback.
  const activeChannelId = enabled ? channelId : undefined;

  useChannelState(activeChannelId, channel?.bot_id);

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
  useChannelEvents(activeChannelId, channel?.bot_id, {
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
    clientLocalId: string;
    text: string;
    files?: PendingFile[];
  } | null>(null);
  const [isQueued, setIsQueued] = useState(false);
  const [queuedMessageText, setQueuedMessageText] = useState<string | null>(null);
  // Ref for checking active state inside async callbacks (avoids stale closures).
  const isActiveRef = useRef(false);
  isActiveRef.current = turnsCount > 0 || isProcessing;

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
    enabled: enabled && !!channel?.active_session_id,
  });

  // Sync DB messages into the chat store when new page data arrives.
  // Suppressed while a turn is streaming so we don't clobber the synthetic
  // streamingContent message before it's materialized — EXCEPT on initial
  // load (empty store), because opening a channel mid-turn gets rehydrated
  // turns from the /state snapshot before the message page lands, and
  // skipping the sync there leaves the UI stuck on "Send a message to
  // start the conversation" until the turn finishes.
  useEffect(() => {
    if (!enabled) return;
    const storeEmpty = (messages?.length ?? 0) === 0;
    const canSync = turnsCount === 0 && !isProcessing;
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
          if (isHarnessQuestionTransportMessage(m)) return false;
          if (
            m.role === "assistant"
            && !extractDisplayText(m.content)
            && (!m.attachments || m.attachments.length === 0)
            && !meta.tool_results
            && (!m.tool_calls || m.tool_calls.length === 0)
            && !meta.assistant_turn_body
            && !meta.transcript_entries
          ) return false;
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
  const { data: sessionStatus } = useSessionStatus(channelId, enabled && isProcessing);

  const submitChat = useSubmitChat();
  const cancelChat = useCancelChat();
  const lastRequestRef = useRef<Record<string, ChatRequest>>({});

  const removeOptimisticMessage = useCallback((targetChannelId: string, optimisticMsgId: string) => {
    const msgs = useChatStore.getState().channels[targetChannelId]?.messages ?? [];
    setMessages(targetChannelId, msgs.filter((m) => m.id !== optimisticMsgId));
  }, [setMessages]);

  const submitPrepared = useCallback((prepared: PreparedChatSend) => {
    lastRequestRef.current[prepared.channelId] = prepared.request;
    submitChat.mutate(prepared.request, {
      onSuccess: (result) => {
        if (result.queued && result.task_id) {
          useChatStore.getState().setProcessing(prepared.channelId, result.task_id);
        }
      },
      onError: (err) => {
        removeOptimisticMessage(prepared.channelId, prepared.optimisticMsgId);
        setError(prepared.channelId, err instanceof Error ? err.message : "Failed to send message");
      },
    });
  }, [removeOptimisticMessage, setError, submitChat]);

  // ---- Bus-driven queue advance ----
  // When the channel's turn count drops to zero AND there's a queued
  // request, fire it. This replaces the legacy `chatStream.onComplete`
  // callback hook.
  const prevTurnsCountRef = useRef(turnsCount);
  useEffect(() => {
    const wasActive = prevTurnsCountRef.current > 0;
    const nowIdle = turnsCount === 0 && !isProcessing;
    prevTurnsCountRef.current = turnsCount;

    if (wasActive && nowIdle && queuedRequestRef.current) {
      const queued = queuedRequestRef.current;
      queuedRequestRef.current = null;
      setIsQueued(false);
      setQueuedMessageText(null);
      submitPrepared(queued);
    }
  }, [turnsCount, isProcessing, submitPrepared]);

  // When background processing completes, clear state and refetch.
  useEffect(() => {
    if (
      isProcessing &&
      sessionStatus &&
      !sessionStatus.processing &&
      sessionStatus.pending_tasks === 0
    ) {
      if (channelId) clearProcessing(channelId);
      queryClient.invalidateQueries({ queryKey: ["session-messages"] });
    }
  }, [isProcessing, sessionStatus, channelId, clearProcessing, queryClient]);

  const syncCancelledState = useCallback(() => {
    if (!channelId) return;
    const ch = useChatStore.getState().getChannel(channelId);
    for (const turnId of Object.keys(ch.turns)) {
      useChatStore.getState().handleTurnEvent(channelId, turnId, {
        event: "error",
        data: { message: "cancelled" },
      });
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
    cancelChat.mutate(buildChatCancelRequest({
      clientId: channel.client_id,
      botId: channel.bot_id,
      channelId,
      sessionId: channel.active_session_id,
    }));
    // Local fast-path cleanup so the UI flips back to idle immediately
    // even before the bus event arrives.
    syncCancelledState();

    // If there's a queued message, fire it now.
    const queued = queuedRequestRef.current;
    if (queued) {
      queuedRequestRef.current = null;
      setIsQueued(false);
      setQueuedMessageText(null);
      setTimeout(() => {
        submitPrepared(queued);
      }, 100);
    }
  }, [channel, channelId, cancelChat, submitPrepared, syncCancelledState]);

  const handleRetry = useCallback(() => {
    const req = channelId ? lastRequestRef.current[channelId] : undefined;
    if (!channelId || !req) return;
    setError(channelId, "");
    submitChat.mutate(req);
  }, [channelId, setError, submitChat]);

  const prepareSend = useCallback(
    (text: string, files?: PendingFile[]): PreparedChatSend | null => {
      if (!channelId || !channel) return null;
      if (!enabled) return null;

      // If viewing a file in non-split mode, auto-enable split.
      if (activeFile && !useUIStore.getState().fileExplorerSplit) {
        useUIStore.getState().toggleFileExplorerSplit();
      }

      const workspaceUploads: WorkspaceUploadMetadata[] = [];
      const localAttachments = (files ?? []).map((pf) => {
        if (pf.route === "channel_data" && pf.upload?.path) {
          workspaceUploads.push({
            filename: pf.file.name,
            mime_type: pf.file.type || "application/octet-stream",
            size_bytes: pf.file.size,
            path: pf.upload.path,
          });
        }
        const previewUrl = pf.route === "inline_image" && pf.file.type.startsWith("image/") && pf.base64
          ? `data:${pf.file.type || "image/png"};base64,${pf.base64}`
          : pf.route === "channel_data"
            ? pf.preview
            : pf.preview;
        return {
          id: pf.id,
          filename: pf.file.name,
          mime_type: pf.file.type || "application/octet-stream",
          size_bytes: pf.file.size,
          route: pf.route,
          preview_url: previewUrl,
          path: pf.upload?.path,
        };
      });
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
          ...(localAttachments.length ? { local_attachments: localAttachments } : {}),
          ...(workspaceUploads.length ? { workspace_uploads: workspaceUploads } : {}),
        },
      });

      let attachments: ChatAttachment[] | undefined;
      let file_metadata: ChatFileMetadata[] | undefined;
      if (files && files.length > 0) {
        attachments = [];
        file_metadata = [];
        for (const pf of files) {
          if (pf.route === "inline_image" && pf.file.type.startsWith("image/") && pf.base64) {
            attachments.push({
              type: "image",
              content: pf.base64,
              mime_type: pf.file.type,
              name: pf.file.name,
            });
            file_metadata.push({
              filename: pf.file.name,
              mime_type: pf.file.type,
              size_bytes: pf.file.size,
              file_data: pf.base64,
            });
          }
        }
      }

      const request: ChatRequest = {
        message: text,
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
        msg_metadata: {
          source: "web",
          sender_type: "human",
          client_local_id: clientLocalId,
          ...(workspaceUploads.length ? { workspace_uploads: workspaceUploads } : {}),
        },
        ...(attachments?.length ? { attachments } : {}),
        ...(file_metadata?.length ? { file_metadata } : {}),
      };
      return {
        request,
        channelId,
        optimisticMsgId,
        clientLocalId,
        text,
        ...(files ? { files } : {}),
      };
    },
    [channelId, channel, activeFile, addMessage, enabled]
  );

  const doSend = useCallback(
    (text: string, files?: PendingFile[]) => {
      const prepared = prepareSend(text, files);
      if (!prepared) return;
      submitPrepared(prepared);
    },
    [prepareSend, submitPrepared]
  );

  const handleSend = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;
      if (!enabled) return;
      const prepared = prepareSend(text, files);
      if (!prepared) return;

      secretCheck.mutate(text, {
        onSuccess: (result) => {
          if (result.has_secrets) {
            removeOptimisticMessage(prepared.channelId, prepared.optimisticMsgId);
            setSecretWarning({ result, text, files });
          } else if (isActiveRef.current) {
            if (queuedRequestRef.current) {
              removeOptimisticMessage(queuedRequestRef.current.channelId, queuedRequestRef.current.optimisticMsgId);
            }
            const msgs = useChatStore.getState().channels[prepared.channelId]?.messages ?? [];
            setMessages(prepared.channelId, msgs.map((m) => (
              m.id === prepared.optimisticMsgId
                ? { ...m, metadata: { ...(m.metadata ?? {}), local_status: "queued" } }
                : m
            )));
            queuedRequestRef.current = prepared;
            setIsQueued(true);
            setQueuedMessageText(text);
          } else {
            submitPrepared(prepared);
          }
        },
        onError: () => {
          if (isActiveRef.current) {
            if (queuedRequestRef.current) {
              removeOptimisticMessage(queuedRequestRef.current.channelId, queuedRequestRef.current.optimisticMsgId);
            }
            const msgs = useChatStore.getState().channels[prepared.channelId]?.messages ?? [];
            setMessages(prepared.channelId, msgs.map((m) => (
              m.id === prepared.optimisticMsgId
                ? { ...m, metadata: { ...(m.metadata ?? {}), local_status: "queued" } }
                : m
            )));
            queuedRequestRef.current = prepared;
            setIsQueued(true);
            setQueuedMessageText(text);
          } else {
            submitPrepared(prepared);
          }
        },
      });
    },
    [channelId, channel, enabled, prepareSend, removeOptimisticMessage, secretCheck, setMessages, submitPrepared]
  );

  const handleSendAudio = useCallback(
    (audioBase64: string, audioFormat: string, message?: string) => {
      if (!channelId || !channel) return;
      if (!enabled) return;

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
    [channelId, channel, activeFile, addMessage, enabled, submitChat]
  );

  /** Cancel + send immediately (bypasses queue). */
  const handleSendNow = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;
      if (!enabled) return;
      queuedRequestRef.current = null;
      setIsQueued(false);
      setQueuedMessageText(null);
      handleCancel();
      setTimeout(() => doSend(text, files), 50);
    },
    [channelId, channel, enabled, handleCancel, doSend],
  );

  /** Cancel the queued message (remove optimistic message, keep current stream running). */
  const cancelQueue = useCallback(() => {
    if (!queuedRequestRef.current) return;
    const { optimisticMsgId, channelId: qCh } = queuedRequestRef.current;
    queuedRequestRef.current = null;
    setIsQueued(false);
    setQueuedMessageText(null);
    removeOptimisticMessage(qCh, optimisticMsgId);
  }, [removeOptimisticMessage]);

  const editQueue = useCallback(() => {
    if (!queuedRequestRef.current) return null;
    const queued = queuedRequestRef.current;
    queuedRequestRef.current = null;
    setIsQueued(false);
    setQueuedMessageText(null);
    removeOptimisticMessage(queued.channelId, queued.optimisticMsgId);
    return { text: queued.text, files: queued.files };
  }, [removeOptimisticMessage]);

  // Reset queue when channel changes.
  useEffect(() => {
    queuedRequestRef.current = null;
    setIsQueued(false);
    setQueuedMessageText(null);
  }, [channelId]);

  // Phase 4: pass bot_id so the catalog is intersected with the harness
  // runtime's slash policy server-side. Non-harness bots return the full
  // catalog unchanged.
  const slashCatalog = useSlashCommandList(
    channel?.bot_id,
    channel?.active_session_id ?? undefined,
  );
  const { data: modelGroups } = useModelGroups();
  const availableSlashCommandIds = useMemo(
    () => resolveAvailableSlashCommandIds({
      catalog: slashCatalog,
      surface: "channel",
      enabled: enabled && !!channelId,
      capabilities: ["clear", "new", "scratch", "model", "theme", "sessions", "split", "focus"],
    }),
    [channelId, enabled, slashCatalog],
  );

  const slashLocalHandlers = useMemo(
    () => ({
      clear: async () => {
        if (!channelId) return;
        try {
          const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${channelId}/sessions`, { method: "POST" });
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          queryClient.invalidateQueries({ queryKey: ["channel", channelId] });
          navigate(`/channels/${channelId}/session/${result.new_session_id}`);
        } catch (err) {
          console.error("Failed to create session:", err);
        }
      },
      new: async () => {
        if (!channelId) return;
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${channelId}/sessions`, { method: "POST" });
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        queryClient.invalidateQueries({ queryKey: ["channel", channelId] });
        navigate(`/channels/${channelId}/session/${result.new_session_id}`);
      },
      scratch: async () => {
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
      model: async (args: string[]) => {
        if (!channelId) return;
        // No-args path: open the composer's model picker. For harness bots
        // it shows the runtime's model list (sourced from
        // /runtimes/{name}/capabilities); for normal bots it shows the
        // provider catalog. Both write through the right path on selection.
        if (!args[0]) {
          window.dispatchEvent(
            new CustomEvent("spindrel:open-model-picker", { detail: { channelId } }),
          );
          return;
        }
        // Args path for non-harness bots: write channel.model_override.
        // (Harness path with args is handled server-side by the slash handler
        // which writes to harness_settings.model.)
        if (channel?.bot_id) {
          // For harness bots the server-side handler did the write already.
          // Fall through only for non-harness.
        }
        const modelId = args[0];
        const providerId = resolveProviderForModel(modelId, modelGroups);
        await updateChannelSettings.mutateAsync({
          model_override: modelId,
          model_provider_id_override: providerId ?? undefined,
        });
      },
      theme: (args: string[]) => {
        const arg = args[0]?.toLowerCase();
        const store = useThemeStore.getState();
        if (arg === "light" || arg === "dark") {
          store.setMode(arg);
        } else {
          store.toggle();
        }
      },
      sessions: () => {
        onOpenSessions?.();
      },
      split: () => {
        onOpenSessionSplit?.();
      },
      focus: () => {
        window.dispatchEvent(new CustomEvent("spindrel:channel-focus-layout"));
      },
    }),
    [channelId, channel?.bot_id, modelGroups, navigate, onOpenSessionSplit, onOpenSessions, queryClient, setMessages, updateChannelSettings],
  );

  const handleSlashCommand = useSlashCommandExecutor({
    availableCommands: availableSlashCommandIds,
    catalog: slashCatalog,
    surface: "channel",
    channelId: channelId ?? undefined,
    sessionId: channel?.active_session_id ?? undefined,
    onSyntheticMessage: (message) => {
      if (!channelId) return;
      addMessage(channelId, message);
    },
    localHandlers: slashLocalHandlers,
    onSideEffect: async (result) => {
      if (!channelId) return;
      if (result.command_id === "stop") {
        syncCancelledState();
        return;
      }
      if (result.command_id === "compact") {
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        return;
      }
      if (result.command_id === "plan") {
        queryClient.invalidateQueries({ queryKey: ["session-plan", channel?.active_session_id ?? undefined] });
      }
      if (result.command_id === "style" || result.command_id === "rename") {
        if (result.command_id === "style") {
          applyChatStyleSideEffect(queryClient, channelId, result);
        } else {
          queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
          queryClient.invalidateQueries({ queryKey: ["channels"] });
        }
      }
    },
  });

  // Reverse for inverted FlatList
  const invertedData = useMemo(
    () => [...messages].reverse(),
    [messages],
  );

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      return fetchNextPage();
    }
    return undefined;
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
    queuedMessageText,
    handleSendNow,
    cancelQueue,
    editQueue,
  };
}
