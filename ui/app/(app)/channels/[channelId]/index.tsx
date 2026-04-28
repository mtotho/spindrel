import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useParams, useNavigate, useLocation, useMatch, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { PipelineRunModal } from "./PipelineRunModal";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ChevronUp, ChevronDown } from "lucide-react";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { OmniPanel } from "./OmniPanel";
import { WidgetDockRight } from "./WidgetDockRight";
import { MobileChannelDrawer } from "./MobileChannelDrawer";
import { ChannelFileViewer } from "./ChannelFileViewer";
import { MobileFileViewerSlide } from "./MobileFileViewerSlide";
import { ResizeHandle } from "@/src/components/workspace/ResizeHandle";
import { MessageBubble } from "@/src/components/chat/MessageBubble";
import { MessageInput } from "@/src/components/chat/MessageInput";
import { useHarnessComposerProps } from "@/src/components/chat/useHarnessComposerProps";
import { ChatComposerShell } from "@/src/components/chat/ChatComposerShell";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore, defaultChannelPanelPrefs, type OmniPanelTab } from "@/src/stores/ui";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChannel, useChannelContextBudget, useChannelConfigOverhead } from "@/src/api/hooks/useChannels";
import { useSessionHeaderStats } from "@/src/api/hooks/useSessionHeaderStats";
import { useBot } from "@/src/api/hooks/useBots";
import {
  useSessionApprovalMode,
  useSessionHarnessSettings,
  useSessionHarnessStatus,
  useSetSessionApprovalMode,
  useSetSessionHarnessSettings,
  type HarnessApprovalMode,
} from "@/src/api/hooks/useApprovals";
import { getNextHarnessApprovalMode } from "@/src/components/chat/harnessApprovalModeControl";
import { useRuntimeCapabilities } from "@/src/api/hooks/useRuntimes";
import { useSystemStatus } from "@/src/api/hooks/useSystemStatus";
import { useAuthStore } from "@/src/stores/auth";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { usePaletteActions, type PaletteAction } from "@/src/stores/paletteActions";
import { FolderOpen, Cog, Settings as SettingsIcon, PanelLeft as PanelLeftIcon, PanelRight as PanelRightIcon, LayoutDashboard as LayoutDashboardIcon, Layers, Search, Terminal as TerminalIcon } from "lucide-react";
import { SecretWarningDialog } from "@/src/components/chat/SecretWarningDialog";
import { ActiveBadgeBar } from "./ActiveBadgeBar";
import { ErrorBanner, SecretWarningBanner } from "./ChatBanners";
import { BotInfoPanel } from "@/src/components/chat/BotInfoPanel";
import { TriggerCard, SUPPORTED_TRIGGERS } from "@/src/components/chat/TriggerCard";
import { TaskRunEnvelope } from "@/src/components/chat/TaskRunEnvelope";
import { shouldGroup, formatDateSeparator, isDifferentDay, getTurnMessages, getTurnText } from "./chatUtils";
import { ChatMessageArea, DateSeparator } from "@/src/components/chat/ChatMessageArea";
import { isEditableKeyboardTarget } from "@/src/components/chat/chatKeyboard";
import { ChannelPendingApprovals } from "./ChannelPendingApprovals";
import { ChannelHeader } from "./ChannelHeader";
import { ChannelHeaderChip } from "./ChannelHeaderChip";
import { ChannelChatPaneGroup } from "./ChannelChatPaneGroup";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import {
  CHANNEL_CHAT_MIN_WIDTH,
  CHANNEL_PANEL_DEFAULT_WIDTH,
  CHANNEL_PANEL_MAX_WIDTH,
  CHANNEL_PANEL_MIN_WIDTH,
  clampChannelPanelWidth,
  resolveChannelPanelLayout,
} from "@/src/lib/channelPanelLayout";
import { OrchestratorLaunchpad } from "./OrchestratorEmptyState";
import { useChannelPipelines } from "@/src/api/hooks/useChannelPipelines";
import { useWidgetStreamBroker } from "@/src/api/hooks/useWidgetStreamBroker";
import { FindingsPanel, FindingsSheet, useFindings } from "./FindingsPanel";
import { ChatScreenSkeleton } from "./ChatScreenSkeleton";
import { useChannelChat } from "./useChannelChat";
import { useSessionPlanMode } from "./useSessionPlanMode";
import {
  useChannelSessionOverlayController,
  useChannelRouteSessionSurface,
  useChannelSessionPaneController,
} from "./useChannelSessionPaneController";
import type { Message } from "@/src/types/api";
import { ChatSession } from "@/src/components/chat/ChatSession";
import { SessionPickerOverlay } from "@/src/components/chat/SessionPickerOverlay";
import { SessionChatView } from "@/src/components/chat/SessionChatView";
import { useSessionResumeCard } from "@/src/components/chat/useSessionResumeCard";
import { buildThreadParentPreviewRow } from "@/src/components/chat/threadPreview";
import { isPendingHarnessQuestionMessage } from "@/src/components/chat/harnessQuestionMessages";
import { useSubmitChat } from "@/src/api/hooks/useChat";
import { apiFetch } from "@/src/api/client";
import { selectIsStreaming } from "@/src/stores/chat";
import {
  buildRecentHref,
  formatSessionRecentLabel,
  formatThreadRecentLabel,
  parseChannelRecentRoute,
} from "@/src/lib/recentPages";
import {
  CHANNEL_FILES_PATH_PARAM,
  CHANNEL_OPEN_FILE_PARAM,
  readChannelFileIntent,
} from "@/src/lib/channelFileNavigation";
import {
  useThreadSummaries,
  useThreadInfo,
} from "@/src/api/hooks/useThreads";
import { useMarkRead, useMarkSessionVisible } from "@/src/api/hooks/useUnread";
import { MessageCircle, StickyNote, X as CloseIcon } from "lucide-react";
import { Lock as LockIcon } from "lucide-react";

const TerminalPanel = lazy(() =>
  import("@/src/components/terminal/TerminalPanel").then((m) => ({ default: m.TerminalPanel })),
);

function readLegacyRightDockWidth(): number {
  if (typeof window === "undefined") return CHANNEL_PANEL_DEFAULT_WIDTH;
  const raw = window.localStorage.getItem("chat-dock-right-width");
  const parsed = raw ? parseInt(raw, 10) : NaN;
  return clampChannelPanelWidth(Number.isFinite(parsed) ? parsed : CHANNEL_PANEL_DEFAULT_WIDTH);
}

type PanelSpineAction = {
  id: string;
  label: string;
  hint?: string;
  icon: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  disabledReason?: string;
};

const COLLAPSED_PANEL_SPINE_WIDTH_PX = 44;
const HEADER_RAIL_EDGE_INSET_PX = 12;
const CENTER_PANEL_GUTTER_PX = 6;

/** Collapsed panel spine: the closed panel still occupies an honest slot in
 *  the row instead of relying on hidden edge hover or floating grabbers. */
function CollapsedPanelSpine({
  side,
  title,
  actions,
  statusLabel,
}: {
  side: "left" | "right";
  title: string;
  actions: PanelSpineAction[];
  statusLabel?: string;
}) {
  const t = useThemeTokens();

  return (
    <div
      role="group"
      aria-label={title}
      title={title}
      className={`flex h-full w-10 shrink-0 flex-col items-center py-2 ${side === "left" ? "mr-1" : "ml-1"}`}
      style={{ backgroundColor: t.surface, color: t.textDim }}
    >
      <div className="flex flex-col items-center gap-0.5">
        {actions.map((action) => (
          <button
            key={action.id}
            type="button"
            onClick={action.disabled ? undefined : action.onSelect}
            aria-label={action.label}
            disabled={action.disabled}
            title={
              action.disabled
                ? action.disabledReason
                  ? `${action.label} · ${action.disabledReason}`
                  : action.label
                : action.hint
                  ? `${action.label} · ${action.hint}`
                  : action.label
            }
            className="flex h-9 w-10 items-center justify-center bg-transparent text-text-dim transition-colors hover:bg-surface-overlay/70 hover:text-text focus-visible:bg-surface-overlay/70 focus-visible:text-text focus-visible:outline-none disabled:cursor-default disabled:opacity-45 disabled:hover:bg-transparent disabled:hover:text-text-dim"
          >
            {action.icon}
          </button>
        ))}
      </div>
      <div className="mt-2 flex flex-1 items-start justify-center">
        <span
          className="select-none text-[9px] font-semibold uppercase tracking-[0.18em] text-text-dim/60"
          style={{ writingMode: "vertical-rl", transform: side === "left" ? "rotate(180deg)" : undefined }}
        >
          {statusLabel ?? (side === "left" ? "Panel" : "Dock")}
        </span>
      </div>
    </div>
  );
}

export default function ChatScreen() {
  const { channelId } = useParams<{ channelId: string }>();
  const goBack = useGoBack("/");
  const navigate = useNavigate();

  const { data: channel, isLoading: channelLoading } = useChannel(channelId);
  const { data: bot } = useBot(channel?.bot_id);

  // Harness composer model picker — only fetches when bot is a harness.
  const { data: harnessCaps } = useRuntimeCapabilities(bot?.harness_runtime ?? null);
  const setHarnessSettings = useSetSessionHarnessSettings();
  const { data: systemStatus } = useSystemStatus();
  const { data: configOverheadData } = useChannelConfigOverhead(channelId);
  // Host-side broker so pinned widgets reuse the channel's SSE connection
  // instead of each opening its own /widget-actions/stream socket.
  useWidgetStreamBroker(channelId);
  const isPaused = systemStatus?.paused ?? false;
  const columns = useResponsiveColumns();
  const { width: viewportWidth } = useWindowSize();
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const showHamburger = columns === "single" || sidebarCollapsed;
  const t = useThemeTokens();

  const markChannelRead = useMarkRead();
  const markSessionVisible = useMarkSessionVisible();

  // Auto-collapse the global sidebar to its rail whenever the user enters a
  // chat. Maximises horizontal room for the centered chat column; the rail's
  // own toggle still lets the user re-expand per session.
  useEffect(() => {
    if (channelId && columns !== "single" && !sidebarCollapsed) {
      useUIStore.setState({ sidebarCollapsed: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId]);

  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);
  const loc = useLocation();
  useEffect(() => {
    if (!channel?.name) return;
    const currentHref = buildRecentHref(loc.pathname, loc.search, loc.hash);
    const parsed = parseChannelRecentRoute(currentHref);
    if (parsed?.kind === "session") {
      enrichRecentPage(currentHref, formatSessionRecentLabel(channel.name));
      return;
    }
    if (parsed?.kind === "thread") {
      enrichRecentPage(currentHref, formatThreadRecentLabel(channel.name));
      return;
    }
    enrichRecentPage(currentHref, channel.name);
  }, [channel?.name, loc.pathname, loc.search, loc.hash, enrichRecentPage]);

  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [findingsPanelOpen, setFindingsPanelOpen] = useState(false);
  const [botInfoBotId, setBotInfoBotId] = useState<string | null>(null);
  const isSystemChannel = channel?.client_id === "orchestrator:home";

  // Phase 5: launchpad + Findings visibility follows subscription state,
  // not orchestrator:home hard-coding. `pipeline_mode` on the channel
  // config can force-on or force-off.
  const pipelineMode =
    (channel?.config?.pipeline_mode as "auto" | "on" | "off" | undefined) ?? "auto";
  const { data: channelPipelinesData } = useChannelPipelines(channelId, {
    enabledOnly: true,
  });
  const hasSubscriptions =
    (channelPipelinesData?.subscriptions?.length ?? 0) > 0;
  const launchpadVisible =
    pipelineMode === "on" || (pipelineMode === "auto" && hasSubscriptions);

  // Findings count drives the ChannelHeader badge. Only wired when the
  // channel is pipeline-aware (otherwise nothing can render an awaiting-input
  // widget here).
  const { count: findingsCount } = useFindings(launchpadVisible ? channelId : undefined);
  // ---- Single-session route mode (URL-driven) ----
  // Route: /channels/:channelId/session/:sessionId?scratch=true|surface=channel
  // Swaps the main chat column with the URL-provided session. Keep this
  // above useChannelChat so the hidden primary channel transcript can stop
  // its own state/messages/SSE subscriptions while a routed session is the
  // visible chat surface.
  const channelRouteSession = useChannelRouteSessionSurface();
  const {
    routeSessionId,
    isScratchRoute,
    routeSessionSurface,
    scratchUrlSessionId,
  } = channelRouteSession;
  const channelSessionOverlay = useChannelSessionOverlayController();
  const { openSessionsOverlay, openSplitOverlay } = channelSessionOverlay;

  const {
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
  } = useChannelChat({
    channelId,
    channel,
    activeFile,
    onOpenSessions: openSessionsOverlay,
    onOpenSessionSplit: openSplitOverlay,
    enabled: !routeSessionId,
  });

  // In inverted list: index 0 = newest, index+1 = chronologically previous (older).
  // Show date separator when the current message starts a new day vs the older message above it.
  //
  // Render order matters per platform:
  // - Native (inverted FlatList): scaleY(-1) flips each cell, so DateSeparator
  //   AFTER the message in DOM ends up ABOVE it visually.
  // - Web (column layout): messages rendered chronologically, DateSeparator
  //   comes BEFORE the message in JSX and appears above it visually.
  // When a bot avatar/name is clicked in a message, show the BotInfoPanel.
  // senderBotId comes from message metadata; fall back to channel's primary bot.
  const handleBotClick = useCallback(
    (senderBotId: string | null) => {
      setBotInfoBotId(senderBotId || channel?.bot_id || null);
    },
    [channel?.bot_id],
  );

  // ---- Thread state (reply-in-thread dock) ----
  // Active thread sits in local state; dock mounts when non-null. Lazy-spawn
  // model: clicking "Reply in thread" on a message with no existing thread
  // opens the dock in a transient pending state (sessionId=null, parent
  // Message cached) so the user can close it without persisting anything.
  // On first send, ChatSession spawns via POST /messages/{id}/thread and
  // calls onSessionSpawned to lift the id back into activeThread.
  const [activeThread, setActiveThread] = useState<
    {
      sessionId: string | null;
      botId: string;
      parentMessageId: string;
      parentMessage?: Message | null;
    } | null
  >(null);

  // Visible message ids drive the batched thread-summaries fetch.
  // Limit to the rendered window to keep the query key bounded.
  // Filter out optimistic `msg-<timestamp>` ids — the endpoint expects
  // UUIDs and returns 400 on anything else (ReadError banner on the SSE
  // stream piggybacked on that failure).
  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const visibleMessageIds = useMemo(
    () =>
      invertedData
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(0, 50)
        .map((m) => m.id)
        .filter((id) => UUID_RE.test(id)),
    [invertedData],
  );
  const { data: threadSummaries } = useThreadSummaries(visibleMessageIds);

  const handleReplyInThread = useCallback(
    (messageId: string) => {
      const existing = threadSummaries?.[messageId];
      if (existing) {
        setActiveThread({
          sessionId: existing.session_id,
          botId: existing.bot_id,
          parentMessageId: messageId,
        });
        return;
      }
      // Lazy path — resolve the parent Message + inferred bot locally so
      // the dock has everything it needs to render without first hitting
      // the backend. The ChatSession controller spawns on first send.
      const parent = invertedData.find((m) => m.id === messageId) ?? null;
      if (parent == null) return;
      const meta = (parent.metadata as Record<string, unknown> | undefined) ?? {};
      const inferredBotId =
        parent.role === "assistant" && typeof meta.bot_id === "string"
          ? (meta.bot_id as string)
          : parent.role === "assistant" && typeof meta.source_bot_id === "string"
            ? (meta.source_bot_id as string)
            : channel?.bot_id;
      if (!inferredBotId) return;
      setActiveThread({
        sessionId: null,
        botId: inferredBotId,
        parentMessageId: messageId,
        parentMessage: parent,
      });
    },
    [threadSummaries, invertedData, channel?.bot_id],
  );

  const scratchSessionState = useChatStore((s) =>
    scratchUrlSessionId ? s.getChannel(scratchUrlSessionId) : null,
  );
  const currentBudgetSessionId = routeSessionId ?? channel?.active_session_id ?? null;
  useEffect(() => {
    const visibleSessionId = routeSessionId ?? channel?.active_session_id ?? null;
    if (visibleSessionId) {
      markSessionVisible.mutate({
        session_id: visibleSessionId,
        surface: routeSessionId ? "session_route" : "channel_primary",
        mark_read: true,
      });
      return;
    }
    if (channelId) {
      markChannelRead.mutate({
        channel_id: channelId,
        source: "web_channel_open",
        surface: "channel",
      });
    }
  }, [channelId, channel?.active_session_id, routeSessionId]);
  const { data: savedBudget } = useChannelContextBudget(channelId, currentBudgetSessionId);
  const { data: sessionHeaderStats } = useSessionHeaderStats(channelId, currentBudgetSessionId);

  const channelDashboardHref = useMemo(() => {
    if (!channelId) return "/widgets";
    const qs = new URLSearchParams();
    if (isScratchRoute && scratchUrlSessionId) {
      qs.set("scratch_session_id", scratchUrlSessionId);
    }
    if (new URLSearchParams(loc.search).get("edit") === "true") {
      qs.set("edit", "true");
    }
    const suffix = qs.toString();
    return `/widgets/channel/${channelId}${suffix ? `?${suffix}` : ""}`;
  }, [channelId, isScratchRoute, scratchUrlSessionId, loc.search]);

  const effectiveContextBudget = (
    currentBudgetSessionId
      ? scratchSessionState?.contextBudget
      : chatState.contextBudget
  ) ?? (
    savedBudget?.utilization != null ? {
      utilization: savedBudget.utilization,
      consumed: savedBudget.consumed_tokens ?? 0,
      total: savedBudget.total_tokens ?? 0,
      gross: savedBudget.gross_prompt_tokens ?? savedBudget.consumed_tokens ?? 0,
      current: savedBudget.current_prompt_tokens ?? savedBudget.gross_prompt_tokens ?? savedBudget.consumed_tokens ?? 0,
      cached: savedBudget.cached_prompt_tokens ?? undefined,
      contextProfile: savedBudget.context_profile ?? undefined,
    } : null
  );

  const handleSetActiveThreadSpawned = useCallback(
    (sid: string) =>
      setActiveThread((curr) => (curr ? { ...curr, sessionId: sid } : curr)),
    [],
  );
  const handleClearActiveThread = useCallback(() => setActiveThread(null), []);

  const threadSource = useMemo(
    () =>
      activeThread && channelId
        ? ({
            kind: "thread" as const,
            threadSessionId: activeThread.sessionId,
            parentChannelId: channelId,
            parentMessageId: activeThread.parentMessageId,
            botId: activeThread.botId,
            parentMessage: activeThread.parentMessage ?? null,
            onSessionSpawned: handleSetActiveThreadSpawned,
          })
        : null,
    [
      activeThread,
      channelId,
      handleSetActiveThreadSpawned,
    ],
  );

  // Pipeline anchors dedupe visually: when multiple runs of the same
  // definition exist in the channel, only the latest stays fully expanded.
  // Older ones collapse to a one-line header. Grouping key is
  // (parent_task_id || title) — definition-row churn (YAML reload → new
  // Task id) would otherwise leave two parents showing as "latest" for
  // the same human-facing pipeline. Title catches that.
  const latestAnchorByGroup = useMemo(() => {
    const latestMessageIds = new Set<string>();
    const seenGroups = new Set<string>();
    for (const m of invertedData) {
      const meta = (m.metadata ?? {}) as Record<string, any>;
      if (meta.kind !== "task_run") continue;
      const groupKey =
        (meta.parent_task_id as string | null | undefined) ||
        (meta.title as string | null | undefined) ||
        m.id; // fallback: self → always latest
      if (!seenGroups.has(groupKey)) {
        seenGroups.add(groupKey);
        latestMessageIds.add(m.id);
      }
    }
    return latestMessageIds;
  }, [invertedData]);
  const layoutMode = (channel?.config?.layout_mode ?? "full") as
    | "full" | "rail-header-chat" | "rail-chat" | "dashboard-only";
  const chatMode = ((channel?.config?.chat_mode ?? "default") as "default" | "terminal");
  const currentPlanSessionId = routeSessionId ?? channel?.active_session_id ?? undefined;
  const queryClient = useQueryClient();
  const sessionPlan = useSessionPlanMode(currentPlanSessionId);
  const { data: harnessStatus } = useSessionHarnessStatus(bot?.harness_runtime ? currentPlanSessionId : null);
  const [dismissedAutoCompactSession, setDismissedAutoCompactSession] = useState<string | null>(null);
  const [autoCompactRunning, setAutoCompactRunning] = useState(false);
  const autoCompactConfig = (channel?.config as any)?.harness_auto_compaction ?? {};
  const autoCompactEnabled = autoCompactConfig.enabled ?? channel?.config?.harness_auto_compaction_enabled ?? true;
  const autoCompactSoft = autoCompactConfig.soft_remaining_pct ?? channel?.config?.harness_auto_compaction_soft_remaining_pct ?? 60;
  const autoCompactHard = autoCompactConfig.hard_remaining_pct ?? channel?.config?.harness_auto_compaction_hard_remaining_pct ?? 10;
  const remainingPct = harnessStatus?.context_remaining_pct;
  const contextConfidence = typeof harnessStatus?.context_diagnostics?.confidence === "string"
    ? harnessStatus.context_diagnostics.confidence
    : null;
  const contextEstimateActionable = contextConfidence === "high" || contextConfidence === "medium";
  const autoCompactPressure = bot?.harness_runtime
    && autoCompactEnabled
    && typeof remainingPct === "number"
    && contextEstimateActionable
    && currentPlanSessionId
    && dismissedAutoCompactSession !== currentPlanSessionId
    ? (remainingPct < autoCompactHard ? "hard" : remainingPct < autoCompactSoft ? "soft" : null)
    : null;
  const triggerNativeCompact = useCallback(async () => {
    if (!currentPlanSessionId) return;
    setAutoCompactRunning(true);
    try {
      await apiFetch("/api/v1/slash-commands/execute", {
        method: "POST",
        body: JSON.stringify({
          command_id: "compact",
          session_id: currentPlanSessionId,
          surface: "session",
          args: [],
        }),
      });
      setDismissedAutoCompactSession(currentPlanSessionId);
      void queryClient.invalidateQueries({ queryKey: ["session-messages", currentPlanSessionId] });
      void queryClient.invalidateQueries({ queryKey: ["session-harness-status", currentPlanSessionId] });
    } finally {
      setAutoCompactRunning(false);
    }
  }, [currentPlanSessionId, queryClient]);
  const openNewVisibleSession = useCallback(async () => {
    if (!channelId) return;
    const result = await apiFetch<{ new_session_id: string }>(`/channels/${channelId}/sessions`, { method: "POST" });
    setDismissedAutoCompactSession(result.new_session_id);
    void queryClient.invalidateQueries({ queryKey: ["session-messages"] });
    navigate(`/channels/${channelId}/session/${result.new_session_id}`);
  }, [channelId, navigate, queryClient]);
  const disableAutoCompactionPrompts = useCallback(async () => {
    if (!channelId) return;
    await apiFetch(`/api/v1/admin/channels/${channelId}/settings`, {
      method: "PUT",
      body: JSON.stringify({ harness_auto_compaction_enabled: false }),
    });
    setDismissedAutoCompactSession(currentPlanSessionId ?? null);
    void queryClient.invalidateQueries({ queryKey: ["channel", channelId] });
    void queryClient.invalidateQueries({ queryKey: ["channel-settings", channelId] });
  }, [channelId, currentPlanSessionId, queryClient]);
  const [ignoredHarnessQuestionIds, setIgnoredHarnessQuestionIds] = useState<Set<string>>(() => new Set());
  const pendingHarnessQuestionIndex = useMemo(() => {
    const targetSessionId = currentPlanSessionId ?? channel?.active_session_id;
    return invertedData.findIndex((m) => {
      return isPendingHarnessQuestionMessage(m, {
        sessionId: targetSessionId,
        ignoredIds: ignoredHarnessQuestionIds,
      });
    });
  }, [channel?.active_session_id, currentPlanSessionId, ignoredHarnessQuestionIds, invertedData]);
  const pendingHarnessQuestion = pendingHarnessQuestionIndex >= 0
    ? invertedData[pendingHarnessQuestionIndex]
    : null;
  const visibleInvertedData = useMemo(
    () => chatMode === "terminal" && pendingHarnessQuestion
      ? invertedData.filter((m) => m.id !== pendingHarnessQuestion.id)
      : invertedData,
    [chatMode, invertedData, pendingHarnessQuestion],
  );
  const handleIgnoreHarnessQuestion = useCallback(async () => {
    if (!pendingHarnessQuestion?.session_id) return;
    const questionId = pendingHarnessQuestion.id;
    setIgnoredHarnessQuestionIds((prev) => new Set(prev).add(questionId));
    try {
      await apiFetch(`/api/v1/sessions/${pendingHarnessQuestion.session_id}/harness-interactions/${questionId}/cancel`, {
        method: "POST",
      });
      void queryClient.invalidateQueries({ queryKey: ["session-messages", pendingHarnessQuestion.session_id] });
    } catch {
      // Keep the local dismissal: this path is also used for cards that are
      // already expired server-side but have stale metadata in the current view.
    }
  }, [pendingHarnessQuestion, queryClient]);
  const setApprovalMode = useSetSessionApprovalMode();
  const harnessApprovalBeforePlanRef = useRef<HarnessApprovalMode | null>(null);
  const planBusy = sessionPlan.startPlan.isPending
    || sessionPlan.approvePlan.isPending
    || sessionPlan.exitPlan.isPending
    || sessionPlan.resumePlan.isPending
    || setApprovalMode.isPending
    || sessionPlan.updateStepStatus.isPending;

  const handleTogglePlanMode = useCallback(() => {
    if (!currentPlanSessionId) return;
    if (sessionPlan.mode !== "chat") {
      sessionPlan.exitPlan.mutate();
      if (bot?.harness_runtime && harnessStatus?.permission_mode === "plan") {
        setApprovalMode.mutate({
          sessionId: currentPlanSessionId,
          mode: harnessApprovalBeforePlanRef.current || "bypassPermissions",
        });
        harnessApprovalBeforePlanRef.current = null;
      }
      return;
    }
    if (bot?.harness_runtime) {
      harnessApprovalBeforePlanRef.current = harnessStatus?.permission_mode && harnessStatus.permission_mode !== "plan"
        ? (harnessStatus.permission_mode as HarnessApprovalMode)
        : "bypassPermissions";
      setApprovalMode.mutate({ sessionId: currentPlanSessionId, mode: "plan" });
    }
    if (sessionPlan.hasPlan) {
      sessionPlan.resumePlan.mutate();
      return;
    }
    sessionPlan.startPlan.mutate();
  }, [bot?.harness_runtime, currentPlanSessionId, harnessStatus?.permission_mode, sessionPlan, setApprovalMode]);

  useEffect(() => {
    if (!bot?.harness_runtime || !currentPlanSessionId) return;
    if (sessionPlan.mode !== "chat") return;
    if (harnessApprovalBeforePlanRef.current && harnessStatus?.permission_mode === "plan" && !setApprovalMode.isPending) {
      setApprovalMode.mutate({
        sessionId: currentPlanSessionId,
        mode: harnessApprovalBeforePlanRef.current,
      });
      harnessApprovalBeforePlanRef.current = null;
    }
  }, [bot?.harness_runtime, currentPlanSessionId, harnessStatus?.permission_mode, sessionPlan.mode, setApprovalMode]);

  const renderMessage = useCallback(
    ({ item, index }: { item: Message; index: number }) => {
      const prevMsg = invertedData[index + 1];
      const grouped = shouldGroup(item, prevMsg);
      const showDateSep = index === invertedData.length - 1 || (prevMsg && isDifferentDay(item.created_at, prevMsg.created_at));
      const dateSep = showDateSep ? <DateSeparator label={formatDateSeparator(item.created_at)} /> : null;
      const meta = (item.metadata ?? {}) as Record<string, any>;
      if (meta.kind === "task_run") {
        const collapsedByDefault = !latestAnchorByGroup.has(item.id);
        return <>{dateSep}<TaskRunEnvelope message={item} collapsedByDefault={collapsedByDefault} /></>;
      }
      if (item.role === "user" && meta.trigger && SUPPORTED_TRIGGERS.has(meta.trigger)) {
        const card = <TriggerCard message={item} botName={bot?.name} />;
        return <>{dateSep}{card}</>;
      }
      const isGrouped = showDateSep ? false : grouped;
      // Find turn header index (walk toward older messages to find the non-grouped start)
      let headerIdx = index;
      while (headerIdx < invertedData.length - 1 && shouldGroup(invertedData[headerIdx], invertedData[headerIdx + 1])) {
        headerIdx++;
      }
      const fullTurnMessages = getTurnMessages(invertedData, headerIdx);
      const fullTurnText = getTurnText(invertedData, headerIdx);
      const isLatestBotMessage = item.role === "assistant" && index === 0;
      const threadSummary = threadSummaries?.[item.id] ?? null;
      const bubble = <MessageBubble message={item} botName={bot?.name} isGrouped={isGrouped} onBotClick={handleBotClick} fullTurnText={fullTurnText} fullTurnMessages={fullTurnMessages} channelId={channelId} isLatestBotMessage={isLatestBotMessage} isMobile={columns === "single"} threadSummary={threadSummary} onReplyInThread={handleReplyInThread} canReplyInThread={true} chatMode={chatMode} />;
      return <>{dateSep}{bubble}</>;
    },
    [invertedData, bot?.name, handleBotClick, channelId, latestAnchorByGroup, columns, threadSummaries, handleReplyInThread, chatMode]
  );

  // ---- Workspace / file explorer state ----
  const workspaceId = channel?.resolved_workspace_id;
  const projectPath = typeof channel?.config?.project_path === "string"
    ? channel.config.project_path.replace(/^\/+|\/+$/g, "")
    : "";
  const projectWorkspaceId = typeof channel?.config?.project_workspace_id === "string"
    ? channel.config.project_workspace_id
    : undefined;
  const fileWorkspaceId = projectWorkspaceId || workspaceId;
  const fileRootPath = projectPath ? `/${projectPath}` : undefined;
  const [terminalRequest, setTerminalRequest] = useState<{ cwd: string; label: string } | null>(null);
  const buildWorkspaceTerminalCwd = useCallback((workspaceRelativePath?: string | null) => {
    if (!fileWorkspaceId) return null;
    const trimmed = (workspaceRelativePath || fileRootPath || `/channels/${channelId}`).replace(/^\/+|\/+$/g, "");
    return `workspace://${fileWorkspaceId}${trimmed ? `/${trimmed}` : ""}`;
  }, [channelId, fileRootPath, fileWorkspaceId]);
  const openTerminalAtPath = useCallback((workspaceRelativePath?: string | null) => {
    const cwd = buildWorkspaceTerminalCwd(workspaceRelativePath);
    if (!cwd) return;
    const labelRaw = workspaceRelativePath || fileRootPath || `/channels/${channelId}`;
    const labelPath = labelRaw.startsWith("/") ? labelRaw : `/${labelRaw}`;
    setTerminalRequest({
      cwd,
      label: labelPath || "/",
    });
  }, [buildWorkspaceTerminalCwd, channelId, fileRootPath]);
  const explorerWidth = useFileBrowserStore((s) => s.channelExplorerWidth);
  const setRememberedChannelPath = useFileBrowserStore((s) => s.setChannelExplorerPath);
  const legacyExplorerOpen = useUIStore((s) => s.fileExplorerOpen);
  const legacyOmniPanelTab = useUIStore((s) => s.omniPanelTab);
  const ensureChannelPanelPrefs = useUIStore((s) => s.ensureChannelPanelPrefs);
  const patchChannelPanelPrefs = useUIStore((s) => s.patchChannelPanelPrefs);
  const setChannelPanelTab = useUIStore((s) => s.setChannelPanelTab);
  const requestChannelFilesFocus = useUIStore((s) => s.requestChannelFilesFocus);
  const setMobileDrawerOpen = useUIStore((s) => s.setMobileDrawerOpen);
  const setMobileExpandedWidget = useUIStore((s) => s.setMobileExpandedWidget);
  const channelPanelPrefs = useUIStore((s) =>
    channelId ? s.channelPanelPrefs[channelId] : undefined,
  );
  const splitMode = useUIStore((s) => s.fileExplorerSplit);
  const setSplitMode = useUIStore((s) => s.setFileExplorerSplit);
  const toggleSplit = useUIStore((s) => s.toggleFileExplorerSplit);
  const legacyRightDockHidden = useUIStore((s) => s.rightDockHidden);
  const isMobile = columns === "single";
  const fileDirtyRef = useRef(false);
  const channelPanelDefaults = useMemo(() => ({
    ...defaultChannelPanelPrefs(),
    leftOpen: legacyExplorerOpen,
    rightOpen: !legacyRightDockHidden,
    leftWidth: explorerWidth,
    rightWidth: readLegacyRightDockWidth(),
    leftTab: legacyOmniPanelTab,
  }), [explorerWidth, legacyExplorerOpen, legacyOmniPanelTab, legacyRightDockHidden]);
  useEffect(() => {
    if (!channelId) return;
    ensureChannelPanelPrefs(channelId, channelPanelDefaults);
  }, [channelId, channelPanelDefaults, ensureChannelPanelPrefs]);
  const panelPrefs = channelPanelPrefs ?? channelPanelDefaults;
  const {
    scratchSource,
    scratchOpen,
    handleScratchClose,
    sessionsOverlayOpen,
    setSessionsOverlayOpen,
    sessionsOverlayMode,
    pendingSplitSurface,
    setPendingSplitSurface,
    channelSessionCatalog,
    miniPaneSource,
    miniPaneLabel,
    handleCloseMiniPane,
    restoreMiniPane,
    visibleChatPanes,
    canvasActive,
    headerPaneSessionId,
    headerPaneMeta,
    channelHeaderChromeMode,
    headerBudgetSessionId,
    selectedPickerSessionId,
    pickerHiddenSurfaces,
    focusPane,
    closePane,
    maximizePane,
    restorePanes,
    minimizePane,
    movePane,
    commitPaneWidths,
    activateChannelSessionSurface,
    handleOpenFindResultSession,
    replacePaneWithPendingSplit,
    makePanePrimary,
    handleExitSessionRoute,
    routeSessionSource,
  } = useChannelSessionPaneController({
    channelId,
    channel,
    routeSession: channelRouteSession,
    overlay: channelSessionOverlay,
    panelPrefs,
    patchChannelPanelPrefs,
    isMobile,
    setActiveFile,
  });
  const { data: harnessSettings } = useSessionHarnessSettings(
    bot?.harness_runtime ? headerPaneSessionId : null,
  );
  const { data: sessionApprovalMode } = useSessionApprovalMode(
    bot?.harness_runtime ? headerPaneSessionId : null,
  );
  const handleCycleHarnessApprovalMode = useCallback(() => {
    if (!bot?.harness_runtime || !headerPaneSessionId || setApprovalMode.isPending) return;
    const nextMode = getNextHarnessApprovalMode(sessionApprovalMode?.mode);
    setApprovalMode.mutate({
      sessionId: headerPaneSessionId,
      mode: nextMode,
    });
  }, [
    bot?.harness_runtime,
    headerPaneSessionId,
    sessionApprovalMode?.mode,
    setApprovalMode,
  ]);
  const { data: headerSavedBudget } = useChannelContextBudget(
    channelHeaderChromeMode !== "canvas" ? channelId : undefined,
    headerBudgetSessionId,
  );
  const { data: headerSessionStats } = useSessionHeaderStats(
    channelHeaderChromeMode !== "canvas" ? channelId : undefined,
    headerBudgetSessionId,
  );
  const headerPaneChatState = useChatStore((s) =>
    headerBudgetSessionId ? s.getChannel(headerBudgetSessionId) : null,
  );
  const headerContextBudget = channelHeaderChromeMode !== "canvas"
    ? (headerBudgetSessionId ? headerPaneChatState?.contextBudget : chatState.contextBudget) ?? (
        headerSavedBudget?.utilization != null ? {
          utilization: headerSavedBudget.utilization,
          consumed: headerSavedBudget.consumed_tokens ?? 0,
          total: headerSavedBudget.total_tokens ?? 0,
          gross: headerSavedBudget.gross_prompt_tokens ?? headerSavedBudget.consumed_tokens ?? 0,
          current: headerSavedBudget.current_prompt_tokens ?? headerSavedBudget.gross_prompt_tokens ?? headerSavedBudget.consumed_tokens ?? 0,
          cached: headerSavedBudget.cached_prompt_tokens ?? undefined,
          contextProfile: headerSavedBudget.context_profile ?? undefined,
        } : null
      )
    : null;
  const openLeftPanelTab = useCallback((tab: OmniPanelTab) => {
    if (!channelId) return;
    if (tab === "files") {
      requestChannelFilesFocus(channelId);
      return;
    }
    patchChannelPanelPrefs(channelId, {
      leftOpen: true,
      mobileDrawerOpen: isMobile,
      leftTab: tab,
      focusModePrior: null,
    });
  }, [channelId, isMobile, patchChannelPanelPrefs, requestChannelFilesFocus]);
  const toggleExplorer = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => current.leftOpen
      ? { leftOpen: false }
      : { leftOpen: true, leftTab: current.leftTab, focusModePrior: null });
  }, [channelId, patchChannelPanelPrefs]);

  // `?from=dock` — dashboard's Open-chat toggle cues an entrance animation
  // that visually reverses the chat-dock-expand-in motion (scales up from
  // the bottom-right where the dock lived). Read once on mount, scrub the
  // param so a refresh doesn't replay.
  const [searchParams, setSearchParams] = useSearchParams();
  const [enteringFromDock] = useState(() => searchParams.get("from") === "dock");
  useEffect(() => {
    if (searchParams.get("from") === "dock") {
      const next = new URLSearchParams(searchParams);
      next.delete("from");
      setSearchParams(next, { replace: true });
    }
    // Mount-only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Flip the animation class off once the animation window has elapsed so
  // subsequent state updates don't re-run it.
  const [entranceClassActive, setEntranceClassActive] = useState(enteringFromDock);
  useEffect(() => {
    if (!enteringFromDock) return;
    const timer = window.setTimeout(() => setEntranceClassActive(false), 360);
    return () => window.clearTimeout(timer);
  }, [enteringFromDock]);
  // Header-zone pins — read here so the floating strip below the header
  // renders only when there's something to show (empty translucent pill is
  // visual noise).
  const { rail: railPins, header: headerChipPins, dock: dockPins } = useChannelChatZones(channelId ?? "");
  const hasHeaderChips = headerChipPins.length > 0;

  // "Browse files" gesture — opens the OmniPanel on the Files tab and
  // auto-focuses its filter input. Replaces the old BrowseFilesModal.
  const openBrowseFiles = useCallback(() => {
    if (!channelId) return;
    requestChannelFilesFocus(channelId);
  }, [channelId, requestChannelFilesFocus]);
  const toggleRightDockPanel = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      rightOpen: !current.rightOpen,
      focusModePrior: null,
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const focusOrRestorePanels = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => {
      if (current.leftOpen || current.rightOpen || !current.topChromeCollapsed) {
        return {
          focusModePrior: {
            leftOpen: current.leftOpen,
            rightOpen: current.rightOpen,
            topChromeCollapsed: current.topChromeCollapsed,
          },
          leftOpen: false,
          rightOpen: false,
          topChromeCollapsed: true,
        };
      }
      return {
        leftOpen: current.focusModePrior?.leftOpen ?? true,
        rightOpen: current.focusModePrior?.rightOpen ?? (dockPins.length > 0),
        topChromeCollapsed: current.focusModePrior?.topChromeCollapsed ?? false,
        focusModePrior: null,
      };
    });
  }, [channelId, dockPins.length, patchChannelPanelPrefs]);
  useEffect(() => {
    const handler = () => focusOrRestorePanels();
    window.addEventListener("spindrel:channel-focus-layout", handler);
    return () => window.removeEventListener("spindrel:channel-focus-layout", handler);
  }, [focusOrRestorePanels]);

  // Keyboard shortcuts for explorer/split/file viewer/browse
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isEditableKeyboardTarget(e.target)) return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.altKey && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        focusOrRestorePanels();
        return;
      }
      // Cmd+Shift+B → Browse files (OmniPanel Files tab + focus filter).
      // Check before the plain Cmd+B branch since `e.key` is just "b" either way.
      if (mod && e.shiftKey && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        if (channelId) requestChannelFilesFocus(channelId);
        return;
      }
      if (mod && !e.shiftKey && e.key === "b") {
        e.preventDefault();
        toggleExplorer();
        return;
      }
      if (mod && e.key === "\\") {
        e.preventDefault();
        toggleSplit();
        return;
      }
      if (e.key === "Escape" && activeFile) {
        setActiveFile(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleExplorer, toggleSplit, activeFile, channelId, requestChannelFilesFocus, focusOrRestorePanels]);

  // Reset file selection when switching channels
  useEffect(() => {
    setActiveFile(null);
    fileDirtyRef.current = false;
    setSplitMode(false);
  }, [channelId, setSplitMode]);

  // OmniPanel is always available — it shows pinned widgets even without a workspace.
  // The file explorer section inside OmniPanel is conditionally shown when workspaceId exists.
  const showFileViewer = activeFile !== null;
  // Chat-screen layout mode. Controls which dashboard zones surface on the
  // chat screen itself. Mobile drawer always shows every zone regardless.
  const showRailZone = layoutMode !== "dashboard-only";
  const showHeaderChips = layoutMode === "full" || layoutMode === "rail-header-chat";
  const showDockZone = layoutMode === "full";
  const dashboardOnly = layoutMode === "dashboard-only";
  const dockBlockedByFileViewer = showFileViewer && !splitMode;
  const panelLayout = resolveChannelPanelLayout({
    availableWidth: viewportWidth || 0,
    isMobile,
    layoutMode,
    hasLeftPanel: !!channelId && !isSystemChannel && showRailZone,
    hasRightPanel: !!channelId && !isSystemChannel && showDockZone && dockPins.length > 0 && !dockBlockedByFileViewer,
    leftOpen: panelPrefs.leftOpen,
    rightOpen: panelPrefs.rightOpen,
    leftPinned: panelPrefs.leftPinned,
    rightPinned: panelPrefs.rightPinned,
    leftWidth: panelPrefs.leftWidth,
    rightWidth: panelPrefs.rightWidth,
  });
  const showExplorer = isMobile
    ? panelPrefs.mobileDrawerOpen
    : panelLayout.left.mode !== "closed";
  const showRightDock = !isMobile && panelLayout.right.mode !== "closed";
  const overlayPanelOpen = panelLayout.left.mode === "overlay" || panelLayout.right.mode === "overlay";
  const panelResizeMax = useCallback((side: "left" | "right") => {
    const panelMode = side === "left" ? panelLayout.left.mode : panelLayout.right.mode;
    if (panelMode !== "push") return CHANNEL_PANEL_MAX_WIDTH;
    const viewport = viewportWidth || CHANNEL_CHAT_MIN_WIDTH + CHANNEL_PANEL_MAX_WIDTH;
    const otherPushedWidth =
      side === "left"
        ? (panelLayout.right.mode === "push" ? panelLayout.right.width : 0)
        : (panelLayout.left.mode === "push" ? panelLayout.left.width : 0);
    const safeWidth = viewport - CHANNEL_CHAT_MIN_WIDTH - otherPushedWidth - 40;
    return Math.max(
      CHANNEL_PANEL_MIN_WIDTH,
      Math.min(CHANNEL_PANEL_MAX_WIDTH, safeWidth),
    );
  }, [panelLayout.left.mode, panelLayout.left.width, panelLayout.right.mode, panelLayout.right.width, viewportWidth]);
  const leftPanelResizeMax = panelResizeMax("left");
  const rightPanelResizeMax = panelResizeMax("right");
  const closeOverlayPanels = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, {
      ...(panelLayout.left.mode === "overlay" ? { leftOpen: false } : {}),
      ...(panelLayout.right.mode === "overlay" ? { rightOpen: false } : {}),
    });
  }, [channelId, panelLayout.left.mode, panelLayout.right.mode, patchChannelPanelPrefs]);
  useEffect(() => {
    if (!overlayPanelOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (isEditableKeyboardTarget(e.target)) return;
      closeOverlayPanels();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [closeOverlayPanels, overlayPanelOpen]);
  const leftSpineActions = useMemo<PanelSpineAction[]>(() => {
    const actions: PanelSpineAction[] = [
      {
        id: "widgets",
        label: "Widgets",
        hint: railPins.length > 0 ? String(railPins.length) : undefined,
        icon: <Layers size={15} />,
        onSelect: () => openLeftPanelTab("widgets"),
      },
    ];
    if (fileWorkspaceId) {
      actions.push({
        id: "files",
        label: "Files",
        icon: <FolderOpen size={15} />,
        onSelect: () => openLeftPanelTab("files"),
      });
    }
    actions.push({
      id: "jump",
      label: "Jump",
      icon: <Search size={15} />,
      onSelect: () => openLeftPanelTab("jump"),
    });
    return actions;
  }, [fileWorkspaceId, openLeftPanelTab, railPins.length]);
  const rightSpineActions = useMemo<PanelSpineAction[]>(() => [
    {
      id: "dock",
      label: "Dock",
      hint: dockBlockedByFileViewer ? undefined : (dockPins.length > 0 ? String(dockPins.length) : undefined),
      icon: dockBlockedByFileViewer ? <LockIcon size={14} /> : <PanelRightIcon size={15} />,
      onSelect: () => patchChannelPanelPrefs(channelId!, { rightOpen: true, focusModePrior: null }),
      disabled: dockBlockedByFileViewer,
      disabledReason: dockBlockedByFileViewer ? "Close file or enter split view to open dock." : undefined,
    },
  ], [channelId, dockBlockedByFileViewer, dockPins.length, patchChannelPanelPrefs]);

  // Dirty-file guard: instead of window.confirm, use a ConfirmDialog
  type DirtyAction = { type: "select"; path: string } | { type: "close" } | { type: "closePanel" };
  const [pendingDirtyAction, setPendingDirtyAction] = useState<DirtyAction | null>(null);

  const tryOrConfirmDirty = useCallback((action: DirtyAction) => {
    if (!fileDirtyRef.current) return action; // not dirty, proceed immediately
    setPendingDirtyAction(action);
    return null; // blocked, waiting for confirm
  }, []);

  const executeDirtyAction = useCallback((action: DirtyAction) => {
    switch (action.type) {
      case "select":
        if (channelId && isMobile) setMobileDrawerOpen(channelId, false);
        setActiveFile(action.path);
        break;
      case "close":
        setActiveFile(null);
        setSplitMode(false);
        break;
      case "closePanel":
        if (channelId) {
          if (isMobile) setMobileDrawerOpen(channelId, false);
          else patchChannelPanelPrefs(channelId, { leftOpen: false });
        }
        break;
    }
  }, [channelId, isMobile, patchChannelPanelPrefs, setMobileDrawerOpen, setSplitMode]);

  const handleDirtyChange = useCallback((dirty: boolean) => {
    fileDirtyRef.current = dirty;
  }, []);

  const handleSelectFile = useCallback((path: string) => {
    if (path === activeFile) return;
    const action: DirtyAction = { type: "select", path };
    if (!fileDirtyRef.current) { executeDirtyAction(action); return; }
    setPendingDirtyAction(action);
  }, [activeFile, executeDirtyAction]);

  useEffect(() => {
    if (!channelId) return;
    const intent = readChannelFileIntent(searchParams, channelId);
    if (!intent) return;
    patchChannelPanelPrefs(channelId, {
      leftOpen: true,
      mobileDrawerOpen: true,
      leftTab: "files",
    });
    setRememberedChannelPath(channelId, `/${intent.directoryPath}`);
    if (intent.openFile) {
      handleSelectFile(intent.openFile);
    }
    const next = new URLSearchParams(searchParams);
    next.delete(CHANNEL_FILES_PATH_PARAM);
    next.delete(CHANNEL_OPEN_FILE_PARAM);
    setSearchParams(next, { replace: true });
  }, [
    channelId,
    handleSelectFile,
    patchChannelPanelPrefs,
    searchParams,
    setRememberedChannelPath,
    setSearchParams,
  ]);

  const handleCloseFile = useCallback(() => {
    const action: DirtyAction = { type: "close" };
    if (!fileDirtyRef.current) { executeDirtyAction(action); return; }
    setPendingDirtyAction(action);
  }, [executeDirtyAction]);

  const handleCloseExplorer = useCallback(() => {
    const action: DirtyAction = { type: "closePanel" };
    executeDirtyAction(action);
  }, [executeDirtyAction]);

  // Mobile: back from file viewer goes to explorer, back from explorer goes to chat
  const handleMobileBack = useCallback(() => {
    if (activeFile) {
      setActiveFile(null);
    } else {
      if (channelId) setMobileDrawerOpen(channelId, false);
    }
  }, [activeFile, channelId, setMobileDrawerOpen]);

  const displayName = (channel as any)?.display_name || channel?.name || channel?.client_id || "Chat";

  // ---- Command-palette actions scoped to this channel ---------------------
  // Registered via a runtime store so the global CommandPalette can surface
  // channel-contextual commands (Browse files, View bot context, etc.) under
  // a dedicated "This Channel" section without any navigation detour.
  const registerPaletteActions = usePaletteActions((s) => s.register);
  useEffect(() => {
    if (!channelId) return;
    const channelLabel = displayName ? `#${displayName}` : undefined;
    const actions: PaletteAction[] = [];

    if (fileWorkspaceId && !isSystemChannel) {
      actions.push({
        id: `channel:${channelId}:browse-files`,
        label: "Browse files in this channel",
        hint: channelLabel,
        icon: FolderOpen,
        category: "This Channel",
        onSelect: () => openBrowseFiles(),
      });
      actions.push({
        id: `channel:${channelId}:open-terminal`,
        label: projectPath ? "Open terminal in project" : "Open terminal in channel workspace",
        hint: projectPath ? `/${projectPath}` : channelLabel,
        icon: TerminalIcon,
        category: "This Channel",
        onSelect: () => openTerminalAtPath(fileRootPath || `/channels/${channelId}`),
      });
    }

    if (!isSystemChannel) {
      actions.push({
        id: `channel:${channelId}:switch-sessions`,
        label: "Switch sessions",
        hint: channelLabel,
        icon: MessageCircle,
        category: "This Channel",
        onSelect: () => openSessionsOverlay(),
      });
      actions.push({
        id: `channel:${channelId}:new-session`,
        label: "New session",
        hint: channelLabel,
        icon: StickyNote,
        category: "This Channel",
        onSelect: () => openSessionsOverlay(),
      });
      actions.push({
        id: `channel:${channelId}:add-session-split`,
        label: "Add session split",
        hint: channelLabel,
        icon: Layers,
        category: "This Channel",
        onSelect: () => openSplitOverlay(),
      });
      actions.push({
        id: `channel:${channelId}:open-widgets`,
        label: "Open panel: Widgets",
        hint: railPins.length > 0 ? `${railPins.length} widget${railPins.length === 1 ? "" : "s"}` : channelLabel,
        icon: PanelLeftIcon,
        category: "This Channel",
        onSelect: () => openLeftPanelTab("widgets"),
      });
      if (fileWorkspaceId) {
        actions.push({
          id: `channel:${channelId}:open-files`,
          label: "Open panel: Files",
          hint: channelLabel,
          icon: FolderOpen,
          category: "This Channel",
          onSelect: () => openLeftPanelTab("files"),
        });
      }
      actions.push({
        id: `channel:${channelId}:open-jump`,
        label: "Open panel: Jump",
        hint: channelLabel,
        icon: PanelLeftIcon,
        category: "This Channel",
        onSelect: () => openLeftPanelTab("jump"),
      });
      actions.push({
        id: `channel:${channelId}:toggle-left-panel`,
        label: panelPrefs.leftOpen ? "Hide left workbench" : "Show left workbench",
        hint: channelLabel,
        icon: PanelLeftIcon,
        category: "This Channel",
        onSelect: () => patchChannelPanelPrefs(channelId, { leftOpen: !panelPrefs.leftOpen }),
      });
      actions.push({
        id: `channel:${channelId}:pin-left-panel`,
        label: panelPrefs.leftPinned ? "Unpin left workbench" : "Pin left workbench open",
        hint: channelLabel,
        icon: PanelLeftIcon,
        category: "This Channel",
        onSelect: () => patchChannelPanelPrefs(channelId, { leftPinned: !panelPrefs.leftPinned, leftOpen: true }),
      });
      if (dockPins.length > 0 && layoutMode === "full") {
        actions.push({
          id: `channel:${channelId}:toggle-right-dock`,
          label: panelPrefs.rightOpen ? "Hide right dock" : "Show right dock",
          hint: `${dockPins.length} widget${dockPins.length === 1 ? "" : "s"}`,
          icon: PanelRightIcon,
          category: "This Channel",
          onSelect: () => toggleRightDockPanel(),
        });
        actions.push({
          id: `channel:${channelId}:pin-right-dock`,
          label: panelPrefs.rightPinned ? "Unpin right dock" : "Pin right dock open",
          hint: `${dockPins.length} widget${dockPins.length === 1 ? "" : "s"}`,
          icon: PanelRightIcon,
          category: "This Channel",
          onSelect: () => patchChannelPanelPrefs(channelId, { rightPinned: !panelPrefs.rightPinned, rightOpen: true }),
        });
      }
      actions.push({
        id: `channel:${channelId}:focus-mode`,
        label: panelPrefs.leftOpen || panelPrefs.rightOpen || !panelPrefs.topChromeCollapsed ? "Focus chat panes" : "Restore panels",
        hint: channelLabel,
        icon: LayoutDashboardIcon,
        category: "This Channel",
        onSelect: () => focusOrRestorePanels(),
      });
      actions.push({
        id: `channel:${channelId}:bot-context`,
        label: "View bot context",
        hint: channelLabel,
        icon: Cog,
        category: "This Channel",
        onSelect: () => setBotInfoBotId(channel?.bot_id || null),
      });
      actions.push({
        id: `channel:${channelId}:dashboard`,
        label: "Channel dashboard",
        hint: channelLabel,
        icon: LayoutDashboardIcon,
        category: "This Channel",
        onSelect: () => navigate(channelDashboardHref),
      });
    }

    actions.push({
      id: `channel:${channelId}:settings`,
      label: "Channel settings",
      hint: channelLabel,
      icon: SettingsIcon,
      category: "This Channel",
      onSelect: () => navigate(`/channels/${channelId}/settings`),
    });

    if (isSystemChannel) {
      actions.push({
        id: `channel:${channelId}:findings`,
        label: "Findings",
        hint: findingsCount > 0 ? `${findingsCount} pending` : channelLabel,
        icon: PanelRightIcon,
        category: "This Channel",
        onSelect: () => setFindingsPanelOpen((p) => !p),
      });
    }

    return registerPaletteActions(`channel:${channelId}`, actions);
  }, [
    channelId,
    displayName,
    fileWorkspaceId,
    isSystemChannel,
    findingsCount,
    channel?.bot_id,
    channelDashboardHref,
    dockPins.length,
    focusOrRestorePanels,
    fileRootPath,
    navigate,
    openLeftPanelTab,
    openSessionsOverlay,
    openSplitOverlay,
    openTerminalAtPath,
    panelPrefs.leftOpen,
    panelPrefs.rightOpen,
    panelPrefs.topChromeCollapsed,
    panelPrefs.leftPinned,
    panelPrefs.rightPinned,
    panelPrefs.focusModePrior,
    railPins.length,
    layoutMode,
    patchChannelPanelPrefs,
    projectPath,
    registerPaletteActions,
    toggleRightDockPanel,
  ]);

  // ---- Shared message input props ----
  const messageInputProps = {
    onSend: handleSend,
    onSendAudio: handleSendAudio,
    disabled: isPaused,
    sendDisabledReason: pendingHarnessQuestion
      ? "Answer or ignore the harness question above to continue."
      : autoCompactPressure === "hard" && autoCompactRunning
        ? "Native compaction is running. Send after it finishes."
        : null,
    isStreaming: Object.keys(chatState.turns).length > 0 || chatState.isProcessing,
    onCancel: handleCancel,
    modelOverride: turnModelOverride,
    modelProviderIdOverride: turnProviderIdOverride,
    onModelOverrideChange: handleModelOverrideChange,
    defaultModel: channel?.model_override || bot?.model,
    // Phase 4: drop the harness gate. Composer pill now swaps to a
    // harness-aware picker when bot.harness_runtime is set (writes go to
    // POST /sessions/{id}/harness-settings instead of channel.model_override).
    hideModelOverride: false,
    harnessRuntime: bot?.harness_runtime ?? null,
    harnessAvailableModels: harnessCaps?.available_models ?? [],
    harnessEffortValues: (
      harnessCaps?.model_options?.find((m) => m.id === harnessSettings?.model)?.effort_values
      ?? harnessCaps?.effort_values
      ?? []
    ),
    harnessCurrentModel: harnessSettings?.model ?? null,
    harnessCurrentEffort: harnessSettings?.effort ?? null,
    harnessApprovalMode: bot?.harness_runtime
      ? sessionApprovalMode?.mode ?? "bypassPermissions"
      : null,
    onHarnessModelChange: (model: string | null) => {
      const sid = headerPaneSessionId;
      if (!sid) return;
      setHarnessSettings.mutate({ sessionId: sid, patch: { model } });
    },
    onHarnessEffortChange: (effort: string | null) => {
      const sid = headerPaneSessionId;
      if (!sid) return;
      setHarnessSettings.mutate({ sessionId: sid, patch: { effort } });
    },
    onHarnessApprovalModeCycle: bot?.harness_runtime ? handleCycleHarnessApprovalMode : undefined,
    harnessModelMutating: setHarnessSettings.isPending,
    harnessApprovalModeMutating: setApprovalMode.isPending,
    harnessCostTotal: bot?.harness_runtime
      ? invertedData.reduce((sum, m) => {
          const c = (m.metadata as { harness?: { cost_usd?: number } } | undefined)?.harness?.cost_usd;
          return typeof c === "number" ? sum + c : sum;
        }, 0)
      : null,
    currentBotId: channel?.bot_id,
    isMultiBot: (channel?.member_bots?.length ?? 0) > 0,
    channelId,
    onSlashCommand: handleSlashCommand,
    isQueued,
    queuedMessageText,
    onCancelQueue: cancelQueue,
    onEditQueue: editQueue,
    onSendNow: handleSendNow,
    configOverhead: configOverheadData?.overhead_pct ?? null,
    onConfigOverheadClick: () => setBotInfoBotId(channel?.bot_id || null),
    chatMode,
    planMode: sessionPlan.mode,
    hasPlan: sessionPlan.hasPlan,
    planBusy,
    canTogglePlanMode: !!currentPlanSessionId,
    onTogglePlanMode: currentPlanSessionId ? handleTogglePlanMode : undefined,
    onApprovePlan: sessionPlan.mode === "planning" && sessionPlan.data ? () => sessionPlan.approvePlan.mutate() : undefined,
  };

  // ---- Shared message area props ----
  const messageAreaProps = {
    invertedData: visibleInvertedData,
    renderMessage,
    chatState,
    bot,
    botId: channel?.bot_id,
    pendingApprovalsSlot: channelId
      ? (liveApprovalIds: Set<string>) => (
          <ChannelPendingApprovals channelId={channelId} liveApprovalIds={liveApprovalIds} chatMode={chatMode} />
        )
      : undefined,
    isLoading,
    isFetchingNextPage,
    hasNextPage,
    handleLoadMore,
    isProcessing: chatState.isProcessing,
    t,
    chatMode,
    sessionId: channel?.active_session_id,
    onOpenMessageSession: handleOpenFindResultSession,
  };
  const primarySessionResumeSlot = useSessionResumeCard({
    sessionId: channel?.active_session_id,
    channelId,
    messages: invertedData,
    isActive: Object.keys(chatState.turns).length > 0 || !!chatState.isProcessing,
    chatMode,
    seed: {
      surfaceKind: "primary",
      title: "Primary session",
      botName: bot?.name,
      botModel: bot?.model,
    },
    onOpenSessions: openSessionsOverlay,
  });
  const pendingHarnessQuestionLane = pendingHarnessQuestion ? (
    <div className="px-3 pb-2">
      <div className="mb-1 text-[11px] text-text-dim">
        Answer this harness question to continue, or ignore it if it expired.
      </div>
      {renderMessage({ item: pendingHarnessQuestion, index: pendingHarnessQuestionIndex })}
      <div className="mt-1 flex justify-end">
        <button
          type="button"
          onClick={handleIgnoreHarnessQuestion}
          className="rounded px-2 py-1 text-[11px] text-text-dim hover:bg-surface-overlay hover:text-text"
        >
          Ignore question
        </button>
      </div>
    </div>
  ) : null;
  const harnessAutoCompactionLane = autoCompactPressure ? (
    <div className="px-3 pb-2">
      <div className="rounded-md border border-warning/25 bg-warning/8 p-3 text-xs text-text-muted">
        <div className="mb-1 font-medium text-text">
          {autoCompactPressure === "hard" ? "Native context is critically low" : "Native context is getting full"}
        </div>
        <div className="mb-3 leading-snug">
          {typeof remainingPct === "number" ? `${Math.round(remainingPct)}% context remains. ` : ""}
          {autoCompactPressure === "hard"
            ? "Compact now, open a fresh session, or keep going. Spindrel will not compact unless you choose it."
            : "Compact now, open a fresh session, or dismiss this prompt for the current session."}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={triggerNativeCompact}
            disabled={autoCompactRunning}
            className="rounded bg-surface-overlay px-2.5 py-1 text-[11px] text-text hover:bg-surface-raised disabled:opacity-60"
          >
            {autoCompactRunning ? "Compacting..." : "Compact now"}
          </button>
          <button
            type="button"
            onClick={openNewVisibleSession}
            className="rounded bg-surface-overlay px-2.5 py-1 text-[11px] text-text hover:bg-surface-raised"
          >
            New session
          </button>
          <button
            type="button"
            onClick={() => setDismissedAutoCompactSession(currentPlanSessionId ?? null)}
            className="rounded px-2.5 py-1 text-[11px] text-text-dim hover:bg-surface-overlay hover:text-text"
          >
            Later
          </button>
          <button
            type="button"
            onClick={disableAutoCompactionPrompts}
            className="rounded px-2.5 py-1 text-[11px] text-text-dim hover:bg-surface-overlay hover:text-text"
          >
            Disable prompts
          </button>
        </div>
      </div>
    </div>
  ) : null;

  const terminalBottomSlot = chatMode === "terminal" ? (
    <>
      {chatState.error && (
        <ErrorBanner error={chatState.error} onDismiss={() => channelId && setError(channelId, "")} onRetry={handleRetry} />
      )}
      {chatState.secretWarning && (
        <SecretWarningBanner
          patterns={chatState.secretWarning.patterns}
          onDismiss={() => channelId && useChatStore.setState((s) => ({
            channels: { ...s.channels, [channelId]: { ...s.channels[channelId]!, secretWarning: null } },
          }))}
        />
      )}
      {pendingHarnessQuestionLane}
      {harnessAutoCompactionLane}
      <ChatComposerShell chatMode={chatMode}>
        <MessageInput {...messageInputProps} />
      </ChatComposerShell>
    </>
  ) : null;

  const scratchEmptyState = (
    <div
      className="flex flex-col items-center justify-center text-center px-6"
      style={{ minHeight: 260, gap: 14 }}
    >
      <div
        className="inline-flex items-center gap-2 rounded-full px-3 py-1.5"
        style={{
          backgroundColor: t.surfaceOverlay,
          border: `1px solid ${t.surfaceBorder}`,
          color: t.textDim,
        }}
      >
        <StickyNote size={13} color={t.textDim} />
        <span className="text-[11px] font-semibold tracking-[0.18em] uppercase">
          Session
        </span>
      </div>
      <div className="space-y-2">
        <div
          style={{
            color: t.text,
            fontSize: isMobile ? 21 : 24,
            fontWeight: 600,
            letterSpacing: "-0.02em",
          }}
        >
          Work in a separate session for this channel.
        </div>
        <div
          style={{
            color: t.textMuted,
            fontSize: isMobile ? 13 : 14,
            maxWidth: 460,
            lineHeight: 1.55,
          }}
        >
          {"This session stays attached to the channel while keeping its own context and history apart from the primary conversation."}
        </div>
      </div>
    </div>
  );

  // ---- Single-session column (full-page mode) ----
  // A selected previous/scratch session is the page, not a pane. This keeps
  // the channel header and the chat surface from presenting competing session
  // identities.
  const sessionColumnNode =
    routeSessionSource && channelId ? (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
        <div style={{ flex: 1, minHeight: 0 }}>
          <ChatSession
            source={routeSessionSource}
            shape="fullpage"
            open
            onClose={handleExitSessionRoute}
            title="Session"
            emptyState={scratchEmptyState}
            chatMode={chatMode}
            onOpenSessions={openSessionsOverlay}
            onOpenSessionSplit={openSplitOverlay}
            onToggleFocusLayout={focusOrRestorePanels}
          />
        </div>
      </div>
    ) : null;
  // Measured height of the composer overlay (input card + banners + strips)
  // so messages scroll BEHIND the frosted input at the bottom — Claude-style.
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

  const primaryChatNode = (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", position: "relative" }}>
      <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
        <ChatMessageArea
          {...messageAreaProps}
          sessionResumeSlot={primarySessionResumeSlot}
          bottomSlot={terminalBottomSlot}
          scrollPaddingTop={0}
          scrollPaddingBottom={chatMode === "terminal" ? 20 : inputOverlayHeight + (isMobile ? 32 : 48)}
        />
      </div>
      {chatMode !== "terminal" && (
        <div ref={inputOverlayRef} style={{ position: "absolute", bottom: 0, left: 0, right: 0, zIndex: 4 }}>
          {chatState.error && (
            <ErrorBanner error={chatState.error} onDismiss={() => channelId && setError(channelId, "")} onRetry={handleRetry} />
          )}
          {chatState.secretWarning && (
            <SecretWarningBanner
              patterns={chatState.secretWarning.patterns}
              onDismiss={() => channelId && useChatStore.setState((s) => ({
                channels: { ...s.channels, [channelId]: { ...s.channels[channelId]!, secretWarning: null } },
              }))}
            />
          )}
          {pendingHarnessQuestionLane}
          {harnessAutoCompactionLane}
          <ChatComposerShell chatMode={chatMode}>
            <MessageInput {...messageInputProps} />
          </ChatComposerShell>
        </div>
      )}
    </div>
  );

  const channelHeaderBlock = (
    // Transparent wrapper — header, HUD strip, and launchpad sit directly
    // on the page surface like the rail/dock/chat columns below. Previously
    // framed with a backdrop-blur + surface/cc tint that made the top
    // section read as a separate card; spacing alone now separates regions.
    <div style={{ flexShrink: 0 }}>
        <ChannelHeader
          channelId={channelId!}
          displayName={displayName}
          bot={bot}
          channelModelOverride={channel?.model_override ?? undefined}
          columns={columns}
          goBack={goBack}
          workspaceId={fileWorkspaceId}
          explorerOpen={showExplorer}
          toggleExplorer={toggleExplorer}
          onBrowseWorkspace={openBrowseFiles}
          isMobile={isMobile}
          contextBudget={headerContextBudget}
          sessionHeaderStats={channelHeaderChromeMode !== "canvas" ? headerSessionStats ?? null : null}
          sessionId={channelHeaderChromeMode !== "canvas" ? headerPaneSessionId : null}
          sessionChromeMode={channelHeaderChromeMode}
          sessionChromeTitle={null}
          sessionChromeMeta={channelHeaderChromeMode === "session" ? headerPaneMeta : null}
          canvasSessionCount={visibleChatPanes.length}
          onContextBudgetClick={() => setBotInfoBotId(channel?.bot_id || null)}
          isSystemChannel={isSystemChannel}
          findingsPanelOpen={isSystemChannel ? findingsPanelOpen : undefined}
          toggleFindingsPanel={isSystemChannel ? () => setFindingsPanelOpen((p) => !p) : undefined}
          findingsCount={isSystemChannel ? findingsCount : 0}
          scratchOpen={!!routeSessionSurface || scratchOpen || visibleChatPanes.length > 1}
          scratchSessionId={channelHeaderChromeMode === "session" ? headerPaneSessionId : null}
          onOpenMainChat={routeSessionSurface ? handleExitSessionRoute : undefined}
          dashboardHref={channelDashboardHref}
          onOpenSessions={openSessionsOverlay}
          scratchFullpageMode={routeSessionSurface ? {} : undefined}
        />
        {/* Desktop: integration dots inlined into ChannelHeader subtitle.
            Mobile: retain the compact scrolling bar (no subtitle row to inline into). */}
        {channelId && isMobile && <ActiveBadgeBar channelId={channelId} compact />}

      {launchpadVisible && channelId && (
        <OrchestratorLaunchpad
          channelId={channelId}
          onOpenFindings={() => setFindingsPanelOpen(true)}
        />
      )}

    </div>
  );

  // Header-zone chip strip — rendered as an absolute overlay centered over
  // the top of the three-column row so it floats without consuming vertical
  // space. Desktop only; mobile surfaces these in the drawer's Widgets tab.
  // The overlay spans the real center track between the left and right
  // panels, but remains transparent/click-through outside the actual widgets.
  const headerChipOverlay =
    !isMobile && channelId && hasHeaderChips && showHeaderChips ? (
      <div
        className="absolute top-1 z-20 pointer-events-none"
        style={{
          left:
            panelLayout.left.mode === "push"
              ? panelLayout.left.width + HEADER_RAIL_EDGE_INSET_PX + CENTER_PANEL_GUTTER_PX
              : panelLayout.left.mode === "closed" && !isSystemChannel && showRailZone
                ? COLLAPSED_PANEL_SPINE_WIDTH_PX + HEADER_RAIL_EDGE_INSET_PX + CENTER_PANEL_GUTTER_PX
                : HEADER_RAIL_EDGE_INSET_PX + CENTER_PANEL_GUTTER_PX,
          right:
            dockBlockedByFileViewer && !isSystemChannel && showDockZone && dockPins.length > 0
              ? COLLAPSED_PANEL_SPINE_WIDTH_PX + HEADER_RAIL_EDGE_INSET_PX + CENTER_PANEL_GUTTER_PX
              : panelLayout.right.mode === "push"
                ? panelLayout.right.width + HEADER_RAIL_EDGE_INSET_PX + CENTER_PANEL_GUTTER_PX
                : panelLayout.right.mode === "closed" && !isSystemChannel && showDockZone && dockPins.length > 0
                ? COLLAPSED_PANEL_SPINE_WIDTH_PX + HEADER_RAIL_EDGE_INSET_PX + CENTER_PANEL_GUTTER_PX
                : HEADER_RAIL_EDGE_INSET_PX + CENTER_PANEL_GUTTER_PX,
        }}
      >
        {panelPrefs.topChromeCollapsed ? (
          <div className="pointer-events-auto mx-auto flex h-7 w-fit items-center gap-2 rounded-md border border-surface-border bg-surface-raised/90 px-2 text-[11px] text-text-dim shadow-sm">
            <button
              type="button"
              onClick={() => patchChannelPanelPrefs(channelId, { topChromeCollapsed: false, focusModePrior: null })}
              className="text-text-dim hover:text-text"
            >
              Show top widgets
            </button>
            <span>{headerChipPins.length}</span>
          </div>
        ) : (
        <div className="w-full">
          <ChannelHeaderChip
            channelId={channelId}
            backdropMode={channel?.config?.header_backdrop_mode ?? "glass"}
          />
        </div>
        )}
      </div>
    ) : null;

  const outerChildren = (
    <>
      {/* Mobile: header at top, then content stack. */}
      {isMobile && channelHeaderBlock}

      {/* Content area — mobile stack or desktop side-by-side */}
      {isMobile ? (
        /* ---- Mobile: chat + bottom sheet OmniPanel ---- */
        /* Chat stays mounted underneath; file viewer slides in from the right
           as an overlay. Preserves chat scroll position + avoids the jarring
           full-screen swap. */
        <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative", minHeight: 0 }}>
          {sessionColumnNode ? (
            sessionColumnNode
          ) : (
            primaryChatNode
          )}
          {/* Mobile channel drawer — tabbed Widgets/Files/Jump; opens from
              the channel header's hamburger. Replaces the old bottom sheet
              with a channel-scoped full-height drawer that also embeds the
              global command palette as its "Jump" tab. Hidden on system
              channels (no workspace + orchestrator handles its own chrome). */}
          {channelId && !isSystemChannel && (
            <MobileChannelDrawer
              open={showExplorer}
              onClose={handleCloseExplorer}
              channelId={channelId}
              dashboardHref={channelDashboardHref}
              workspaceId={fileWorkspaceId ?? undefined}
              fileRootPath={fileRootPath}
              fileRootLabel="Project"
              botId={channel?.bot_id}
              channelDisplayName={channel?.display_name || channel?.name}
              activeFile={activeFile}
              onSelectFile={handleSelectFile}
              onOpenTerminal={openTerminalAtPath}
              activeTab={panelPrefs.leftTab}
              onTabChange={(tab) => setChannelPanelTab(channelId, tab)}
              expandedWidgetId={panelPrefs.mobileExpandedWidgetId}
              onExpandedWidgetChange={(widgetId) => setMobileExpandedWidget(channelId, widgetId)}
            />
          )}
          {/* Mobile file viewer — slides in over the chat, chat stays mounted. */}
          <MobileFileViewerSlide
            open={showFileViewer}
            channelId={channelId!}
            workspaceId={fileWorkspaceId ?? undefined}
            filePath={activeFile}
            channelName={channel?.display_name || channel?.name || null}
            channelPrivate={!!channel?.private}
            onBack={handleMobileBack}
            onDirtyChange={handleDirtyChange}
          />
        </div>
      ) : (
        /* ---- Desktop/tablet: full-width header + side-by-side row ----
           ChannelHeader spans above the three columns so the chat screen
           mirrors the dashboard layout (header-row above rail/grid/dock).
           Pinned files now ride the normal dock widget system. */
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minHeight: 0 }}>
          {channelHeaderBlock}
        <div style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden", position: "relative", minHeight: 0 }}>
          {headerChipOverlay}
          {overlayPanelOpen && (
            <button
              type="button"
              aria-label="Close overlay panels"
              className="absolute inset-0 z-[24] cursor-default bg-transparent"
              onClick={closeOverlayPanels}
            />
          )}
          {!isMobile && panelLayout.left.mode === "closed" && channelId && !isSystemChannel && showRailZone && (
            <CollapsedPanelSpine
              side="left"
              title="Open left panel"
              actions={leftSpineActions}
            />
          )}
          {/* OmniPanel shell — animated via width clip.
              Hidden on system channels (orchestrator has no workspace files
              or channel-specific pinned widgets worth surfacing) and when
              the channel's layout_mode is "dashboard-only". The expensive
              panel contents unmount when closed so rail widgets stop their
              polling/SSE work instead of running inside a 0px container.
              Outer padding (pl-1.5 py-1.5) creates the 6px floating-card gap. */}
          {channelId && !isSystemChannel && showRailZone && (
            <div
              style={{
                width: panelLayout.left.mode === "push" ? panelLayout.left.width : 0,
                ...(panelLayout.left.mode === "overlay"
                  ? {
                      position: "absolute",
                      left: 0,
                      top: 0,
                      bottom: 0,
                      zIndex: 30,
                      width: panelLayout.left.width,
                      backgroundColor: t.surface,
                      boxShadow: "18px 0 36px rgba(0,0,0,0.28)",
                    }
                  : {}),
                overflow: "hidden",
                transition: "width 200ms cubic-bezier(0.4, 0, 0.2, 1)",
                flexShrink: 0,
              }}
            >
              {showExplorer && (
                <OmniPanel
                  channelId={channelId}
                  dashboardHref={channelDashboardHref}
                  workspaceId={fileWorkspaceId ?? undefined}
                  fileRootPath={fileRootPath}
                  fileRootLabel="Project"
                  botId={channel?.bot_id}
                  channelDisplayName={channel?.display_name || channel?.name}
                  activeFile={activeFile}
                  onSelectFile={handleSelectFile}
                  onOpenTerminal={openTerminalAtPath}
                  onClose={handleCloseExplorer}
                  width={panelLayout.left.width}
                  activeTab={panelPrefs.leftTab}
                  onTabChange={(tab) => setChannelPanelTab(channelId, tab)}
                  onCollapse={() => patchChannelPanelPrefs(channelId, { leftOpen: false })}
                />
              )}
            </div>
          )}
          {panelLayout.left.mode === "push" && channelId && (
            <ResizeHandle
              direction="horizontal"
              onResize={(delta) =>
                patchChannelPanelPrefs(channelId, {
                  leftWidth: clampChannelPanelWidth(panelPrefs.leftWidth + delta, leftPanelResizeMax),
                })
              }
              invisible
            />
          )}

          <div
            style={{
              flex: 1,
              minWidth: 0,
              display: "flex",
              paddingLeft: CENTER_PANEL_GUTTER_PX,
              paddingRight: CENTER_PANEL_GUTTER_PX,
            }}
          >
            {/* Dashboard-only mode: replace the chat column with a card
                that points users at the full dashboard. No messages, no
                composer — the channel is purely a widget surface. */}
            {dashboardOnly && channelId && (
              <div
                className="flex-1 flex items-center justify-center p-6"
                style={{ backgroundColor: t.surface }}
              >
                <div
                  className="max-w-sm w-full rounded-lg p-6 flex flex-col items-center gap-3 text-center"
                  style={{ backgroundColor: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}` }}
                >
                  <LayoutDashboardIcon size={20} style={{ color: t.accent }} />
                  <div className="text-[15px] font-semibold" style={{ color: t.text }}>
                    Dashboard-only channel
                  </div>
                  <div className="text-[12px] leading-relaxed" style={{ color: t.textMuted }}>
                    This channel renders as a widget dashboard. Open the dashboard
                    to see pinned widgets.
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate(channelDashboardHref)}
                    className="mt-1 rounded-md px-4 py-1.5 text-[12px] font-medium"
                    style={{ backgroundColor: t.accent, color: t.surface }}
                  >
                    Open dashboard
                  </button>
                </div>
              </div>
            )}

            {/* Chat column — messages + input stacked vertically. The full-width
                ChannelHeader now lives ABOVE this flex-row, so the column is
                header-free and the message area doesn't need a top-offset. */}
            {!dashboardOnly && sessionColumnNode && (
              sessionColumnNode
            )}
            {!dashboardOnly && !sessionColumnNode && (!showFileViewer || splitMode) && (
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                {canvasActive
                  && !panelPrefs.collapseHintDismissed
                  && (panelPrefs.leftOpen || panelPrefs.rightOpen || !panelPrefs.topChromeCollapsed) && (
                  <div className="mx-1 flex shrink-0 items-center justify-between rounded-md border border-surface-border bg-surface-raised px-3 py-1.5 text-[11px] text-text-dim">
                    <span>More room for splits: use /focus or Ctrl/⌘+Alt+B to collapse panels.</span>
                    <div className="flex items-center gap-2">
                      <button type="button" onClick={focusOrRestorePanels} className="text-accent hover:underline">Focus</button>
                      <button
                        type="button"
                        onClick={() => patchChannelPanelPrefs(channelId!, { collapseHintDismissed: true })}
                        className="text-text-dim hover:text-text"
                      >
                        Don't show again
                      </button>
                    </div>
                  </div>
                )}
                {canvasActive ? (
                  <ChannelChatPaneGroup
                    channelId={channelId!}
                    botId={channel?.bot_id}
                    activeSessionId={channel?.active_session_id}
                    panes={panelPrefs.chatPaneLayout.panes}
                    widths={panelPrefs.chatPaneLayout.widths}
                    focusedPaneId={panelPrefs.chatPaneLayout.focusedPaneId}
                    maximizedPaneId={panelPrefs.chatPaneLayout.maximizedPaneId}
                    catalog={channelSessionCatalog}
                    primaryNode={primaryChatNode}
                    emptyState={scratchEmptyState}
                    chatMode={chatMode}
                    onFocusPane={focusPane}
                    onClosePane={closePane}
                    onMaximizePane={maximizePane}
                    onRestorePanes={restorePanes}
                    onMinimizePane={minimizePane}
                    onMovePane={movePane}
                    onCommitPaneWidths={commitPaneWidths}
                    onMakePrimary={makePanePrimary}
                    onOpenSessions={openSessionsOverlay}
                    onOpenSessionSplit={openSplitOverlay}
                    onToggleFocusLayout={focusOrRestorePanels}
                  />
                ) : (
                  primaryChatNode
                )}
              </div>
            )}

            {/* File viewer -- visible when a file is selected */}
            {showFileViewer && channelId && (
              <div style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                minWidth: 0,
                borderLeft: splitMode ? `1px solid ${t.surfaceBorder}` : "none",
              }}>
                <ChannelFileViewer
                  channelId={channelId}
                  workspaceId={fileWorkspaceId ?? undefined}
                  filePath={activeFile!}
                  onBack={handleCloseFile}
                  splitMode={splitMode}
                  onToggleSplit={toggleSplit}
                  onDirtyChange={handleDirtyChange}
                />
              </div>
            )}
          </div>

          {!isMobile && channelId && !isSystemChannel && showDockZone && dockPins.length > 0 && (panelLayout.right.mode === "closed" || dockBlockedByFileViewer) && (
            <CollapsedPanelSpine
              side="right"
              title={dockBlockedByFileViewer ? "Right dock unavailable" : "Open right dock"}
              actions={rightSpineActions}
              statusLabel={dockBlockedByFileViewer ? "Dock Locked" : undefined}
            />
          )}

          {/* Right-side widget dock — surfaces channel-dashboard pins whose
              left edge sits in the dock-right band. Hidden on system channels
              (no channel dashboard) and when the band is empty. Outer
              `pr-2.5 py-2.5` mirrors the left dock's `pl-2.5 py-2.5` so the
              floating-card gap is symmetric on both sides. */}
          {!isMobile && channelId && !isSystemChannel && showRightDock && showDockZone && (
            <div
              className="pr-2.5 py-2.5 flex"
              style={panelLayout.right.mode === "overlay"
                ? {
                    position: "absolute",
                    right: 0,
                    top: 0,
                    bottom: 0,
                    zIndex: 30,
                    backgroundColor: t.surface,
                    boxShadow: "-18px 0 36px rgba(0,0,0,0.28)",
                  }
                : undefined}
            >
              <WidgetDockRight
                channelId={channelId}
                dashboardHref={channelDashboardHref}
                width={panelLayout.right.width}
                maxWidth={rightPanelResizeMax}
                onWidthChange={(width) => patchChannelPanelPrefs(channelId, { rightWidth: width })}
                onCollapse={() => patchChannelPanelPrefs(channelId, { rightOpen: false })}
              />
            </div>
          )}

          {/* Findings panel — pipelines awaiting user approval (system channels only) */}
          {!isMobile && isSystemChannel && findingsPanelOpen && channelId && (
            <FindingsPanel
              channelId={channelId}
              onClose={() => setFindingsPanelOpen(false)}
            />
          )}
        </div>
        </div>
      )}

      {/* Mobile findings sheet */}
      {isMobile && isSystemChannel && channelId && (
        <FindingsSheet
          channelId={channelId}
          open={findingsPanelOpen}
          onClose={() => setFindingsPanelOpen(false)}
        />
      )}
      <ConfirmDialog
        open={pendingDirtyAction !== null}
        title="Unsaved Changes"
        message="You have unsaved changes. Discard them?"
        confirmLabel="Discard"
        variant="warning"
        onConfirm={() => {
          if (pendingDirtyAction) executeDirtyAction(pendingDirtyAction);
          setPendingDirtyAction(null);
        }}
        onCancel={() => setPendingDirtyAction(null)}
      />
      {secretWarning && (
        <SecretWarningDialog
          result={secretWarning.result}
          onSendAnyway={() => {
            const { text, files } = secretWarning;
            setSecretWarning(null);
            doSend(text, files);
          }}
          onCancel={() => setSecretWarning(null)}
          onAddToSecrets={() => {
            // Extract the first detected secret value and pass via sessionStorage
            const { text, result } = secretWarning;
            const patternType = result.pattern_matches?.[0]?.type ?? "Secret";
            // Use a simple regex extraction for common patterns
            const secretPatterns = [
              /sk_live_[A-Za-z0-9]{20,}/,
              /sk_test_[A-Za-z0-9]{20,}/,
              /rk_live_[A-Za-z0-9]{20,}/,
              /pk_live_[A-Za-z0-9]{20,}/,
              /sk-[A-Za-z0-9]{20,}/,
              /sk-proj-[A-Za-z0-9_-]{20,}/,
              /sk-ant-[A-Za-z0-9_-]{20,}/,
              /gh[pso]_[A-Za-z0-9]{20,}/,
              /github_pat_[A-Za-z0-9_]{20,}/,
              /xox[bpas]-[A-Za-z0-9-]+/,
              /AKIA[0-9A-Z]{16}/,
              /SG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}/,
              /AIza[A-Za-z0-9_-]{35}/,
              /eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+/,
            ];
            let extractedValue = "";
            for (const pat of secretPatterns) {
              const m = text.match(pat);
              if (m) { extractedValue = m[0]; break; }
            }
            if (extractedValue) {
              try {
                sessionStorage.setItem("secret_prefill", JSON.stringify({
                  value: extractedValue,
                  type: patternType,
                  returnTo: `/channels/${channelId}`,
                  channelId,
                  originalMessage: text,
                }));
              } catch { /* ignore */ }
            }
            setSecretWarning(null);
            navigate("/admin/secret-values");
          }}
        />
      )}
      {botInfoBotId && channelId && (
        <BotInfoPanel
          botId={botInfoBotId}
          channelId={channelId}
          onClose={() => setBotInfoBotId(null)}
          contextBudget={effectiveContextBudget}
          configOverhead={configOverheadData ?? null}
        />
      )}
    </>
  );

  // Show full-page skeleton while channel data is loading to prevent
  // the multi-stage pop-in (header → badges → messages).
  if (channelLoading && !channel) {
    return <ChatScreenSkeleton />;
  }

  return (
    <div
      className={entranceClassActive ? "chat-screen--entering-from-dock" : undefined}
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        backgroundColor: t.surface,
        overflow: "hidden",
        // Respect the notch + system UI on mobile. No-op on desktop where
        // safe-area insets are 0. Bottom is handled per-component already
        // (composer overlay, mobile drawer) so we only pad the top.
        paddingTop: isMobile ? "env(safe-area-inset-top)" : undefined,
      }}
    >
      {outerChildren}
      <ChannelModalMount />
      {pendingSplitSurface && (
        <div className="fixed inset-0 z-[10045] flex items-center justify-center bg-black/40">
          <div className="w-[360px] max-w-[92vw] rounded-md border border-surface-border bg-surface-raised p-3 shadow-xl">
            <div className="text-[13px] font-semibold text-text">Replace a pane</div>
            <div className="mt-1 text-[12px] text-text-dim">This channel can show up to 3 chat panes. Choose one to replace.</div>
            <div className="mt-3 space-y-1">
              {panelPrefs.chatPaneLayout.panes.map((pane, index) => (
                <button
                  key={pane.id}
                  type="button"
                  onClick={() => replacePaneWithPendingSplit(pane.id)}
                  className="block w-full rounded-md px-2 py-2 text-left text-[12px] text-text hover:bg-surface-overlay"
                >
                  Pane {index + 1}: {pane.surface.kind === "primary" ? "Primary session" : pane.surface.kind}
                </button>
              ))}
            </div>
            <div className="mt-3 flex justify-end">
              <button type="button" onClick={() => setPendingSplitSurface(null)} className="rounded-md px-2 py-1 text-[12px] text-text-dim hover:bg-surface-overlay">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      {channelId && (
        <SessionPickerOverlay
          open={sessionsOverlayOpen}
          onClose={() => setSessionsOverlayOpen(false)}
          channelId={channelId}
          botId={channel?.bot_id}
          channelLabel={displayName}
          selectedSessionId={selectedPickerSessionId}
          onActivateSurface={activateChannelSessionSurface}
          allowSplit={!isMobile}
          mode={sessionsOverlayMode}
          hiddenSurfaces={pickerHiddenSurfaces}
          openSurfaces={pickerHiddenSurfaces}
        />
      )}
      {threadSource && (
        <ChatSession
          source={threadSource}
          shape="dock"
          open
          onClose={handleClearActiveThread}
          title="Thread"
          initiallyExpanded
          chatMode={chatMode}
          onOpenSessions={openSessionsOverlay}
          onOpenSessionSplit={openSplitOverlay}
          onToggleFocusLayout={focusOrRestorePanels}
        />
      )}
      {miniPaneSource && !activeThread && !routeSessionSurface && (
        <ChatSession
          source={miniPaneSource}
          shape="dock"
          open
          onClose={handleCloseMiniPane}
          title={miniPaneLabel.title}
          dismissMode="collapse"
          dockCollapsedTitle={miniPaneLabel.title}
          dockCollapsedSubtitle={miniPaneLabel.subtitle}
          onRestoreToCanvas={restoreMiniPane}
          chatMode={chatMode}
          onOpenSessions={openSessionsOverlay}
          onOpenSessionSplit={openSplitOverlay}
          onToggleFocusLayout={focusOrRestorePanels}
        />
      )}
      {scratchSource && !miniPaneSource && !activeThread && !routeSessionSurface && (
        <ChatSession
          source={scratchSource}
          shape="dock"
          open={scratchOpen}
          onClose={handleScratchClose}
          title="Session"
          emptyState={scratchEmptyState}
          initiallyExpanded
          chatMode={chatMode}
          onOpenSessions={openSessionsOverlay}
          onOpenSessionSplit={openSplitOverlay}
          onToggleFocusLayout={focusOrRestorePanels}
        />
      )}
      {terminalRequest && (
        <ChannelTerminalDrawer
          cwd={terminalRequest.cwd}
          label={terminalRequest.label}
          onClose={() => setTerminalRequest(null)}
        />
      )}
    </div>
  );
}

function ChannelTerminalDrawer({
  cwd,
  label,
  onClose,
}: {
  cwd: string;
  label: string;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-y-0 right-0 z-[10035] flex w-[min(820px,92vw)] flex-col border-l border-surface-border bg-[#0a0d12] shadow-2xl">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-white/10 bg-[#0d1117] px-3">
        <TerminalIcon size={15} className="text-accent" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-semibold text-zinc-200">Terminal</div>
          <div className="truncate font-mono text-[10px] text-zinc-500">{label}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1.5 text-zinc-500 hover:bg-white/10 hover:text-zinc-200"
          aria-label="Close terminal"
          title="Close terminal"
        >
          <CloseIcon size={14} />
        </button>
      </div>
      <Suspense fallback={<div className="flex flex-1 items-center justify-center bg-[#0a0d12] text-[12px] text-zinc-500">Starting terminal...</div>}>
        <TerminalPanel cwd={cwd} title={cwd} />
      </Suspense>
    </div>
  );
}

/**
 * Conditionally mounts the PipelineRunModal on top of the channel page
 * when the URL is on one of the run-view sub-routes. Kept as a sibling
 * component so the channel page's chat + SSE subscription don't tear
 * down when opening the modal (the portal layers over the existing DOM).
 */
function ChannelModalMount() {
  const preRun = useMatch("/channels/:channelId/pipelines/:pipelineId");
  const live = useMatch("/channels/:channelId/runs/:taskId");
  const thread = useMatch("/channels/:channelId/threads/:threadSessionId");
  if (preRun?.params.channelId && preRun.params.pipelineId) {
    return (
      <PipelineRunModal
        channelId={preRun.params.channelId as string}
        pipelineId={preRun.params.pipelineId as string}
        mode="prerun"
      />
    );
  }
  if (live?.params.channelId && live.params.taskId) {
    return (
      <PipelineRunModal
        channelId={live.params.channelId as string}
        taskId={live.params.taskId as string}
        mode="live"
      />
    );
  }
  if (thread?.params.channelId && thread.params.threadSessionId) {
    return (
      <ThreadFullScreenMount
        channelId={thread.params.channelId as string}
        threadSessionId={thread.params.threadSessionId as string}
      />
    );
  }
  return null;
}

/** Full-screen thread view reached by Maximize-from-dock or direct URL.
 *
 *   - Loads the thread's info (bot + parent message preview) via GET
 *     /api/v1/messages/thread/{sessionId}.
 *   - Wraps ChatSession shape="modal" with a custom "Replying to …"
 *     header + X that returns to the channel. */
function ThreadFullScreenMount({
  channelId,
  threadSessionId,
}: {
  channelId: string;
  threadSessionId: string;
}) {
  const navigate = useNavigate();
  const { data: channel } = useChannel(channelId);
  const { data: info } = useThreadInfo(threadSessionId);
  const chatMode = ((channel?.config?.chat_mode ?? "default") as "default" | "terminal");
  const handleClose = useCallback(() => {
    navigate(`/channels/${channelId}`);
  }, [channelId, navigate]);

  if (!info) {
    return (
      <div className="fixed inset-0 z-[10050] flex items-center justify-center bg-surface/80 backdrop-blur-sm">
        <div className="text-text-dim text-sm">Loading thread…</div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[10050] flex flex-col bg-surface">
      <div className="flex items-center gap-3 px-4 py-2.5 shrink-0 bg-surface-raised">
        <MessageCircle size={16} className="text-accent shrink-0" />
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-[13px] font-semibold text-text">Thread</span>
        </div>
        {info.bot_name && (
          <span
            className="text-[11px] text-text-dim px-2 py-1 rounded bg-surface-overlay shrink-0"
            title={info.bot_name}
          >
            @{info.bot_name}
          </span>
        )}
        <button
          onClick={handleClose}
          title="Close thread"
          aria-label="Close thread"
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors shrink-0"
        >
          <CloseIcon size={14} />
        </button>
      </div>
      <ThreadFullScreenBody
        threadSessionId={threadSessionId}
        parentChannelId={channelId}
        botId={info.bot_id}
        parentMessage={info.parent_message ?? null}
        chatMode={chatMode}
      />
    </div>
  );
}

/** Body of the full-screen thread view — SessionChatView + MessageInput.
 *  Kept separate from ``ThreadFullScreenMount`` so the outer header can
 *  render while info is loading. Uses the same SessionChatView the dock
 *  does, so rendering stays single-implementation. */
function ThreadFullScreenBody({
  threadSessionId,
  parentChannelId,
  botId,
  parentMessage,
  chatMode = "default",
}: {
  threadSessionId: string;
  parentChannelId: string;
  botId: string;
  parentMessage: Message | null;
  chatMode?: "default" | "terminal";
}) {
  const submitChat = useSubmitChat();
  const chatState = useChatStore((s) => s.getChannel(threadSessionId));
  const turnActive = selectIsStreaming(chatState);
  const isSending = submitChat.isPending || turnActive;
  const [sendError, setSendError] = useState<string | null>(null);
  const [modelOverride, setModelOverride] = useState<string | undefined>(undefined);
  const [modelProviderId, setModelProviderId] = useState<string | null>(null);
  const { data: threadBot } = useBot(botId);
  const harnessComposerProps = useHarnessComposerProps(threadBot, threadSessionId);
  const syntheticMessages = useMemo(
    () => [buildThreadParentPreviewRow(threadSessionId, parentMessage)],
    [threadSessionId, parentMessage],
  );
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

  const handleSend = useCallback(
    async (message: string) => {
      setSendError(null);
      try {
        await submitChat.mutateAsync({
          message,
          bot_id: botId,
          client_id: "web",
          session_id: threadSessionId,
          channel_id: parentChannelId,
          ...(modelOverride
            ? {
                model_override: modelOverride,
                model_provider_id_override: modelProviderId,
              }
            : {}),
        });
      } catch (err) {
        setSendError(err instanceof Error ? err.message : "Failed to send message");
      }
    },
    [botId, threadSessionId, parentChannelId, submitChat, modelOverride, modelProviderId],
  );

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-1 min-h-0 relative">
        <SessionChatView
          sessionId={threadSessionId}
          parentChannelId={parentChannelId}
          botId={botId}
          scrollPaddingBottom={inputOverlayHeight + 16}
          syntheticMessages={syntheticMessages}
          chatMode={chatMode}
        />
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
              channelId={threadSessionId}
              modelOverride={modelOverride}
              modelProviderIdOverride={modelProviderId}
              onModelOverrideChange={(m, providerId) => {
                setModelOverride(m ?? undefined);
                setModelProviderId(providerId ?? null);
              }}
              hideModelOverride={!!threadBot?.harness_runtime}
              {...harnessComposerProps}
              chatMode={chatMode}
            />
          </ChatComposerShell>
        </div>
      </div>
    </div>
  );
}
