import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useBots, useBot } from "@/src/api/hooks/useBots";
import { useSubmitChat } from "@/src/api/hooks/useChat";
import { useQueryClient } from "@tanstack/react-query";
import {
  useSpawnEphemeralSession,
  loadEphemeralState,
  saveEphemeralState,
  clearEphemeralState,
  type StoredEphemeralState,
} from "@/src/api/hooks/useEphemeralSession";
import { useSessionConfigOverhead } from "@/src/api/hooks/useSessionConfigOverhead";
import { useChannelConfigOverhead } from "@/src/api/hooks/useChannels";
import { useChannelChatSource } from "@/src/api/hooks/useChannelChatSource";
import { selectIsStreaming, useChatStore } from "@/src/stores/chat";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { ChatSessionModal } from "./ChatSessionModal";
import { ChatSessionDock } from "./ChatSessionDock";
import { SessionChatView } from "./SessionChatView";
import { MessageInput, type PendingFile } from "./MessageInput";
import { ChatMessageArea, DateSeparator } from "./ChatMessageArea";
import { MessageBubble } from "./MessageBubble";
import { TaskRunEnvelope } from "./TaskRunEnvelope";
import { TriggerCard, SUPPORTED_TRIGGERS } from "./TriggerCard";
import {
  formatDateSeparator,
  isDifferentDay,
  shouldGroup,
  getTurnText,
} from "@/app/(app)/channels/[channelId]/chatUtils";
import { useThemeTokens } from "@/src/theme/tokens";
import { Maximize2, Minimize2, RotateCcw, X } from "lucide-react";
import type { Message } from "@/src/types/api";

export interface EphemeralContextPayload {
  page_name?: string;
  url?: string;
  tags?: string[];
  payload?: Record<string, unknown>;
  tool_hints?: string[];
}

/** Discriminator picks which backend path the chat component talks to.
 *
 *   - ``channel`` — the dock / modal mirrors an existing channel's chat.
 *     Same store slot, same SSE, same POST /chat path as the full channel
 *     screen. Bot is the channel's primary bot (picker hidden). Maximize
 *     navigates to the full channel screen.
 *   - ``ephemeral`` — bot-agnostic ad-hoc chat. Session spawns lazily on
 *     first send. Picker visible, locks once the session exists. Legacy
 *     behavior from the original EphemeralSession component. */
export type ChatSource =
  | { kind: "channel"; channelId: string }
  | {
      kind: "ephemeral";
      sessionStorageKey: string;
      parentChannelId?: string;
      defaultBotId?: string;
      context?: EphemeralContextPayload;
    };

export interface ChatSessionProps {
  source: ChatSource;
  /** Display mode — the controller renders the appropriate shell. */
  shape: "modal" | "dock";
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
}: ChannelChatSessionProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();

  const src = useChannelChatSource(source.channelId);
  const { data: bot } = useBot(src.bot_id);
  const { data: overheadData } = useChannelConfigOverhead(source.channelId);
  const overheadPct = overheadData?.overhead_pct ?? null;

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
            channelId={source.channelId}
            isLatestBotMessage={isLatest}
            compact
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
    if (shape === "dock") setDockExpanded(false);
    else onClose();
  }, [shape, onClose]);

  const { handleSend: srcHandleSend } = src;
  const handleSendMsg = useCallback(
    (message: string, _files?: PendingFile[]) => {
      srcHandleSend(message);
    },
    [srcHandleSend],
  );

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
      style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
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
        />
        {/* Composer overlay — messages scroll behind the frosted card
            (mirrors the main channel screen pattern). */}
        <div
          ref={inputOverlayRef}
          className="absolute bottom-0 left-0 right-0 z-[4]"
        >
          {src.sendError && (
            <div className="px-4 py-1.5 text-[11px] text-red-400 bg-red-500/5">
              {src.sendError}
            </div>
          )}
          <MessageInput
            onSend={handleSendMsg}
            disabled={!src.bot_id}
            isStreaming={src.isStreaming}
            currentBotId={src.bot_id}
            channelId={source.channelId}
            modelOverride={src.modelOverride}
            modelProviderIdOverride={src.modelProviderIdOverride}
            onModelOverrideChange={src.setModelOverride}
            defaultModel={bot?.model}
            configOverhead={overheadPct}
            compact
          />
        </div>
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

  return (
    <ChatSessionDock
      open={open}
      expanded={dockExpanded}
      onExpandedChange={setDockExpanded}
      title={displayTitle}
    >
      {body}
    </ChatSessionDock>
  );
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
}: EphemeralChatSessionProps) {
  const t = useThemeTokens();
  const qc = useQueryClient();
  const { data: bots } = useBots();

  const { sessionStorageKey, parentChannelId, defaultBotId, context } = source;
  const resolvedDefault = defaultBotId ?? bots?.[0]?.id ?? "";

  const [stored, setStored] = useState<StoredEphemeralState | null>(() =>
    sessionStorageKey ? loadEphemeralState(sessionStorageKey) : null,
  );

  const sessionId = stored?.sessionId && stored.sessionId.length > 0 ? stored.sessionId : null;
  const botId = stored?.botId ?? resolvedDefault;
  const modelOverride = stored?.modelOverride ?? undefined;
  const modelProviderId = stored?.modelProviderId ?? null;

  const [mode, setMode] = useState<"dock" | "modal">(shape);
  const [dockExpanded, setDockExpanded] = useState(false);

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
  const overheadPct = overheadData?.overhead_pct ?? null;

  const handleSend = useCallback(
    async (message: string, _files?: PendingFile[]) => {
      setSendError(null);
      if (!botId) {
        setSendError("Pick a bot first.");
        return;
      }

      let activeSessionId = sessionId;

      if (!activeSessionId) {
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
        await submitChat.mutateAsync({
          message,
          bot_id: botId,
          client_id: "web",
          session_id: activeSessionId,
          channel_id: parentChannelId,
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
    if (sessionStorageKey) clearEphemeralState(sessionStorageKey);
    setStored(null);
    setSendError(null);
    setResetArmed(false);
  }, [resetArmed, sessionStorageKey]);

  const handleHeaderClose = useCallback(() => {
    if (mode === "dock") setDockExpanded(false);
    else onClose();
  }, [mode, onClose]);

  const expandTitle = mode === "dock" ? "Expand to full view" : "Minimize to dock";
  const ExpandIcon = mode === "dock" ? Maximize2 : Minimize2;
  const overheadColor = useMemo(() => {
    if (overheadPct == null) return null;
    if (overheadPct >= 0.4) return "#ef4444";
    if (overheadPct >= 0.2) return "#eab308";
    return null;
  }, [overheadPct]);

  const header = (
    <div
      className="flex items-center justify-between gap-2 px-3 py-2 shrink-0"
      style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
    >
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className="text-[13px] font-semibold text-text truncate shrink-0">{title}</span>
        <div className="min-w-[120px] max-w-[200px]">
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
      <div className="flex items-center gap-0.5 shrink-0">
        {overheadColor && (
          <button
            type="button"
            title={`Context overhead: ${Math.round((overheadPct ?? 0) * 100)}% of the model's window is spent on tools, skills, and system prompts`}
            className="w-2 h-2 rounded-full mx-1"
            style={{ backgroundColor: overheadColor, border: "none", cursor: "help" }}
          />
        )}
        <button
          onClick={() => setMode((m) => (m === "dock" ? "modal" : "dock"))}
          title={expandTitle}
          aria-label={expandTitle}
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
        >
          <ExpandIcon size={13} />
        </button>
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
        {sessionId ? (
          <SessionChatView
            sessionId={sessionId}
            parentChannelId={parentChannelId}
            botId={botId}
            emptyStateComponent={emptyState}
          />
        ) : (
          <div
            className="absolute inset-0 flex items-center justify-center text-text-dim text-sm px-4 text-center"
          >
            {emptyState ?? "Send a message to start the conversation"}
          </div>
        )}
      </div>
      {sendError && (
        <div className="px-4 py-1.5 text-[11px] text-red-400 border-t border-red-500/20 bg-red-500/5 shrink-0">
          {sendError}
        </div>
      )}
      <div className="shrink-0" style={{ borderTop: `1px solid ${t.surfaceBorder}` }}>
        <MessageInput
          onSend={handleSend}
          disabled={!botId}
          isStreaming={isSending}
          currentBotId={botId || undefined}
          channelId={sessionId ?? undefined}
          modelOverride={modelOverride}
          modelProviderIdOverride={modelProviderId}
          onModelOverrideChange={setModelOverride}
          defaultModel={bots?.find((b) => b.id === botId)?.model}
          configOverhead={overheadPct}
        />
      </div>
    </div>
  );

  if (mode === "modal") {
    return (
      <ChatSessionModal open={open} onClose={onClose} title={title}>
        {body}
      </ChatSessionModal>
    );
  }

  return (
    <ChatSessionDock
      open={open}
      expanded={dockExpanded}
      onExpandedChange={setDockExpanded}
      title={title}
    >
      {body}
    </ChatSessionDock>
  );
}

