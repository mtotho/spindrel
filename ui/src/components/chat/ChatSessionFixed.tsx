import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { useSessionHarnessStatus } from "@/src/api/hooks/useApprovals";
import { useSpawnThread, useThreadInfo } from "@/src/api/hooks/useThreads";
import { ThreadParentAnchor } from "./ThreadParentAnchor";
import { useChannel, useChannelConfigOverhead } from "@/src/api/hooks/useChannels";
import { useChannelChatSource } from "@/src/api/hooks/useChannelChatSource";
import { useChatStore } from "@/src/stores/chat";
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
import { History, Maximize2, Minimize2, RotateCcw, Rows3, Terminal as TerminalIcon, X } from "lucide-react";
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

const TerminalPanel = lazy(() =>
  import("@/src/components/terminal/TerminalPanel").then((m) => ({ default: m.TerminalPanel })),
);

// ---------------------------------------------------------------------------
// Fixed existing-session mode
// ---------------------------------------------------------------------------

interface FixedSessionChatSessionProps extends Omit<ChatSessionProps, "source"> {
  source: Extract<ChatSource, { kind: "session" }>;
}

export function FixedSessionChatSession({
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
  const navigate = useNavigate();
  const composerInTranscriptFlow = isTranscriptFlowComposer(chatMode);
  const qc = useQueryClient();
  const { data: bots } = useBots();
  const { data: sessionModelGroups } = useModelGroups();
  const submitChat = useSubmitChat();
  const cancelChat = useCancelChat();
  const sessionId = source.sessionId;
  const parentChannelId = source.parentChannelId;
  const botId = source.botId ?? bots?.[0]?.id ?? "";
  const sessionBot = useMemo(() => bots?.find((b) => b.id === botId), [bots, botId]);
  const harnessComposerProps = useHarnessComposerProps(sessionBot, sessionId);
  // Narrow boolean read: flips at turn boundaries, NOT per text_delta.
  // Subscribing to the full channel state here would re-render this entire
  // session chat surface ~50×/sec during streaming.
  const turnActive = useChatStore(
    (s) => Object.keys(s.getChannel(sessionId).turns).length > 0,
  );
  const isSending = submitChat.isPending || turnActive;
  const [sendError, setSendError] = useState<string | null>(null);
  const [modelOverride, setModelOverrideState] = useState<string | undefined>(undefined);
  const [modelProviderId, setModelProviderId] = useState<string | null>(null);
  const { data: overheadData } = useSessionConfigOverhead(sessionId);
  const overheadPct = overheadData?.overhead_pct ?? null;
  const { sessionPlan, planBusy, handleTogglePlanMode } = useChatSessionPlan(sessionId);
  const [slashSyntheticMessages, setSlashSyntheticMessages] = useState<Message[]>([]);
  const [nativeCliOpen, setNativeCliOpen] = useState(false);
  const [nativeCliStarted, setNativeCliStarted] = useState(false);
  const [nativeCliRevision, setNativeCliRevision] = useState(0);
  const isHarnessSession = !!sessionBot?.harness_runtime;
  const { data: harnessStatus } = useSessionHarnessStatus(sessionId, isHarnessSession);
  const nativeSessionId = typeof harnessStatus?.run_inspector?.native_session_id === "string"
    ? harnessStatus.run_inspector.native_session_id
    : null;
  const nativeCliAvailable = Boolean(nativeSessionId);

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
    if (isHarnessSession && nativeCliStarted) {
      setNativeCliOpen(false);
      setNativeCliStarted(false);
      setNativeCliRevision((value) => value + 1);
    }
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
      if (result.queued) {
        useChatStore.getState().setProcessing(
          sessionId,
          result.task_id ?? result.turn_id ?? clientLocalId,
        );
      }
      qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
    } catch (err) {
      useChatStore.getState().clearProcessing(sessionId);
      setSendError(err instanceof Error ? err.message : "Failed to send message");
    }
  }, [botId, isHarnessSession, modelOverride, modelProviderId, nativeCliStarted, parentChannelId, qc, sessionId, source.externalDelivery, submitChat]);

  const handleCancel = useCallback(() => {
    cancelChat.mutate({
      client_id: "web",
      bot_id: botId,
      session_id: sessionId,
      channel_id: parentChannelId,
    });
    syncCancelledState();
  }, [botId, cancelChat, parentChannelId, sessionId, syncCancelledState]);

  const slashCatalog = useSlashCommandList(botId || undefined, sessionId);
  const availableSlashCommands = useMemo(
    () => resolveAvailableSlashCommandIds({
      catalog: slashCatalog,
      surface: "session",
      enabled: !!sessionId,
      capabilities: onOpenSessions
        ? ["clear", "new", "model", "theme", "sessions", "split", "focus"]
        : ["clear", "new", "model", "theme"],
    }),
    [onOpenSessions, sessionId, slashCatalog],
  );
  const localHandlers = useMemo(
    () => ({
      clear: async () => {
        if (!parentChannelId) return;
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${parentChannelId}/sessions`, {
          method: "POST",
          body: JSON.stringify({ source_session_id: sessionId }),
        });
        qc.invalidateQueries({ queryKey: ["session-messages"] });
        navigate(`/channels/${parentChannelId}/session/${result.new_session_id}`);
      },
      new: async () => {
        if (!parentChannelId) return;
        const result = await apiFetch<{ new_session_id: string }>(`/api/v1/channels/${parentChannelId}/sessions`, {
          method: "POST",
          body: JSON.stringify({ source_session_id: sessionId }),
        });
        qc.invalidateQueries({ queryKey: ["session-messages"] });
        navigate(`/channels/${parentChannelId}/session/${result.new_session_id}`);
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
    [navigate, onOpenSessionSplit, onOpenSessions, onToggleFocusLayout, parentChannelId, qc, sessionId, sessionModelGroups, setModelOverride],
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
      if (result.command_id === "style" && parentChannelId) {
        applyChatStyleSideEffect(qc, parentChannelId, result);
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
          currentSessionId={sessionId}
          channelId={sessionId}
          toolContextChannelId={parentChannelId}
          onSlashCommand={handleSlashCommand}
          slashSurface="session"
          availableSlashCommands={availableSlashCommands}
          modelOverride={modelOverride}
          modelProviderIdOverride={modelProviderId}
          onModelOverrideChange={setModelOverride}
          defaultModel={sessionBot?.model}
          hideModelOverride={isHarnessSession}
          {...harnessComposerProps}
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
        {isHarnessSession && !nativeCliOpen && (
          <button
            type="button"
            onClick={() => {
              setNativeCliStarted(true);
              setNativeCliOpen(true);
            }}
            disabled={isSending || !nativeCliAvailable}
            className={`absolute right-3 top-3 z-[8] inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium backdrop-blur ${
              isSending || !nativeCliAvailable
                ? "cursor-not-allowed bg-surface-overlay/50 text-text-dim/60"
                : nativeCliStarted
                  ? "bg-accent/15 text-accent hover:bg-accent/20"
                  : "bg-surface-overlay/80 text-text-dim hover:bg-surface-overlay hover:text-text"
            }`}
            title={
              isSending
                ? "Native CLI is available after the active Spindrel turn records a native session id"
                : !nativeCliAvailable
                  ? "Native CLI is unavailable until this harness session records a resumable native session id"
                : nativeCliStarted
                  ? "Return to the running native CLI for this session"
                  : "Open the runtime's native CLI for this session"
            }
            aria-pressed={nativeCliStarted}
          >
            <TerminalIcon size={13} />
            {isSending ? "CLI after turn" : !nativeCliAvailable ? "CLI unavailable" : nativeCliStarted ? "Native CLI running" : "Native CLI"}
          </button>
        )}
        <div
          className={`h-full min-h-0 ${nativeCliOpen ? "pointer-events-none opacity-0" : "opacity-100"}`}
          aria-hidden={nativeCliOpen}
        >
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
              surfaceKind: source.externalDelivery === "none" ? "channel" : "session",
              title,
              botName: sessionBot?.name,
              botModel: isHarnessSession ? null : sessionBot?.model,
            }}
            onOpenSessions={onOpenSessions}
            bottomSlot={composerInTranscriptFlow ? composer : undefined}
          />
          {!composerInTranscriptFlow && (
            <div ref={inputOverlayRef} className="absolute bottom-0 left-0 right-0 z-[4]">
              {composer}
            </div>
          )}
        </div>
        {isHarnessSession && nativeCliStarted && (
          <div
            className={`absolute inset-0 min-h-0 bg-[#0a0d12] transition-opacity ${
              nativeCliOpen ? "pointer-events-auto z-[20] opacity-100" : "pointer-events-none z-0 opacity-0"
            }`}
            aria-hidden={!nativeCliOpen}
          >
            <button
              type="button"
              onClick={() => {
                setNativeCliOpen(false);
                qc.invalidateQueries({ queryKey: ["session-harness-settings", sessionId] });
                qc.invalidateQueries({ queryKey: ["session-harness-status", sessionId] });
              }}
              className="absolute right-3 top-3 z-10 inline-flex h-7 items-center gap-1.5 rounded-md bg-surface-overlay/80 px-2 text-[11px] font-medium text-accent backdrop-blur hover:bg-surface-overlay hover:text-accent"
              title="Return to Spindrel chat"
              aria-pressed={nativeCliOpen}
            >
              <TerminalIcon size={13} />
              Spindrel chat
            </button>
            <Suspense fallback={<div className="flex h-full items-center justify-center bg-[#0a0d12] text-[12px] text-zinc-500">Starting native CLI...</div>}>
              <TerminalPanel
                key={nativeCliRevision}
                chrome="bare"
                sessionCreatePath={`/api/v1/admin/sessions/${sessionId}/harness/native-terminal`}
                className="h-full"
                onExit={() => {
                  qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
                  qc.invalidateQueries({ queryKey: ["session-harness-settings", sessionId] });
                  qc.invalidateQueries({ queryKey: ["session-harness-status", sessionId] });
                }}
              />
            </Suspense>
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
