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
// Ephemeral-mode (original EphemeralSession logic, preserved verbatim)
// ---------------------------------------------------------------------------

interface EphemeralChatSessionProps extends Omit<ChatSessionProps, "source"> {
  source: Extract<ChatSource, { kind: "ephemeral" }>;
}

export function EphemeralChatSession({
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
  const sessionBot = useMemo(() => bots?.find((b) => b.id === botId), [bots, botId]);
  const harnessComposerProps = useHarnessComposerProps(sessionBot, sessionId);
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
    async (message: string, files?: PendingFile[]) => {
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
        const attachmentPayload = buildChatAttachmentPayload(files);
        const workspaceUploads = attachmentPayload.workspace_uploads ?? [];
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
            ...(workspaceUploads.length ? { workspace_uploads: workspaceUploads } : {}),
          },
        });
        const result = await submitChat.mutateAsync({
          message,
          bot_id: botId,
          client_id: "web",
          session_id: activeSessionId,
          channel_id: parentChannelId,
          msg_metadata: {
            source: "web",
            sender_type: "human",
            client_local_id: clientLocalId,
            ...(workspaceUploads.length ? { workspace_uploads: workspaceUploads } : {}),
          },
          ...(attachmentPayload.attachments?.length ? { attachments: attachmentPayload.attachments } : {}),
          ...(attachmentPayload.file_metadata?.length ? { file_metadata: attachmentPayload.file_metadata } : {}),
          ...(modelOverride ? {
            model_override: modelOverride,
            model_provider_id_override: modelProviderId,
          } : {}),
        });
        if (result.queued) {
          useChatStore.getState().setProcessing(
            activeSessionId,
            result.task_id ?? result.turn_id ?? clientLocalId,
          );
        }
        qc.invalidateQueries({ queryKey: ["session-messages", activeSessionId] });
      } catch (err) {
        if (activeSessionId) {
          useChatStore.getState().clearProcessing(activeSessionId);
        }
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
  const sessionSlashCatalog = useSlashCommandList(botId || undefined);
  const sessionAvailableSlashCommands = useMemo(
    () => resolveAvailableSlashCommandIds({
      catalog: sessionSlashCatalog,
      surface: "session",
      enabled: !!sessionId,
      capabilities: onOpenSessions
        ? ["clear", "new", "model", "theme", "sessions", "split", "focus"]
        : ["clear", "new", "model", "theme"],
    }),
    [onOpenSessions, sessionId, sessionSlashCatalog],
  );
  const sessionSlashLocalHandlers = useMemo(
    () => ({
      clear: async () => {
        const channelForNew = scratchBoundChannelId ?? parentChannelId;
        if (!channelForNew) return;
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${channelForNew}/sessions`, { method: "POST" });
        qc.invalidateQueries({ queryKey: ["session-messages"] });
        navigate(`/channels/${channelForNew}/session/${result.new_session_id}`);
      },
      new: async () => {
        const channelForNew = scratchBoundChannelId ?? parentChannelId;
        if (!channelForNew) return;
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${channelForNew}/sessions`, { method: "POST" });
        qc.invalidateQueries({ queryKey: ["session-messages"] });
        navigate(`/channels/${channelForNew}/session/${result.new_session_id}`);
      },
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
    [navigate, onOpenSessionSplit, onOpenSessions, onToggleFocusLayout, parentChannelId, qc, scratchBoundChannelId, sessionModelGroups, setModelOverride],
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
      if (result.command_id === "style") {
        const channelForStyle = scratchBoundChannelId ?? parentChannelId;
        applyChatStyleSideEffect(qc, channelForStyle, result);
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
            showSessionResumeCard
            sessionResumeSeed={{
              surfaceKind: scratchBoundChannelId ? "scratch" : "session",
              title: scratchQuery.data?.title ?? title,
              summary: scratchQuery.data?.summary ?? undefined,
              createdAt: scratchQuery.data?.created_at,
              messageCount: scratchQuery.data?.message_count,
              sectionCount: scratchQuery.data?.section_count,
              botName: sessionBot?.name,
              botModel: sessionBot?.harness_runtime ? null : sessionBot?.model,
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
                    currentBotId={botId || undefined}
                    channelId={sessionId ?? undefined}
                    toolContextChannelId={scratchBoundChannelId ?? parentChannelId}
                    onSlashCommand={handleSessionSlashCommand}
                    slashSurface="session"
                    availableSlashCommands={sessionAvailableSlashCommands}
                    modelOverride={modelOverride}
                    modelProviderIdOverride={modelProviderId}
                    onModelOverrideChange={setModelOverride}
                    defaultModel={sessionBot?.model}
                    hideModelOverride={!!sessionBot?.harness_runtime}
                    {...harnessComposerProps}
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
            sessionId={sessionId}
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
                    toolContextChannelId={scratchBoundChannelId ?? parentChannelId}
                    slashSurface="session"
                    availableSlashCommands={[]}
                    modelOverride={modelOverride}
                    modelProviderIdOverride={modelProviderId}
                    onModelOverrideChange={setModelOverride}
                    defaultModel={sessionBot?.model}
                    hideModelOverride={!!sessionBot?.harness_runtime}
                    {...harnessComposerProps}
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
                toolContextChannelId={scratchBoundChannelId ?? parentChannelId}
                onSlashCommand={handleSessionSlashCommand}
                slashSurface="session"
                availableSlashCommands={sessionAvailableSlashCommands}
                modelOverride={modelOverride}
                modelProviderIdOverride={modelProviderId}
                onModelOverrideChange={setModelOverride}
                defaultModel={sessionBot?.model}
                hideModelOverride={!!sessionBot?.harness_runtime}
                {...harnessComposerProps}
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
