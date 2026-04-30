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
// Channel-mode
// ---------------------------------------------------------------------------

interface ChannelChatSessionProps extends Omit<ChatSessionProps, "source"> {
  source: Extract<ChatSource, { kind: "channel" }>;
}

export function ChannelChatSession({
  source,
  shape,
  open,
  onClose,
  title,
  emptyState,
  initiallyExpanded,
  dismissMode,
  dockCollapsedTitle,
  dockCollapsedSubtitle,
  onRestoreToCanvas,
  onOpenSessions,
  onOpenSessionSplit,
  onToggleFocusLayout,
  chatMode = "default",
}: ChannelChatSessionProps) {
  const t = useThemeTokens();
  const composerInTranscriptFlow = isTranscriptFlowComposer(chatMode);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const src = useChannelChatSource(source.channelId);
  const addMessage = useChatStore((s) => s.addMessage);
  const { data: bot } = useBot(src.bot_id);
  const harnessComposerProps = useHarnessComposerProps(bot, src.sessionId);
  const { data: overheadData } = useChannelConfigOverhead(source.channelId);
  const overheadPct = overheadData?.overhead_pct ?? null;
  const { sessionPlan, planBusy, handleTogglePlanMode } = useChatSessionPlan(src.sessionId);
  const sessionResumeSlot = useSessionResumeCard({
    sessionId: src.sessionId,
    channelId: source.channelId,
    messages: src.invertedData,
    isActive: Object.keys(src.chatState.turns).length > 0 || !!src.chatState.isProcessing,
    chatMode,
    seed: {
      surfaceKind: "primary",
      title: "Primary session",
      botName: bot?.name,
      botModel: bot?.harness_runtime ? null : bot?.model,
    },
    onOpenSessions,
  });

  // Dock expansion (FAB vs panel); controller owns so header X collapses.
  // Respect the caller's `initiallyExpanded` on mount only — subsequent toggles
  // go through the X button and FAB, not prop updates.
  const [dockExpanded, setDockExpanded] = useState(
    shape === "dock" && (initiallyExpanded ?? false),
  );

  // Composer overlay height — measured via ResizeObserver so the message
  // list's scroll padding matches the real composer height. Mirrors the main
  // channel screen pattern at ui/app/(app)/channels/[channelId]/index.tsx:571.
  const inputOverlayRef = useRef<HTMLDivElement>(null);
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

  // Message-renderer — same rendering primitives as the full channel screen
  // and SessionChatView. No onBotClick / secret warnings / etc. in the dock.
  const latestAnchorByGroup = useMemo(() => {
    const ids = new Set<string>();
    const seen = new Set<string>();
    for (const m of src.invertedData) {
      const meta = (m.metadata ?? {}) as Record<string, any>;
      if (meta.kind !== "task_run") continue;
      const key =
        (meta.parent_task_id as string | null | undefined) ||
        (meta.title as string | null | undefined) ||
        m.id;
      if (!seen.has(key)) {
        seen.add(key);
        ids.add(m.id);
      }
    }
    return ids;
  }, [src.invertedData]);

  const renderMessage = useCallback(
    ({ item, index }: { item: Message; index: number }) => {
      const prevMsg = src.invertedData[index + 1];
      const grouped = shouldGroup(item, prevMsg);
      const showDateSep =
        index === src.invertedData.length - 1 ||
        (prevMsg && isDifferentDay(item.created_at, prevMsg.created_at));
      const dateSep = showDateSep ? (
        <DateSeparator label={formatDateSeparator(item.created_at)} />
      ) : null;
      const meta = (item.metadata ?? {}) as Record<string, any>;
      if (meta.kind === "task_run") {
        const collapsedByDefault = !latestAnchorByGroup.has(item.id);
        return (
          <>
            {dateSep}
            <TaskRunEnvelope message={item} collapsedByDefault={collapsedByDefault} />
          </>
        );
      }
      if (item.role === "user" && meta.trigger && SUPPORTED_TRIGGERS.has(meta.trigger)) {
        return (
          <>
            {dateSep}
            <TriggerCard message={item} botName={bot?.name} />
          </>
        );
      }
      const isGrouped = showDateSep ? false : grouped;
      let headerIdx = index;
      while (
        headerIdx < src.invertedData.length - 1 &&
        shouldGroup(src.invertedData[headerIdx], src.invertedData[headerIdx + 1])
      ) {
        headerIdx++;
      }
      const fullTurnMessages = getTurnMessages(src.invertedData, headerIdx);
      const fullTurnText = getTurnText(src.invertedData, headerIdx);
      const isLatest = item.role === "assistant" && index === 0;
      return (
        <>
          {dateSep}
          <MessageBubble
            message={item}
            botName={bot?.name}
            isGrouped={isGrouped}
            fullTurnText={fullTurnText}
            fullTurnMessages={fullTurnMessages}
            channelId={source.channelId}
            isLatestBotMessage={isLatest}
            compact
            chatMode={chatMode}
          />
        </>
      );
    },
    [src.invertedData, bot?.name, source.channelId, latestAnchorByGroup],
  );

  const handleMaximize = useCallback(() => {
    // Channel-mode maximize → full channel screen. No intermediate modal.
    navigate(`/channels/${source.channelId}`);
  }, [navigate, source.channelId]);

  const handleHeaderClose = useCallback(() => {
    // Full close when:
    //   - the dock has a "restore to canvas" path (the bot/widget tile is
    //     visible elsewhere, no need for a collapsed FAB), or
    //   - the caller passed `dismissMode="close"` to opt out of the
    //     collapse-to-pill default (spatial canvas does this — clicking
    //     a bot reopens its dock fresh, so a leftover pill just creates
    //     "switching" confusion when the user clicks a different bot).
    if (
      shape === "dock" &&
      (onRestoreToCanvas || dismissMode === "close")
    ) {
      onClose();
      return;
    }
    if (shape === "dock") setDockExpanded(false);
    else onClose();
  }, [shape, onClose, onRestoreToCanvas, dismissMode]);

  const { handleSend: srcHandleSend } = src;
  const handleSendMsg = useCallback(
    (message: string, _files?: PendingFile[]) => {
      srcHandleSend(message);
    },
    [srcHandleSend],
  );

  const channelSlashCatalog = useSlashCommandList(src.bot_id, src.sessionId);
  const { data: channelModelGroups } = useModelGroups();
  const channelSlashLocalHandlers = useMemo(
    () => ({
      clear: async () => {
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${source.channelId}/sessions`, { method: "POST" });
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        queryClient.invalidateQueries({ queryKey: ["channel", source.channelId] });
        navigate(`/channels/${source.channelId}/session/${result.new_session_id}`);
      },
      new: async () => {
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${source.channelId}/sessions`, { method: "POST" });
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        queryClient.invalidateQueries({ queryKey: ["channel", source.channelId] });
        navigate(`/channels/${source.channelId}/session/${result.new_session_id}`);
      },
      scratch: async () => {
        if (!src.bot_id) return;
        const qs = new URLSearchParams({
          parent_channel_id: source.channelId,
          bot_id: src.bot_id,
        });
        const scratch = await apiFetch<{ session_id: string }>(
          `/sessions/scratch/current?${qs.toString()}`,
        );
        navigate(`/channels/${source.channelId}/session/${scratch.session_id}?scratch=true`);
      },
      model: (args: string[]) => {
        if (!args[0]) return;
        const providerId = resolveProviderForModel(args[0], channelModelGroups);
        src.setModelOverride(args[0], providerId ?? null);
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
        if (onOpenSessions) onOpenSessions();
        else navigate(`/channels/${source.channelId}`);
      },
      split: () => onOpenSessionSplit?.(),
      focus: () => onToggleFocusLayout?.(),
    }),
    [channelModelGroups, navigate, onOpenSessionSplit, onOpenSessions, onToggleFocusLayout, queryClient, source.channelId, src],
  );

  const channelAvailableSlashCommands = useMemo(
    () => resolveAvailableSlashCommandIds({
      catalog: channelSlashCatalog,
      surface: "channel",
      enabled: !!source.channelId,
      capabilities: ["clear", "new", "scratch", "model", "theme", "sessions", "split", "focus"],
    }),
    [channelSlashCatalog, source.channelId],
  );

  const handleSlashCommand = useSlashCommandExecutor({
    availableCommands: channelAvailableSlashCommands,
    catalog: channelSlashCatalog,
    surface: "channel",
    channelId: source.channelId,
    sessionId: src.sessionId,
    onSyntheticMessage: (message) => addMessage(source.channelId, message),
    localHandlers: channelSlashLocalHandlers,
    onSideEffect: async (result) => {
      if (result.command_id === "stop") {
        src.syncCancelledState();
        return;
      }
      if (result.command_id === "compact") {
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        return;
      }
      if (result.command_id === "plan") return;
      if (result.command_id === "style") {
        applyChatStyleSideEffect(queryClient, source.channelId, result);
        return;
      }
    },
  });

  const overheadColor = useMemo(() => {
    if (overheadPct == null) return null;
    if (overheadPct >= 0.4) return "#ef4444";
    if (overheadPct >= 0.2) return "#eab308";
    return null;
  }, [overheadPct]);

  const displayTitle = title ?? (bot?.name ? `#${bot.name}` : "Channel chat");

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
          title="Open full chat"
          aria-label="Open full chat"
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
        >
          <Maximize2 size={13} />
        </button>
        {onRestoreToCanvas && (
          <button
            onClick={onRestoreToCanvas}
            title="Restore to canvas"
            aria-label="Restore to canvas"
            className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
          >
            <Rows3 size={13} />
          </button>
        )}
        <button
          onClick={handleHeaderClose}
          title={shape === "dock" ? "Collapse to button" : "Close"}
          aria-label={shape === "dock" ? "Collapse to button" : "Close"}
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
        {composerInTranscriptFlow ? (
          <ChatMessageArea
            invertedData={src.invertedData}
            renderMessage={renderMessage}
            chatState={src.chatState}
            bot={bot}
            botId={src.bot_id}
            isLoading={src.isLoading}
            isFetchingNextPage={src.isFetchingNextPage}
            hasNextPage={src.hasNextPage}
            handleLoadMore={src.fetchNextPage}
            isProcessing={src.chatState.isProcessing}
            t={t}
            emptyStateComponent={emptyState}
            scrollPaddingBottom={20}
            chatMode={chatMode}
            channelId={source.channelId}
            sessionResumeSlot={sessionResumeSlot}
            sessionId={src.sessionId}
            bottomSlot={
              <>
                {src.sendError && (
                  <div className="px-4 py-1.5 text-[11px] text-red-400 bg-red-500/5">
                    {src.sendError}
                  </div>
                )}
                <ChatComposerShell chatMode={chatMode}>
                  <MessageInput
                    onSend={handleSendMsg}
                    disabled={!src.bot_id}
                    isStreaming={src.isStreaming}
                    onCancel={src.handleCancel}
                    currentBotId={src.bot_id}
                    currentSessionId={src.sessionId}
                    channelId={source.channelId}
                    onSlashCommand={handleSlashCommand}
                    slashSurface="channel"
                    availableSlashCommands={channelAvailableSlashCommands}
                    modelOverride={src.modelOverride}
                    modelProviderIdOverride={src.modelProviderIdOverride}
                    onModelOverrideChange={src.setModelOverride}
                    defaultModel={bot?.model}
                    hideModelOverride={!!bot?.harness_runtime}
                    {...harnessComposerProps}
                    configOverhead={overheadPct}
                    compact
                    chatMode={chatMode}
                    planMode={sessionPlan.mode}
                    hasPlan={sessionPlan.hasPlan}
                    planBusy={planBusy}
                    canTogglePlanMode={!!src.sessionId}
                    onTogglePlanMode={src.sessionId ? handleTogglePlanMode : undefined}
                    onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
                  />
                </ChatComposerShell>
              </>
            }
          />
        ) : (
        <ChatMessageArea
          invertedData={src.invertedData}
          renderMessage={renderMessage}
          chatState={src.chatState}
          bot={bot}
          botId={src.bot_id}
          isLoading={src.isLoading}
          isFetchingNextPage={src.isFetchingNextPage}
          hasNextPage={src.hasNextPage}
          handleLoadMore={src.fetchNextPage}
          isProcessing={src.chatState.isProcessing}
          t={t}
          emptyStateComponent={emptyState}
          scrollPaddingBottom={inputOverlayHeight + 16}
          chatMode={chatMode}
          channelId={source.channelId}
          sessionResumeSlot={sessionResumeSlot}
          sessionId={src.sessionId}
        />
        )}
        {/* Composer overlay — messages scroll behind the frosted card
            (mirrors the main channel screen pattern). */}
        {!composerInTranscriptFlow && (
          <div
            ref={inputOverlayRef}
            className="absolute bottom-0 left-0 right-0 z-[4]"
          >
            {src.sendError && (
              <div className="px-4 py-1.5 text-[11px] text-red-400 bg-red-500/5">
                {src.sendError}
              </div>
            )}
            <ChatComposerShell chatMode={chatMode}>
              <MessageInput
                onSend={handleSendMsg}
                disabled={!src.bot_id}
                isStreaming={src.isStreaming}
                onCancel={src.handleCancel}
                currentBotId={src.bot_id}
                currentSessionId={src.sessionId}
                channelId={source.channelId}
                onSlashCommand={handleSlashCommand}
                slashSurface="channel"
                availableSlashCommands={channelAvailableSlashCommands}
                modelOverride={src.modelOverride}
                modelProviderIdOverride={src.modelProviderIdOverride}
                onModelOverrideChange={src.setModelOverride}
                defaultModel={bot?.model}
                hideModelOverride={!!bot?.harness_runtime}
                {...harnessComposerProps}
                configOverhead={overheadPct}
                compact
                chatMode={chatMode}
                planMode={sessionPlan.mode}
                hasPlan={sessionPlan.hasPlan}
                planBusy={planBusy}
                canTogglePlanMode={!!src.sessionId}
                onTogglePlanMode={src.sessionId ? handleTogglePlanMode : undefined}
                onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
              />
            </ChatComposerShell>
          </div>
        )}
      </div>
    </div>
  );

  if (shape === "modal") {
    return (
      <ChatSessionModal open={open} onClose={onClose} title={displayTitle}>
        {body}
      </ChatSessionModal>
    );
  }

  if (shape === "fullpage") {
    return (
      <div className="flex h-full min-h-0 w-full flex-col">
        {body}
      </div>
    );
  }

  return (
    <ChatSessionDock
      open={open}
      expanded={dockExpanded}
      onExpandedChange={setDockExpanded}
      // `dismissMode="close"` (e.g. spatial canvas) wants scrim-click + Esc
      // to fully close instead of collapsing to a FAB/pill. Default behavior
      // (collapse) is preserved when the prop is omitted.
      onDismiss={dismissMode === "close" ? onClose : undefined}
      title={displayTitle}
      collapsedTitle={dockCollapsedTitle}
      collapsedSubtitle={dockCollapsedSubtitle}
      onCloseCollapsed={dockCollapsedTitle ? onClose : undefined}
      storageKey={getDockStorageKey(source)}
      chatMode={chatMode}
    >
      {body}
    </ChatSessionDock>
  );
}
