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
import { ChatComposerShell } from "./ChatComposerShell";
import { MessageInput, type PendingFile } from "./MessageInput";
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
import { useSlashCommandList } from "@/src/api/hooks/useSlashCommands";
import { useModelGroups } from "@/src/api/hooks/useModels";
import { resolveProviderForModel } from "./slashArgSources";
import { resolveAvailableSlashCommandIds } from "./slashCommandSurfaces";
import { useThemeStore } from "@/src/stores/theme";
import { useSessionPlanMode } from "@/app/(app)/channels/[channelId]/useSessionPlanMode";
import { buildRecentHref, formatSessionRecentLabel } from "@/src/lib/recentPages";
import { isTranscriptFlowComposer } from "./chatModes";

function makeClientLocalId(): string {
  const cryptoObj = globalThis.crypto as Crypto | undefined;
  if (cryptoObj?.randomUUID) return `web-${cryptoObj.randomUUID()}`;
  return `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface EphemeralContextPayload {
  page_name?: string;
  url?: string;
  tags?: string[];
  payload?: Record<string, unknown>;
  tool_hints?: string[];
}

function formatSessionHeaderTimestamp(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatHeaderTurnMeta(stats: {
  turnsInContext: number | null;
  turnsUntilCompaction: number | null;
} | null | undefined): string[] {
  const bits: string[] = [];
  if (typeof stats?.turnsInContext === "number") {
    bits.push(`${stats.turnsInContext} turn${stats.turnsInContext === 1 ? "" : "s"} in ctx`);
  }
  if (typeof stats?.turnsUntilCompaction === "number") {
    bits.push(`${stats.turnsUntilCompaction} until compact`);
  }
  return bits;
}

/** Discriminator picks which backend path the chat component talks to.
 *
 *   - ``channel`` — the dock / modal mirrors an existing channel's chat.
 *     Same store slot, same SSE, same POST /chat path as the full channel
 *     screen. Bot is the channel's primary bot (picker hidden). Maximize
 *     navigates to the full channel screen.
 *   - ``ephemeral`` — bot-agnostic ad-hoc chat. Session spawns lazily on
 *     first send. Picker visible, locks once the session exists. Legacy
 *     behavior from the original EphemeralSession component.
 *   - ``session`` — fixed existing channel session, used by split panels.
 *     Sends are web-only unless the caller explicitly opts into channel
 *     delivery. */
export type ChatSource =
  | { kind: "channel"; channelId: string }
  | {
      kind: "session";
      sessionId: string;
      parentChannelId: string;
      botId?: string;
      externalDelivery?: "channel" | "none";
    }
  | {
      kind: "ephemeral";
      sessionStorageKey: string;
      parentChannelId?: string;
      defaultBotId?: string;
      context?: EphemeralContextPayload;
      /** When set, the ephemeral session uses a user-scoped server
       *  pointer (``/sessions/scratch/current``) instead of a per-device
       *  localStorage session id. Enables cross-device scratch chat
       *  continuity. Only meaningful for the channel-page "Scratch" mount;
       *  dashboard ad-hoc ephemerals leave it undefined and stay local. */
      scratchBoundChannelId?: string;
      /** Explicit session id override. When set, the component loads
       *  messages from this session instead of resolving one via
       *  scratch-pointer or localStorage. Powers deep links to a
       *  specific scratch session on the full-page
       *  /channels/:id/session/:sid?scratch=true route. */
      pinnedSessionId?: string;
    }
  | {
      kind: "thread";
      /** Thread session id. Null until the user sends their first message —
       *  we lazy-spawn the backend Session row on first send so closing the
       *  dock without typing anything leaves no DB footprint. */
      threadSessionId: string | null;
      /** Parent channel hosting the message being replied to — powers SSE. */
      parentChannelId: string;
      /** Message the thread replies to, for the "Replying to …" hint. */
      parentMessageId: string;
      /** Bot the thread runs as (inherited from parent message's author). */
      botId: string;
      /** Pre-known parent Message passed through from the parent feed so the
       *  anchor bubble can render before (or without) the thread session
       *  existing. When null, the thread view fetches via useThreadInfo. */
      parentMessage?: Message | null;
      /** Fires once the lazy spawn resolves so the caller can swap its
       *  activeThread state from pending → live. Invoked before submitChat
       *  so the live branch can subscribe to SSE before any turn events. */
      onSessionSpawned?: (sessionId: string) => void;
    };

export interface ChatSessionProps {
  source: ChatSource;
  chatMode?: "default" | "terminal";
  /** Display mode — the controller renders the appropriate shell.
   *
   *   - ``dock`` — bottom-right panel with header chrome.
   *   - ``modal`` — centered overlay with header chrome.
   *   - ``fullpage`` — column body for embedding directly in a page layout
   *     (e.g. the scratch full-page swap or session split panels). */
  shape: "modal" | "dock" | "fullpage";
  /** Controlled open state (caller owns open/close). */
  open: boolean;
  onClose: () => void;
  /** Displayed in the modal/dock header. */
  title?: string;
  /** Empty-state content shown before the first message is sent. */
  emptyState?: React.ReactNode;
  /** When rendered as a dock, open already expanded instead of the FAB.
   *  Used for the minimize-from-channel round-trip so the user lands on
   *  the dashboard with the chat already visible. */
  initiallyExpanded?: boolean;
  dockCollapsedTitle?: string;
  dockCollapsedSubtitle?: string | null;
  onRestoreToCanvas?: () => void;
  /** What happens when the user dismisses the dock — via swipe-down on
   *  mobile or the header collapse button. Defaults to 'collapse' which
   *  retreats to the bottom-right FAB (dashboard surface). The chat
   *  screen uses 'close' because it intentionally hides the FAB: the
   *  dock is reachable only from the channel header button. */
  dismissMode?: "collapse" | "close";
  /** Opens the channel-scoped session picker when this chat is embedded
   *  inside a channel screen or split layout. */
  onOpenSessions?: () => void;
  onOpenSessionSplit?: () => void;
  onToggleFocusLayout?: () => void;
}

function getDockStorageKey(source: ChatSource): string {
  if (source.kind === "channel") {
    return `channel:${source.channelId}`;
  }
  if (source.kind === "thread") {
    return `thread:${source.parentChannelId}:${source.parentMessageId}`;
  }
  if (source.kind === "session") {
    return `session:${source.parentChannelId}:${source.sessionId}`;
  }
  return [
    "ephemeral",
    source.sessionStorageKey,
    source.parentChannelId ?? "none",
    source.scratchBoundChannelId ?? "none",
    source.pinnedSessionId ?? "none",
  ].join(":");
}

function useChatSessionPlan(sessionId: string | null | undefined) {
  const sessionPlan = useSessionPlanMode(sessionId ?? undefined);
  const planBusy = sessionPlan.startPlan.isPending
    || sessionPlan.approvePlan.isPending
    || sessionPlan.exitPlan.isPending
    || sessionPlan.resumePlan.isPending
    || sessionPlan.updateStepStatus.isPending;
  const handleTogglePlanMode = useCallback(() => {
    if (!sessionId) return;
    if (sessionPlan.mode !== "chat") {
      sessionPlan.exitPlan.mutate();
      return;
    }
    if (sessionPlan.hasPlan) {
      sessionPlan.resumePlan.mutate();
      return;
    }
    sessionPlan.startPlan.mutate();
  }, [sessionId, sessionPlan]);
  return { sessionPlan, planBusy, handleTogglePlanMode };
}

/**
 * Chat controller — renders either a channel chat or an ephemeral session
 * inside a dock (bottom-right) or modal (centered) shell.
 *
 * Dispatches source kind to a dedicated internal component so hook calls stay
 * stable across renders. All rendering primitives (ChatMessageArea,
 * MessageInput, MessageBubble) are shared with the full channel screen and
 * the pipeline run modal — there is no parallel chat renderer.
 */
export function ChatSession(props: ChatSessionProps) {
  if (props.source.kind === "channel") {
    return <ChannelChatSession {...props} source={props.source} />;
  }
  if (props.source.kind === "thread") {
    return <ThreadChatSession {...props} source={props.source} />;
  }
  if (props.source.kind === "session") {
    return <FixedSessionChatSession {...props} source={props.source} />;
  }
  return <EphemeralChatSession {...props} source={props.source} />;
}

// ---------------------------------------------------------------------------
// Channel-mode
// ---------------------------------------------------------------------------

interface ChannelChatSessionProps extends Omit<ChatSessionProps, "source"> {
  source: Extract<ChatSource, { kind: "channel" }>;
}

function ChannelChatSession({
  source,
  shape,
  open,
  onClose,
  title,
  emptyState,
  initiallyExpanded,
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
  const { data: overheadData } = useChannelConfigOverhead(source.channelId);
  const overheadPct = overheadData?.overhead_pct ?? null;
  const { sessionPlan, planBusy, handleTogglePlanMode } = useChatSessionPlan(src.sessionId);

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
    if (shape === "dock" && onRestoreToCanvas) {
      onClose();
      return;
    }
    if (shape === "dock") setDockExpanded(false);
    else onClose();
  }, [shape, onClose, onRestoreToCanvas]);

  const { handleSend: srcHandleSend } = src;
  const handleSendMsg = useCallback(
    (message: string, _files?: PendingFile[]) => {
      srcHandleSend(message);
    },
    [srcHandleSend],
  );

  const channelSlashCatalog = useSlashCommandList();
  const { data: channelModelGroups } = useModelGroups();
  const channelSlashLocalHandlers = useMemo(
    () => ({
      clear: async () => {
        await apiFetch(`/channels/${source.channelId}/reset`, { method: "POST" });
        useChatStore.getState().setMessages(source.channelId, []);
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        queryClient.invalidateQueries({ queryKey: ["channel", source.channelId] });
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
      capabilities: ["clear", "scratch", "model", "theme", "sessions", "split", "focus"],
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
                    channelId={source.channelId}
                    onSlashCommand={handleSlashCommand}
                    slashSurface="channel"
                    availableSlashCommands={channelAvailableSlashCommands}
                    modelOverride={src.modelOverride}
                    modelProviderIdOverride={src.modelProviderIdOverride}
                    onModelOverrideChange={src.setModelOverride}
                    defaultModel={bot?.model}
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
                channelId={source.channelId}
                onSlashCommand={handleSlashCommand}
                slashSurface="channel"
                availableSlashCommands={channelAvailableSlashCommands}
                modelOverride={src.modelOverride}
                modelProviderIdOverride={src.modelProviderIdOverride}
                onModelOverrideChange={src.setModelOverride}
                defaultModel={bot?.model}
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

// ---------------------------------------------------------------------------
// Fixed existing-session mode
// ---------------------------------------------------------------------------

interface FixedSessionChatSessionProps extends Omit<ChatSessionProps, "source"> {
  source: Extract<ChatSource, { kind: "session" }>;
}

function FixedSessionChatSession({
  source,
  shape,
  open,
  onClose,
  title = "Session",
  emptyState,
  initiallyExpanded,
  dockCollapsedTitle,
  dockCollapsedSubtitle,
  onRestoreToCanvas,
  onOpenSessions,
  onOpenSessionSplit,
  onToggleFocusLayout,
  chatMode = "default",
}: FixedSessionChatSessionProps) {
  const t = useThemeTokens();
  const composerInTranscriptFlow = isTranscriptFlowComposer(chatMode);
  const qc = useQueryClient();
  const { data: bots } = useBots();
  const { data: sessionModelGroups } = useModelGroups();
  const submitChat = useSubmitChat();
  const cancelChat = useCancelChat();
  const sessionId = source.sessionId;
  const parentChannelId = source.parentChannelId;
  const botId = source.botId ?? bots?.[0]?.id ?? "";
  const chatState = useChatStore((s) => s.getChannel(sessionId));
  const turnActive = selectIsStreaming(chatState);
  const isSending = submitChat.isPending || turnActive;
  const [sendError, setSendError] = useState<string | null>(null);
  const [modelOverride, setModelOverrideState] = useState<string | undefined>(undefined);
  const [modelProviderId, setModelProviderId] = useState<string | null>(null);
  const { data: overheadData } = useSessionConfigOverhead(sessionId);
  const overheadPct = overheadData?.overhead_pct ?? null;
  const { sessionPlan, planBusy, handleTogglePlanMode } = useChatSessionPlan(sessionId);
  const [slashSyntheticMessages, setSlashSyntheticMessages] = useState<Message[]>([]);

  const [dockExpanded, setDockExpanded] = useState(
    shape === "dock" && (initiallyExpanded ?? false),
  );
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

  const setModelOverride = useCallback((m: string | undefined, pid?: string | null) => {
    setModelOverrideState(m);
    setModelProviderId(m ? (pid ?? null) : null);
  }, []);

  const syncCancelledState = useCallback(() => {
    const ch = useChatStore.getState().getChannel(sessionId);
    for (const turnId of Object.keys(ch.turns)) {
      useChatStore.getState().handleTurnEvent(sessionId, turnId, {
        event: "error",
        data: { message: "cancelled" },
      });
      useChatStore.getState().finishTurn(sessionId, turnId);
    }
    useChatStore.getState().clearProcessing(sessionId);
    qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
  }, [qc, sessionId]);

  const handleSend = useCallback(async (message: string) => {
    if (!botId) {
      setSendError("Pick a bot first.");
      return;
    }
    setSendError(null);
    const clientLocalId = makeClientLocalId();
    useChatStore.getState().addMessage(sessionId, {
      id: `msg-${clientLocalId}`,
      session_id: sessionId,
      role: "user",
      content: message,
      created_at: new Date().toISOString(),
      metadata: {
        source: "web",
        sender_type: "human",
        client_local_id: clientLocalId,
        local_status: "sending",
      },
    });
    try {
      const result = await submitChat.mutateAsync({
        message,
        bot_id: botId,
        client_id: "web",
        channel_id: parentChannelId,
        session_id: sessionId,
        external_delivery: source.externalDelivery ?? "none",
        msg_metadata: {
          source: "web",
          sender_type: "human",
          client_local_id: clientLocalId,
        },
        ...(modelOverride ? {
          model_override: modelOverride,
          model_provider_id_override: modelProviderId,
        } : {}),
      });
      useChatStore.getState().setProcessing(
        sessionId,
        result.task_id ?? result.turn_id ?? clientLocalId,
      );
      qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
    } catch (err) {
      useChatStore.getState().clearProcessing(sessionId);
      setSendError(err instanceof Error ? err.message : "Failed to send message");
    }
  }, [botId, modelOverride, modelProviderId, parentChannelId, qc, sessionId, source.externalDelivery, submitChat]);

  const handleCancel = useCallback(() => {
    cancelChat.mutate({
      client_id: "web",
      bot_id: botId,
      session_id: sessionId,
      channel_id: parentChannelId,
    });
    syncCancelledState();
  }, [botId, cancelChat, parentChannelId, sessionId, syncCancelledState]);

  const slashCatalog = useSlashCommandList();
  const availableSlashCommands = useMemo(
    () => resolveAvailableSlashCommandIds({
      catalog: slashCatalog,
      surface: "session",
      enabled: !!sessionId,
      capabilities: onOpenSessions
        ? ["model", "theme", "sessions", "split", "focus"]
        : ["model", "theme"],
    }),
    [onOpenSessions, sessionId, slashCatalog],
  );
  const localHandlers = useMemo(
    () => ({
      model: (args: string[]) => {
        if (!args[0]) return;
        const providerId = resolveProviderForModel(args[0], sessionModelGroups);
        setModelOverride(args[0], providerId ?? null);
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
    [onOpenSessionSplit, onOpenSessions, onToggleFocusLayout, sessionModelGroups, setModelOverride],
  );
  const handleSlashCommand = useSlashCommandExecutor({
    availableCommands: availableSlashCommands,
    catalog: slashCatalog,
    surface: "session",
    sessionId,
    onSyntheticMessage: (message) => setSlashSyntheticMessages((prev) => [message, ...prev]),
    localHandlers,
    onSideEffect: async (result) => {
      if (result.command_id === "stop") syncCancelledState();
      if (result.command_id === "compact") {
        qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
      }
    },
  });

  const composer = (
    <>
      {sendError && (
        <div className="px-4 py-1.5 text-[11px] text-danger bg-danger/5">
          {sendError}
        </div>
      )}
      <ChatComposerShell chatMode={chatMode}>
        <MessageInput
          onSend={handleSend}
          onCancel={handleCancel}
          disabled={!botId}
          isStreaming={isSending}
          currentBotId={botId || undefined}
          channelId={sessionId}
          onSlashCommand={handleSlashCommand}
          slashSurface="session"
          availableSlashCommands={availableSlashCommands}
          modelOverride={modelOverride}
          modelProviderIdOverride={modelProviderId}
          onModelOverrideChange={setModelOverride}
          defaultModel={bots?.find((b) => b.id === botId)?.model}
          configOverhead={overheadPct}
          compact
          chatMode={chatMode}
          planMode={sessionPlan.mode}
          hasPlan={sessionPlan.hasPlan}
          planBusy={planBusy}
          canTogglePlanMode={!!sessionId}
          onTogglePlanMode={handleTogglePlanMode}
          onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
        />
      </ChatComposerShell>
    </>
  );

  const body = (
    <div className="flex h-full min-h-0 flex-col">
      {shape === "dock" && onRestoreToCanvas && (
        <div className="flex h-9 shrink-0 items-center justify-between gap-2 bg-surface-overlay/30 px-3">
          <span className="min-w-0 truncate text-[12px] font-semibold text-text">{title}</span>
          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={onRestoreToCanvas}
              title="Restore to canvas"
              aria-label="Restore to canvas"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
            >
              <Rows3 size={13} />
            </button>
            <button
              type="button"
              onClick={onClose}
              title="Close mini chat"
              aria-label="Close mini chat"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
            >
              <X size={13} />
            </button>
          </div>
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        <SessionChatView
          sessionId={sessionId}
          parentChannelId={parentChannelId}
          botId={botId}
          emptyStateComponent={emptyState}
          scrollPaddingBottom={composerInTranscriptFlow ? 20 : inputOverlayHeight + 16}
          chatMode={chatMode}
          syntheticMessages={slashSyntheticMessages}
          bottomSlot={composerInTranscriptFlow ? composer : undefined}
        />
        {!composerInTranscriptFlow && (
          <div ref={inputOverlayRef} className="absolute bottom-0 left-0 right-0 z-[4]">
            {composer}
          </div>
        )}
      </div>
    </div>
  );

  if (shape === "modal") {
    return (
      <ChatSessionModal open={open} onClose={onClose} title={title}>
        {body}
      </ChatSessionModal>
    );
  }

  if (shape === "dock") {
    return (
      <ChatSessionDock
        open={open}
        expanded={dockExpanded}
        onExpandedChange={setDockExpanded}
        title={title}
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

  return <div className="flex h-full min-h-0 w-full flex-col">{body}</div>;
}

// ---------------------------------------------------------------------------
// Ephemeral-mode (original EphemeralSession logic, preserved verbatim)
// ---------------------------------------------------------------------------

interface EphemeralChatSessionProps extends Omit<ChatSessionProps, "source"> {
  source: Extract<ChatSource, { kind: "ephemeral" }>;
}

function EphemeralChatSession({
  source,
  shape,
  open,
  onClose,
  title = "Chat",
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
}: EphemeralChatSessionProps) {
  const t = useThemeTokens();
  const composerInTranscriptFlow = isTranscriptFlowComposer(chatMode);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const { data: bots } = useBots();
  const { data: sessionModelGroups } = useModelGroups();
  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);

  const {
    sessionStorageKey,
    parentChannelId,
    defaultBotId,
    context,
    scratchBoundChannelId,
    pinnedSessionId,
  } = source;
  const resolvedDefault = defaultBotId ?? bots?.[0]?.id ?? "";

  const [stored, setStored] = useState<StoredEphemeralState | null>(() =>
    sessionStorageKey ? loadEphemeralState(sessionStorageKey) : null,
  );

  // Server-backed scratch pointer — resolves the caller's active
  // scratch session for (channel, user, bot) so the session_id is
  // stable across devices. Local storage is kept only as a first-paint
  // cache for model overrides.
  const scratchQuery = useScratchSession(
    scratchBoundChannelId ?? null,
    scratchBoundChannelId ? stored?.botId ?? resolvedDefault : null,
  );
  const { data: scratchHistory } = useScratchHistory(scratchBoundChannelId ?? null);
  const resetScratch = useResetScratchSession();

  const serverSessionId = scratchBoundChannelId
    ? scratchQuery.data?.session_id ?? null
    : null;
  const serverBotId = scratchBoundChannelId
    ? scratchQuery.data?.bot_id ?? null
    : null;

  const sessionId = pinnedSessionId
    ? pinnedSessionId
    : scratchBoundChannelId
      ? serverSessionId
      : (stored?.sessionId && stored.sessionId.length > 0 ? stored.sessionId : null);
  const botId = scratchBoundChannelId
    ? (serverBotId ?? stored?.botId ?? resolvedDefault)
    : (stored?.botId ?? resolvedDefault);
  const modelOverride = stored?.modelOverride ?? undefined;
  const modelProviderId = stored?.modelProviderId ?? null;

  const [mode, setMode] = useState<"dock" | "modal" | "fullpage">(shape);
  // For ephemeral docks we always land on the panel (no FAB intermediate) —
  // the entry point is the channel header button, so a collapsed FAB state
  // would be redundant chrome. Collapse requests become full closes below.
  const [dockExpanded, setDockExpanded] = useState(
    shape === "dock" && (initiallyExpanded ?? false),
  );
  // No-FAB mode: re-sync `dockExpanded` whenever `open` flips back to true.
  // ChatSessionDock's own effect collapses expanded→false on dismissal, and
  // without a FAB there's no way to re-expand, so subsequent opens would
  // render nothing. Only applies when dismissMode !== "collapse" (the
  // dashboard FAB path keeps its minimize-to-button state on purpose).
  useEffect(() => {
    if (open && dismissMode !== "collapse") setDockExpanded(true);
  }, [open, dismissMode]);

  // Measure the composer overlay height so messages scroll BEHIND the
  // frosted composer instead of being clipped by it. Mirrors ChannelChatSession
  // and the main channel screen.
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

  const persistRef = useRef<(patch: Partial<StoredEphemeralState>) => void>(() => {});
  persistRef.current = (patch: Partial<StoredEphemeralState>) => {
    setStored((s) => {
      const next: StoredEphemeralState = {
        sessionId: s?.sessionId ?? "",
        botId: s?.botId ?? resolvedDefault,
        modelOverride: s?.modelOverride ?? null,
        modelProviderId: s?.modelProviderId ?? null,
        ...patch,
      };
      if (sessionStorageKey) saveEphemeralState(sessionStorageKey, next);
      return next;
    });
  };

  const setBotId = useCallback(
    (id: string) => {
      if (stored?.sessionId) return; // locked once session exists
      persistRef.current({ botId: id });
    },
    [stored?.sessionId],
  );

  const setModelOverride = useCallback(
    (m: string | undefined, pid?: string | null) => {
      persistRef.current({ modelOverride: m ?? null, modelProviderId: pid ?? null });
    },
    [],
  );

  useEffect(() => {
    if (!stored?.botId && resolvedDefault) {
      persistRef.current({ botId: resolvedDefault });
    }
  }, [resolvedDefault, stored?.botId]);

  const spawn = useSpawnEphemeralSession();
  const submitChat = useSubmitChat();
  const [sendError, setSendError] = useState<string | null>(null);
  const chatState = useChatStore((s) => (sessionId ? s.getChannel(sessionId) : null));
  const turnActive = chatState ? selectIsStreaming(chatState) : false;
  const isSending = submitChat.isPending || turnActive;

  const { data: overheadData } = useSessionConfigOverhead(sessionId ?? undefined);
  const { data: scratchChannel } = useChannel(scratchBoundChannelId ?? undefined);
  const overheadPct = overheadData?.overhead_pct ?? null;
  const { sessionPlan, planBusy, handleTogglePlanMode } = useChatSessionPlan(sessionId);

  const handleSend = useCallback(
    async (message: string, _files?: PendingFile[]) => {
      setSendError(null);
      if (!botId) {
        setSendError("Pick a bot first.");
        return;
      }

      let activeSessionId = sessionId;

      if (!activeSessionId) {
        if (scratchBoundChannelId) {
          // Server-scratch mode: the hook auto-creates on mount. If we
          // still have no id something is wrong upstream — surface it
          // rather than silently double-spawning via the ephemeral POST.
          setSendError("Session not ready yet — try again.");
          return;
        }
        try {
          const result = await spawn.mutateAsync({
            bot_id: botId,
            parent_channel_id: parentChannelId,
            context,
          });
          activeSessionId = result.session_id;
          persistRef.current({ sessionId: activeSessionId, botId });
        } catch (err) {
          setSendError(err instanceof Error ? err.message : "Failed to start session");
          return;
        }
      }

      try {
        const clientLocalId = makeClientLocalId();
        useChatStore.getState().addMessage(activeSessionId, {
          id: `msg-${clientLocalId}`,
          session_id: activeSessionId,
          role: "user",
          content: message,
          created_at: new Date().toISOString(),
          metadata: {
            source: "web",
            sender_type: "human",
            client_local_id: clientLocalId,
            local_status: "sending",
          },
        });
        await submitChat.mutateAsync({
          message,
          bot_id: botId,
          client_id: "web",
          session_id: activeSessionId,
          channel_id: parentChannelId,
          msg_metadata: {
            source: "web",
            sender_type: "human",
            client_local_id: clientLocalId,
          },
          ...(modelOverride ? {
            model_override: modelOverride,
            model_provider_id_override: modelProviderId,
          } : {}),
        });
        qc.invalidateQueries({ queryKey: ["session-messages", activeSessionId] });
      } catch (err) {
        setSendError(err instanceof Error ? err.message : "Failed to send message");
      }
    },
    [botId, sessionId, parentChannelId, context, spawn, submitChat, modelOverride, modelProviderId, qc],
  );

  const [historyOpen, setHistoryOpen] = useState(false);
  const [slashSyntheticMessages, setSlashSyntheticMessages] = useState<Message[]>([]);
  const syncSessionCancelledState = useCallback(() => {
    if (!sessionId) return;
    const ch = useChatStore.getState().getChannel(sessionId);
    for (const turnId of Object.keys(ch.turns)) {
      useChatStore.getState().handleTurnEvent(sessionId, turnId, {
        event: "error",
        data: { message: "cancelled" },
      });
      useChatStore.getState().finishTurn(sessionId, turnId);
    }
    useChatStore.getState().clearProcessing(sessionId);
    qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
  }, [qc, sessionId]);
  const sessionSlashCatalog = useSlashCommandList();
  const sessionAvailableSlashCommands = useMemo(
    () => resolveAvailableSlashCommandIds({
      catalog: sessionSlashCatalog,
      surface: "session",
      enabled: !!sessionId,
      capabilities: onOpenSessions
        ? ["model", "theme", "sessions", "split", "focus"]
        : ["model", "theme"],
    }),
    [onOpenSessions, sessionId, sessionSlashCatalog],
  );
  const sessionSlashLocalHandlers = useMemo(
    () => ({
      model: (args: string[]) => {
        if (!args[0]) return;
        const providerId = resolveProviderForModel(args[0], sessionModelGroups);
        setModelOverride(args[0], providerId ?? null);
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
    [onOpenSessionSplit, onOpenSessions, onToggleFocusLayout, sessionModelGroups, setModelOverride],
  );
  const handleSessionSlashCommand = useSlashCommandExecutor({
    availableCommands: sessionAvailableSlashCommands,
    catalog: sessionSlashCatalog,
    surface: "session",
    sessionId: sessionId ?? undefined,
    onSyntheticMessage: (message) => setSlashSyntheticMessages((prev) => [message, ...prev]),
    localHandlers: sessionSlashLocalHandlers,
    onSideEffect: async (result) => {
      if (result.command_id === "stop") syncSessionCancelledState();
      if (result.command_id === "compact") {
        qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
      }
    },
  });

  // Two-click speed-bump for reset.
  const [resetArmed, setResetArmed] = useState(false);
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!resetArmed) return;
    resetTimerRef.current = setTimeout(() => setResetArmed(false), 3000);
    return () => {
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
    };
  }, [resetArmed]);

  const handleReset = useCallback(() => {
    if (!resetArmed) {
      setResetArmed(true);
      return;
    }
    if (scratchBoundChannelId && botId) {
      // Server-backed reset: prior session stays in history, a fresh
      // one becomes is_current. Optimistic local clear keeps the UI
      // snappy; the query invalidation inside the mutation brings the
      // new session id in.
      resetScratch.mutate(
        { parent_channel_id: scratchBoundChannelId, bot_id: botId },
        {
          onError: (err) => {
            setSendError(err instanceof Error ? err.message : "Failed to reset scratch.");
          },
        },
      );
    } else if (sessionStorageKey) {
      clearEphemeralState(sessionStorageKey);
    }
    setStored(null);
    setSendError(null);
    setResetArmed(false);
  }, [resetArmed, scratchBoundChannelId, botId, resetScratch, sessionStorageKey]);

  // Ephemeral session: X always closes. No FAB-collapse intermediate (the
  // only entry point is the channel header button, so a minimized dock-FAB
  // would be redundant chrome).
  const handleHeaderClose = useCallback(() => {
    if (mode === "dock" && onRestoreToCanvas) {
      onClose();
      return;
    }
    onClose();
  }, [mode, onClose, onRestoreToCanvas]);

  const isFullpage = mode === "fullpage";
  // Scratch docks navigate to a dedicated full-page route instead of
  // promoting to a modal — the expand becomes a URL change so the user
  // can deep-link / share / back-button the scratch view.
  const canNavigateFullpage = !!scratchBoundChannelId && !!sessionId;
  const expandTitle = canNavigateFullpage
    ? "Open full session page"
    : mode === "dock"
      ? "Expand to full view"
      : "Minimize to dock";
  const ExpandIcon = mode === "dock" ? Maximize2 : Minimize2;
  const handleExpandClick = useCallback(() => {
    if (canNavigateFullpage && scratchBoundChannelId && sessionId) {
      navigate(`/channels/${scratchBoundChannelId}/session/${sessionId}?scratch=true`);
      return;
    }
    setMode((m) => (m === "dock" ? "modal" : "dock"));
  }, [canNavigateFullpage, scratchBoundChannelId, sessionId, navigate]);
  const { data: headerStats } = useSessionHeaderStats(
    scratchBoundChannelId ?? parentChannelId ?? undefined,
    sessionId,
  );
  const overheadColor = useMemo(() => {
    if (overheadPct == null) return null;
    if (overheadPct >= 0.4) return "#ef4444";
    if (overheadPct >= 0.2) return "#eab308";
    return null;
  }, [overheadPct]);
  const sessionHeaderMeta = useMemo(() => {
    if (!scratchBoundChannelId || !sessionId) return null;
    const matchedHistory = scratchHistory?.find((row) => row.session_id === sessionId) ?? null;
    const matchedCurrent = scratchQuery.data?.session_id === sessionId ? scratchQuery.data : null;
    const label =
      matchedHistory?.title?.trim()
      || matchedHistory?.summary?.trim()
      || matchedHistory?.preview?.trim()
      || matchedCurrent?.title?.trim()
      || matchedCurrent?.summary?.trim()
      || null;
    const timestamp = formatSessionHeaderTimestamp(
      matchedHistory?.last_active ?? matchedCurrent?.created_at ?? null,
    );
    const messageCount = matchedHistory?.message_count ?? matchedCurrent?.message_count ?? null;
    const sectionCount = matchedHistory?.section_count ?? matchedCurrent?.section_count ?? null;
    const stats = [
      timestamp,
      typeof messageCount === "number"
        ? `${messageCount} msg${messageCount === 1 ? "" : "s"}`
        : null,
      typeof sectionCount === "number"
        ? `${sectionCount} section${sectionCount === 1 ? "" : "s"}`
        : null,
      ...formatHeaderTurnMeta(headerStats),
    ].filter(Boolean).join(" · ");
    if (!label && !stats) return null;
    return {
      label,
      stats: stats || null,
    };
  }, [headerStats, scratchBoundChannelId, sessionId, scratchHistory, scratchQuery.data]);
  useEffect(() => {
    if (!scratchBoundChannelId || !sessionId || !scratchChannel?.name) return;
    const expectedPath = `/channels/${scratchBoundChannelId}/session/${sessionId}`;
    if (location.pathname !== expectedPath) return;
    const currentHref = buildRecentHref(location.pathname, location.search, location.hash);
    enrichRecentPage(
      currentHref,
      formatSessionRecentLabel(scratchChannel.name, sessionHeaderMeta?.label),
    );
  }, [
    enrichRecentPage,
    location.pathname,
    location.search,
    location.hash,
    scratchBoundChannelId,
    scratchChannel?.name,
    sessionHeaderMeta?.label,
    sessionId,
  ]);
  const displayHeaderTitle =
    sessionHeaderMeta?.label
    ?? (scratchBoundChannelId ? "Session" : title);

  const header = (
    <div
      className="flex items-start justify-between gap-2 px-3 py-2 shrink-0"
      style={{
        backgroundColor: chatMode === "terminal" ? `${t.overlayLight}2e` : `${t.overlayLight}1a`,
      }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 min-w-0">
          <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-text">
            {displayHeaderTitle}
          </span>
          <div className="w-[156px] max-w-[156px] shrink-0">
            <BotPicker
              compact
              value={botId}
              onChange={setBotId}
              bots={bots ?? []}
              disabled={!!sessionId}
              placeholder="Pick a bot"
            />
          </div>
        </div>
        {sessionHeaderMeta?.stats && (
          <div className="mt-1 min-w-0">
            <div className="truncate text-[11px] text-text-dim">
              {sessionHeaderMeta.stats}
            </div>
          </div>
        )}
      </div>
      <div className="flex items-center gap-0.5 shrink-0 self-start pt-0.5">
        {overheadColor && (
          <button
            type="button"
            title={`Context overhead: ${Math.round((overheadPct ?? 0) * 100)}% of the model's window is spent on tools, skills, and system prompts`}
            className="w-2 h-2 rounded-full mx-1"
            style={{ backgroundColor: overheadColor, border: "none", cursor: "help" }}
          />
        )}
        {!isFullpage && (
          <button
            onClick={handleExpandClick}
            title={expandTitle}
            aria-label={expandTitle}
            className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
          >
            <ExpandIcon size={13} />
          </button>
        )}
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
        {scratchBoundChannelId && (
          <button
            onClick={() => setHistoryOpen(true)}
            title="Session history"
            aria-label="Open session history"
            className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
          >
            <History size={13} />
          </button>
        )}
        {sessionId && (
          <button
            onClick={handleReset}
            title={resetArmed ? "Click again within 3 s to reset the session" : "Reset session"}
            aria-label="Reset session"
            className={`p-1.5 rounded transition-colors ${
              resetArmed
                ? "text-red-400 bg-red-500/10 animate-pulse"
                : "text-text-dim hover:text-text hover:bg-white/5"
            }`}
          >
            <RotateCcw size={13} />
          </button>
        )}
        {!isFullpage && (
          <button
            onClick={handleHeaderClose}
            title={mode === "dock" ? "Collapse to button" : "Close"}
            aria-label={mode === "dock" ? "Collapse to button" : "Close"}
            className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
          >
            <X size={13} />
          </button>
        )}
      </div>
    </div>
  );

  const body = (
    <div className="flex flex-col h-full">
      {/* Fullpage hosts the header controls (history / reset / minimize)
          up in ChannelHeader — skip the internal chrome row entirely so
          the chat column doesn't carry two redundant title bars. */}
      {!isFullpage && header}
      <div className="flex-1 min-h-0 relative">
        {sessionId ? (
          <SessionChatView
            sessionId={sessionId}
            parentChannelId={parentChannelId}
            botId={botId}
            emptyStateComponent={emptyState}
            scrollPaddingBottom={composerInTranscriptFlow ? 20 : inputOverlayHeight + 16}
            chatMode={chatMode}
            syntheticMessages={slashSyntheticMessages}
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
                    currentBotId={botId || undefined}
                    channelId={sessionId ?? undefined}
                    onSlashCommand={handleSessionSlashCommand}
                    slashSurface="session"
                    availableSlashCommands={sessionAvailableSlashCommands}
                    modelOverride={modelOverride}
                    modelProviderIdOverride={modelProviderId}
                    onModelOverrideChange={setModelOverride}
                    defaultModel={bots?.find((b) => b.id === botId)?.model}
                    configOverhead={overheadPct}
                    compact
                    chatMode={chatMode}
                    planMode={sessionPlan.mode}
                    hasPlan={sessionPlan.hasPlan}
                    planBusy={planBusy}
                    canTogglePlanMode={!!sessionId}
                    onTogglePlanMode={sessionId ? handleTogglePlanMode : undefined}
                    onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
                  />
                </ChatComposerShell>
              </>
            ) : undefined}
          />
        ) : (
          <ChatMessageArea
            invertedData={[]}
            renderMessage={() => <></>}
            chatState={{ turns: {} }}
            bot={undefined}
            botId={botId || undefined}
            isLoading={false}
            isFetchingNextPage={false}
            hasNextPage={false}
            handleLoadMore={() => {}}
            isProcessing={false}
            t={t}
            emptyStateComponent={
              <div className="flex items-center justify-center text-text-dim text-sm px-4 text-center">
                {emptyState ?? "Send a message to start the conversation"}
              </div>
            }
            scrollPaddingBottom={composerInTranscriptFlow ? 20 : inputOverlayHeight + 16}
            chatMode={chatMode}
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
                    currentBotId={botId || undefined}
                    channelId={sessionId ?? undefined}
                    slashSurface="session"
                    availableSlashCommands={[]}
                    modelOverride={modelOverride}
                    modelProviderIdOverride={modelProviderId}
                    onModelOverrideChange={setModelOverride}
                    defaultModel={bots?.find((b) => b.id === botId)?.model}
                    configOverhead={overheadPct}
                    compact
                    chatMode={chatMode}
                    planMode={sessionPlan.mode}
                    hasPlan={sessionPlan.hasPlan}
                    planBusy={planBusy}
                    canTogglePlanMode={!!sessionId}
                    onTogglePlanMode={sessionId ? handleTogglePlanMode : undefined}
                    onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
                  />
                </ChatComposerShell>
              </>
            ) : undefined}
          />
        )}
        {/* Composer overlay — messages scroll behind the frosted card
            (mirrors ChannelChatSession + the main channel screen). No
            border-top wrapper; the card's own elevation separates it. */}
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
                currentBotId={botId || undefined}
                channelId={sessionId ?? undefined}
                onSlashCommand={handleSessionSlashCommand}
                slashSurface="session"
                availableSlashCommands={sessionAvailableSlashCommands}
                modelOverride={modelOverride}
                modelProviderIdOverride={modelProviderId}
                onModelOverrideChange={setModelOverride}
                defaultModel={bots?.find((b) => b.id === botId)?.model}
                configOverhead={overheadPct}
                compact
                chatMode={chatMode}
                planMode={sessionPlan.mode}
                hasPlan={sessionPlan.hasPlan}
                planBusy={planBusy}
                canTogglePlanMode={!!sessionId}
                onTogglePlanMode={sessionId ? handleTogglePlanMode : undefined}
                onApprovePlan={sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined}
              />
            </ChatComposerShell>
          </div>
        )}
      </div>
    </div>
  );

  const historyModal = scratchBoundChannelId ? (
    <ScratchHistoryModal
      open={historyOpen}
      onClose={() => setHistoryOpen(false)}
      channelId={scratchBoundChannelId}
    />
  ) : null;

  if (mode === "fullpage") {
    return (
      <>
        <div className="flex flex-col h-full w-full min-h-0">{body}</div>
        {historyModal}
      </>
    );
  }

  if (mode === "modal") {
    return (
      <>
        <ChatSessionModal open={open} onClose={onClose} title={title}>
          {body}
        </ChatSessionModal>
        {historyModal}
      </>
    );
  }

  return (
    <>
    <ChatSessionDock
      open={open}
      expanded={dockExpanded}
      onExpandedChange={setDockExpanded}
      // Chat-screen scratch has no FAB: the only entry point is the
      // channel header button, so dismissal goes straight to close.
      // Dashboard widget ephemerals would pass dismissMode='collapse'.
      onDismiss={
        dismissMode === "collapse" ? undefined : onClose
      }
      title={title}
      collapsedTitle={dockCollapsedTitle}
      collapsedSubtitle={dockCollapsedSubtitle}
      onCloseCollapsed={dockCollapsedTitle ? onClose : undefined}
      storageKey={getDockStorageKey(source)}
      chatMode={chatMode}
    >
      {body}
    </ChatSessionDock>
    {historyModal}
    </>
  );
}

// ---------------------------------------------------------------------------
// Thread-mode — session pre-spawned via POST /messages/{id}/thread.
// Streaming rides the parent channel's SSE with session-id filter (same
// path as the pipeline run modal). No bot picker: threads run as the
// inherited bot. Maximize deep-links into the full-screen thread route.
// ---------------------------------------------------------------------------

interface ThreadChatSessionProps extends Omit<ChatSessionProps, "source"> {
  source: Extract<ChatSource, { kind: "thread" }>;
}

function ThreadChatSession({
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
  const threadSlashCatalog = useSlashCommandList();
  const threadAvailableSlashCommands = useMemo(
    () => resolveAvailableSlashCommandIds({
      catalog: threadSlashCatalog,
      surface: "session",
      enabled: !!effectiveSessionId,
      capabilities: onOpenSessions
        ? ["model", "theme", "sessions", "split", "focus"]
        : ["model", "theme"],
    }),
    [effectiveSessionId, onOpenSessions, threadSlashCatalog],
  );
  const threadSlashLocalHandlers = useMemo(
    () => ({
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
    [onOpenSessionSplit, onOpenSessions, onToggleFocusLayout, threadModelGroups],
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
    },
  });

  const handleSend = useCallback(
    async (message: string, _files?: PendingFile[]) => {
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
          },
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
                    currentBotId={botId}
                    channelId={storeKey}
                    onSlashCommand={handleThreadSlashCommand}
                    slashSurface="session"
                    availableSlashCommands={threadAvailableSlashCommands}
                    defaultModel={bot?.model}
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
                    currentBotId={botId}
                    channelId={storeKey}
                    defaultModel={bot?.model}
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
                currentBotId={botId}
                channelId={storeKey}
                onSlashCommand={handleThreadSlashCommand}
                slashSurface="session"
                availableSlashCommands={threadAvailableSlashCommands}
                defaultModel={bot?.model}
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
