import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useBots, useBot } from "@/src/api/hooks/useBots";
import { useCancelChat, useSubmitChat } from "@/src/api/hooks/useChat";
import { apiFetch } from "@/src/api/client";
import { useQueryClient } from "@tanstack/react-query";
import {
  useSpawnEphemeralSession,
  loadEphemeralState,
  saveEphemeralState,
  clearEphemeralState,
  type StoredEphemeralState,
} from "@/src/api/hooks/useEphemeralSession";
import {
  useResetScratchSession,
  useScratchHistory,
  useScratchSession,
} from "@/src/api/hooks/useChannelSessions";
import { useSessionConfigOverhead } from "@/src/api/hooks/useSessionConfigOverhead";
import { useSessionHeaderStats } from "@/src/api/hooks/useSessionHeaderStats";
import { useSpawnThread, useThreadInfo } from "@/src/api/hooks/useThreads";
import { ThreadParentAnchor } from "./ThreadParentAnchor";
import { useChannel, useChannelConfigOverhead } from "@/src/api/hooks/useChannels";
import { useChannelChatSource } from "@/src/api/hooks/useChannelChatSource";
import { selectIsStreaming, useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { ChatSessionModal } from "./ChatSessionModal";
import { ChatSessionDock } from "./ChatSessionDock";
import { SessionChatView } from "./SessionChatView";
import { useSessionResumeCard } from "./useSessionResumeCard";
import { ChatComposerShell } from "./ChatComposerShell";
import { MessageInput, type PendingFile } from "./MessageInput";
import { buildChatAttachmentPayload } from "./chatAttachmentPayload";
import { useHarnessComposerProps } from "./useHarnessComposerProps";
import { ChatMessageArea, DateSeparator } from "./ChatMessageArea";
import { MessageBubble } from "./MessageBubble";
import { TaskRunEnvelope } from "./TaskRunEnvelope";
import { TriggerCard, SUPPORTED_TRIGGERS } from "./TriggerCard";
import {
  formatDateSeparator,
  isDifferentDay,
  shouldGroup,
  getTurnMessages,
  getTurnText,
} from "@/app/(app)/channels/[channelId]/chatUtils";
import { useThemeTokens } from "@/src/theme/tokens";
import { History, Maximize2, Minimize2, RotateCcw, Rows3, X } from "lucide-react";
import { ScratchHistoryModal } from "./ScratchHistoryModal";
import type { Message } from "@/src/types/api";
import { buildThreadParentPreviewRow } from "./threadPreview";
import { useSlashCommandExecutor } from "./useSlashCommandExecutor";
import { applyChatStyleSideEffect } from "./slashStyleSideEffects";
import { useSlashCommandList } from "@/src/api/hooks/useSlashCommands";
import { useModelGroups } from "@/src/api/hooks/useModels";
import { resolveProviderForModel } from "./slashArgSources";
import { resolveAvailableSlashCommandIds } from "./slashCommandSurfaces";
import { useThemeStore } from "@/src/stores/theme";
import { useSessionPlanMode } from "@/app/(app)/channels/[channelId]/useSessionPlanMode";
import { buildRecentHref, formatSessionRecentLabel } from "@/src/lib/recentPages";
import { isTranscriptFlowComposer } from "./chatModes";

import type { ChatSessionProps, ChatSource } from "./ChatSessionTypes";
import { getDockStorageKey } from "./ChatSessionTypes";
import { makeClientLocalId, formatSessionHeaderTimestamp, formatHeaderTurnMeta, useChatSessionPlan } from "./ChatSessionShared";

// ---------------------------------------------------------------------------
// Thread-mode — session pre-spawned via POST /messages/{id}/thread.
// Streaming rides the parent channel's SSE with session-id filter (same
// path as the pipeline run modal). No bot picker: threads run as the
// inherited bot. Maximize deep-links into the full-screen thread route.
// ---------------------------------------------------------------------------

interface ThreadChatSessionProps extends Omit<ChatSessionProps, "source"> {
  source: Extract<ChatSource, { kind: "thread" }>;
}

export function ThreadChatSession({
  source,
  shape,
  open,
  onClose,
  title,
  emptyState,
  initiallyExpanded,
  dismissMode,
  onOpenSessions,
  onOpenSessionSplit,
  onToggleFocusLayout,
  chatMode = "default",
}: ThreadChatSessionProps) {
  const t = useThemeTokens();
  const composerInTranscriptFlow = isTranscriptFlowComposer(chatMode);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { parentChannelId, botId, parentMessageId, onSessionSpawned } = source;
  const { data: bot } = useBot(botId);
  const { data: threadModelGroups } = useModelGroups();

  // Lazy spawn — thread session is NOT persisted until the user sends their
  // first message. This state holds the id once spawn resolves so later
  // renders can use it even before the parent lifts it into source via
  // onSessionSpawned.
  const [lazySpawnedId, setLazySpawnedId] = useState<string | null>(null);
  const effectiveSessionId = source.threadSessionId ?? lazySpawnedId;
  const hasSession = !!effectiveSessionId;
  const harnessComposerProps = useHarnessComposerProps(bot, effectiveSessionId);

  const [mode, setMode] = useState<"dock" | "modal" | "fullpage">(shape);
  const [dockExpanded, setDockExpanded] = useState(
    shape === "dock" && (initiallyExpanded ?? false),
  );
  // Mirror EphemeralChatSession: no-FAB docks need dockExpanded re-synced
  // to `open` so the dock is reachable again after scrim/Escape/X dismissal.
  useEffect(() => {
    if (open && dismissMode !== "collapse") setDockExpanded(true);
  }, [open, dismissMode]);

  const submitChat = useSubmitChat();
  const spawnThread = useSpawnThread();
  const [sendError, setSendError] = useState<string | null>(null);
  const [modelOverride, setModelOverride] = useState<string | undefined>(undefined);
  const [modelProviderId, setModelProviderId] = useState<string | null>(null);
  // Chat store slot keyed by effective session id once known. Before the
  // lazy spawn fires we use a sentinel key that no SSE subscriber writes
  // to, so the pending state stays visually empty.
  const storeKey = effectiveSessionId ?? "__thread_pending__";
  const chatState = useChatStore((s) => s.getChannel(storeKey));
  const turnActive = selectIsStreaming(chatState);
  const isSending = submitChat.isPending || spawnThread.isPending || turnActive;

  const { data: overheadData } = useSessionConfigOverhead(
    effectiveSessionId ?? undefined,
  );
  const overheadPct = overheadData?.overhead_pct ?? null;
  const { sessionPlan, planBusy, handleTogglePlanMode } = useChatSessionPlan(effectiveSessionId);

  // Live thread info for the parent-anchor bubble when we don't already have
  // the parent Message in hand (direct-link navigation, existing thread
  // reopened from summaries). Source can also supply the Message inline when
  // the caller has it cheaply (pending-state path).
  const { data: threadInfo } = useThreadInfo(effectiveSessionId ?? undefined);
  const parentForAnchor: Message | null =
    (source.parentMessage ?? null) || threadInfo?.parent_message || null;
  const syntheticMessages = useMemo(
    () => [buildThreadParentPreviewRow(storeKey, parentForAnchor)],
    [storeKey, parentForAnchor],
  );
  const [slashSyntheticMessages, setSlashSyntheticMessages] = useState<Message[]>([]);
  const syncThreadCancelledState = useCallback(() => {
    if (!effectiveSessionId) return;
    const ch = useChatStore.getState().getChannel(storeKey);
    for (const turnId of Object.keys(ch.turns)) {
      useChatStore.getState().handleTurnEvent(storeKey, turnId, {
        event: "error",
        data: { message: "cancelled" },
      });
      useChatStore.getState().finishTurn(storeKey, turnId);
    }
    useChatStore.getState().clearProcessing(storeKey);
    qc.invalidateQueries({ queryKey: ["session-messages", effectiveSessionId] });
  }, [effectiveSessionId, qc, storeKey]);
  const threadSlashCatalog = useSlashCommandList(botId || undefined, effectiveSessionId);
  const threadAvailableSlashCommands = useMemo(
    () => resolveAvailableSlashCommandIds({
      catalog: threadSlashCatalog,
      surface: "session",
      enabled: !!effectiveSessionId,
      capabilities: onOpenSessions
        ? ["clear", "new", "model", "theme", "sessions", "split", "focus"]
        : ["clear", "new", "model", "theme"],
    }),
    [effectiveSessionId, onOpenSessions, threadSlashCatalog],
  );
  const threadSlashLocalHandlers = useMemo(
    () => ({
      clear: async () => {
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${parentChannelId}/sessions`, { method: "POST" });
        qc.invalidateQueries({ queryKey: ["session-messages"] });
        navigate(`/channels/${parentChannelId}/session/${result.new_session_id}`);
      },
      new: async () => {
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${parentChannelId}/sessions`, { method: "POST" });
        qc.invalidateQueries({ queryKey: ["session-messages"] });
        navigate(`/channels/${parentChannelId}/session/${result.new_session_id}`);
      },
      model: (args: string[]) => {
        if (!args[0]) return;
        const providerId = resolveProviderForModel(args[0], threadModelGroups);
        setModelOverride(args[0]);
        setModelProviderId(providerId ?? null);
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
      sessions: () => onOpenSessions?.(),
      split: () => onOpenSessionSplit?.(),
      focus: () => onToggleFocusLayout?.(),
    }),
    [navigate, onOpenSessionSplit, onOpenSessions, onToggleFocusLayout, parentChannelId, qc, threadModelGroups],
  );
  const handleThreadSlashCommand = useSlashCommandExecutor({
    availableCommands: threadAvailableSlashCommands,
    catalog: threadSlashCatalog,
    surface: "session",
    sessionId: effectiveSessionId ?? undefined,
    onSyntheticMessage: (message) => setSlashSyntheticMessages((prev) => [message, ...prev]),
    localHandlers: threadSlashLocalHandlers,
    onSideEffect: async (result) => {
      if (result.command_id === "stop") syncThreadCancelledState();
      if (result.command_id === "compact") {
        qc.invalidateQueries({ queryKey: ["session-messages", effectiveSessionId] });
      }
      if (result.command_id === "style") {
        applyChatStyleSideEffect(qc, parentChannelId, result);
      }
    },
  });

  const handleSend = useCallback(
    async (message: string, files?: PendingFile[]) => {
      setSendError(null);
      let sid = effectiveSessionId;
      try {
        if (!sid) {
          const spawned = await spawnThread.mutateAsync({
            message_id: parentMessageId,
            bot_id: botId,
          });
          sid = spawned.session_id;
          setLazySpawnedId(sid);
          onSessionSpawned?.(sid);
        }
        const clientLocalId = makeClientLocalId();
        const attachmentPayload = buildChatAttachmentPayload(files);
        const workspaceUploads = attachmentPayload.workspace_uploads ?? [];
        useChatStore.getState().addMessage(sid, {
          id: `msg-${clientLocalId}`,
          session_id: sid,
          role: "user",
          content: message,
          created_at: new Date().toISOString(),
          metadata: {
            source: "web",
            sender_type: "human",
            client_local_id: clientLocalId,
            local_status: "sending",
            ...(workspaceUploads.length ? { workspace_uploads: workspaceUploads } : {}),
          },
        });
        await submitChat.mutateAsync({
          message,
          bot_id: botId,
          client_id: "web",
          session_id: sid,
          channel_id: parentChannelId,
          msg_metadata: {
            source: "web",
            sender_type: "human",
            client_local_id: clientLocalId,
            ...(workspaceUploads.length ? { workspace_uploads: workspaceUploads } : {}),
          },
          ...(attachmentPayload.attachments?.length ? { attachments: attachmentPayload.attachments } : {}),
          ...(attachmentPayload.file_metadata?.length ? { file_metadata: attachmentPayload.file_metadata } : {}),
          ...(modelOverride
            ? {
                model_override: modelOverride,
                model_provider_id_override: modelProviderId,
              }
            : {}),
        });
        qc.invalidateQueries({ queryKey: ["session-messages", sid] });
        qc.invalidateQueries({ queryKey: ["thread-summaries"] });
      } catch (err) {
        setSendError(err instanceof Error ? err.message : "Failed to send message");
      }
    },
    [
      botId,
      effectiveSessionId,
      parentChannelId,
      parentMessageId,
      submitChat,
      spawnThread,
      onSessionSpawned,
      modelOverride,
      modelProviderId,
      qc,
    ],
  );

  const handleMaximize = useCallback(() => {
    if (!effectiveSessionId) return;
    navigate(`/channels/${parentChannelId}/threads/${effectiveSessionId}`);
  }, [navigate, parentChannelId, effectiveSessionId]);

  const handleHeaderClose = useCallback(() => {
    if (mode === "dock") setDockExpanded(false);
    else onClose();
  }, [mode, onClose]);

  const overheadColor = useMemo(() => {
    if (overheadPct == null) return null;
    if (overheadPct >= 0.4) return "#ef4444";
    if (overheadPct >= 0.2) return "#eab308";
    return null;
  }, [overheadPct]);

  const displayTitle = title ?? "Thread";
  const ExpandIcon = mode === "dock" ? Maximize2 : Minimize2;
  const inputOverlayRef = useRef<HTMLDivElement | null>(null);
  const [inputOverlayHeight, setInputOverlayHeight] = useState(96);
  useEffect(() => {
    if (!inputOverlayRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height;
      if (h) setInputOverlayHeight(Math.ceil(h));
    });
    ro.observe(inputOverlayRef.current);
    return () => ro.disconnect();
  }, []);

  const header = (
    <div
      className="flex items-center justify-between gap-2 px-3 py-2 shrink-0"
      style={{
        backgroundColor: chatMode === "terminal" ? `${t.overlayLight}2e` : `${t.overlayLight}1a`,
      }}
    >
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className="text-[13px] font-semibold text-text truncate">
          {displayTitle}
        </span>
        {bot?.name && (
          <span
            className="text-[11px] text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay shrink-0 truncate"
            title={bot.name}
          >
            @{bot.name}
          </span>
        )}
      </div>
      <div className="flex items-center gap-0.5 shrink-0">
        {overheadColor && (
          <button
            type="button"
            title={`Context overhead: ${Math.round((overheadPct ?? 0) * 100)}% of the model's window`}
            className="w-2 h-2 rounded-full mx-1"
            style={{ backgroundColor: overheadColor, border: "none", cursor: "help" }}
          />
        )}
        <button
          onClick={handleMaximize}
          disabled={!hasSession}
          title={hasSession ? "Open full-screen thread" : "Send a reply first"}
          aria-label="Open full-screen thread"
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ExpandIcon size={13} />
        </button>
        <button
          onClick={handleHeaderClose}
          title={mode === "dock" ? "Collapse to button" : "Close"}
          aria-label={mode === "dock" ? "Collapse to button" : "Close"}
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
        >
          <X size={13} />
        </button>
      </div>
    </div>
  );

  const body = (
    <div className="flex flex-col h-full">
      {header}
      <div className="flex-1 min-h-0 relative">
        {hasSession ? (
          <SessionChatView
            sessionId={effectiveSessionId!}
            parentChannelId={parentChannelId}
            botId={botId}
            emptyStateComponent={emptyState}
            scrollPaddingBottom={composerInTranscriptFlow ? 20 : inputOverlayHeight + 16}
            syntheticMessages={[...syntheticMessages, ...slashSyntheticMessages]}
            chatMode={chatMode}
            showSessionResumeCard
            sessionResumeSeed={{
              surfaceKind: "thread",
              title: displayTitle,
              botName: bot?.name,
              botModel: bot?.harness_runtime ? null : bot?.model,
            }}
            onOpenSessions={onOpenSessions}
            bottomSlot={composerInTranscriptFlow ? (
              <>
                {sendError && (
                  <div className="px-4 py-1.5 text-[11px] text-red-400 bg-red-500/5">
                    {sendError}
                  </div>
                )}
                <ChatComposerShell chatMode={chatMode}>
                  <MessageInput
                    onSend={handleSend}
                    disabled={!botId}
                    isStreaming={isSending}
                    currentBotId={botId ?? undefined}
                    currentSessionId={effectiveSessionId ?? undefined}
                    channelId={storeKey}
                    onSlashCommand={handleThreadSlashCommand}
                    slashSurface="session"
                    availableSlashCommands={threadAvailableSlashCommands}
                    defaultModel={bot?.model}
                    hideModelOverride={!!bot?.harness_runtime}
                    {...harnessComposerProps}
                    configOverhead={overheadPct}
                    modelOverride={modelOverride}
                    modelProviderIdOverride={modelProviderId}
                    onModelOverrideChange={(m, providerId) => {
                      setModelOverride(m ?? undefined);
                      setModelProviderId(providerId ?? null);
                    }}
                    compact
                    chatMode={chatMode}
                    planMode={sessionPlan.mode}
                    hasPlan={sessionPlan.hasPlan}
                    planBusy={planBusy}
                    canTogglePlanMode={!!effectiveSessionId}
                    onTogglePlanMode={effectiveSessionId ? handleTogglePlanMode : undefined}
                    onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
                  />
                </ChatComposerShell>
              </>
            ) : undefined}
          />
        ) : (
          <ChatMessageArea
            invertedData={syntheticMessages}
            renderMessage={() => (
              <ThreadParentAnchor message={parentForAnchor} inline />
            )}
            chatState={chatState}
            bot={undefined}
            botId={botId}
            isLoading={false}
            isFetchingNextPage={false}
            hasNextPage={false}
            handleLoadMore={() => {}}
            isProcessing={false}
            t={t}
            scrollPaddingBottom={composerInTranscriptFlow ? 20 : inputOverlayHeight + 16}
            chatMode={chatMode}
            sessionId={effectiveSessionId ?? undefined}
            bottomSlot={composerInTranscriptFlow ? (
              <>
                {sendError && (
                  <div className="px-4 py-1.5 text-[11px] text-red-400 bg-red-500/5">
                    {sendError}
                  </div>
                )}
                <ChatComposerShell chatMode={chatMode}>
                  <MessageInput
                    onSend={handleSend}
                    disabled={!botId}
                    isStreaming={isSending}
                    currentBotId={botId ?? undefined}
                    currentSessionId={effectiveSessionId ?? undefined}
                    channelId={storeKey}
                    defaultModel={bot?.model}
                    hideModelOverride={!!bot?.harness_runtime}
                    {...harnessComposerProps}
                    configOverhead={overheadPct}
                    modelOverride={modelOverride}
                    modelProviderIdOverride={modelProviderId}
                    onModelOverrideChange={(m, providerId) => {
                      setModelOverride(m ?? undefined);
                      setModelProviderId(providerId ?? null);
                    }}
                    compact
                    chatMode={chatMode}
                    planMode={sessionPlan.mode}
                    hasPlan={sessionPlan.hasPlan}
                    planBusy={planBusy}
                    canTogglePlanMode={!!effectiveSessionId}
                    onTogglePlanMode={effectiveSessionId ? handleTogglePlanMode : undefined}
                    onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
                  />
                </ChatComposerShell>
              </>
            ) : undefined}
          />
        )}
        {!composerInTranscriptFlow && (
          <div ref={inputOverlayRef} className="absolute bottom-0 left-0 right-0 z-[4]">
            {sendError && (
              <div className="px-4 py-1.5 text-[11px] text-red-400 bg-red-500/5">
                {sendError}
              </div>
            )}
            <ChatComposerShell chatMode={chatMode}>
              <MessageInput
                onSend={handleSend}
                disabled={!botId}
                isStreaming={isSending}
                currentBotId={botId ?? undefined}
                currentSessionId={effectiveSessionId ?? undefined}
                channelId={storeKey}
                onSlashCommand={handleThreadSlashCommand}
                slashSurface="session"
                availableSlashCommands={threadAvailableSlashCommands}
                defaultModel={bot?.model}
                hideModelOverride={!!bot?.harness_runtime}
                {...harnessComposerProps}
                configOverhead={overheadPct}
                modelOverride={modelOverride}
                modelProviderIdOverride={modelProviderId}
                onModelOverrideChange={(m, providerId) => {
                  setModelOverride(m ?? undefined);
                  setModelProviderId(providerId ?? null);
                }}
                compact
                chatMode={chatMode}
                planMode={sessionPlan.mode}
                hasPlan={sessionPlan.hasPlan}
                planBusy={planBusy}
                canTogglePlanMode={!!effectiveSessionId}
                onTogglePlanMode={effectiveSessionId ? handleTogglePlanMode : undefined}
                onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
              />
            </ChatComposerShell>
          </div>
        )}
      </div>
    </div>
  );

  if (mode === "modal") {
    return (
      <ChatSessionModal open={open} onClose={onClose} title={displayTitle}>
        {body}
      </ChatSessionModal>
    );
  }

  return (
    <ChatSessionDock
      open={open}
      expanded={dockExpanded}
      onExpandedChange={setDockExpanded}
      onDismiss={dismissMode === "collapse" ? undefined : onClose}
      title={displayTitle}
      storageKey={getDockStorageKey(source)}
      chatMode={chatMode}
    >
      {body}
    </ChatSessionDock>
  );
}
