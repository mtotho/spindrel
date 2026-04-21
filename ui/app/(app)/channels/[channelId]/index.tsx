import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, useLocation, useMatch, useSearchParams } from "react-router-dom";
import { PipelineRunModal } from "./PipelineRunModal";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ChevronUp, ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { OmniPanel } from "./OmniPanel";
import { WidgetDockRight } from "./WidgetDockRight";
import { MobileChannelDrawer } from "./MobileChannelDrawer";
import { ChannelFileViewer } from "./ChannelFileViewer";
import { MobileFileViewerSlide } from "./MobileFileViewerSlide";
import { ResizeHandle } from "@/src/components/workspace/ResizeHandle";
import { MessageBubble } from "@/src/components/chat/MessageBubble";
import { MessageInput } from "@/src/components/chat/MessageInput";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { useChannelReadStore } from "@/src/stores/channelRead";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChannel, useChannelContextBudget, useChannelConfigOverhead } from "@/src/api/hooks/useChannels";
import { useBot } from "@/src/api/hooks/useBots";
import { useSystemStatus } from "@/src/api/hooks/useSystemStatus";
import { useAuthStore } from "@/src/stores/auth";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { usePaletteActions, type PaletteAction } from "@/src/stores/paletteActions";
import { FolderOpen, Cog, Settings as SettingsIcon, PanelRight as PanelRightIcon, LayoutDashboard as LayoutDashboardIcon } from "lucide-react";
import { SecretWarningDialog } from "@/src/components/chat/SecretWarningDialog";
import { ActiveBadgeBar } from "./ActiveBadgeBar";
import { useIntegrationHuds } from "@/src/api/hooks/useChatHud";
import { HudStatusStrip } from "./hud/HudStatusStrip";
import { HudSidePanel } from "./hud/HudSidePanel";
import { HudInputBar } from "./hud/HudInputBar";
import { HudFloatingAction } from "./hud/HudFloatingAction";
import { ErrorBanner, SecretWarningBanner } from "./ChatBanners";
import { PinnedPanelsRail } from "@/src/components/chat/PinnedPanels";
import { BotInfoPanel } from "@/src/components/chat/BotInfoPanel";
import { TriggerCard, SUPPORTED_TRIGGERS } from "@/src/components/chat/TriggerCard";
import { TaskRunEnvelope } from "@/src/components/chat/TaskRunEnvelope";
import { shouldGroup, formatDateSeparator, isDifferentDay, getTurnText } from "./chatUtils";
import { ChatMessageArea, DateSeparator } from "./ChatMessageArea";
import { ChannelPendingApprovals } from "./ChannelPendingApprovals";
import { ChannelHeader } from "./ChannelHeader";
import { ChannelHeaderChip } from "./ChannelHeaderChip";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { useScratchReturnStore } from "@/src/stores/scratchReturn";
import { ScratchBanner } from "@/src/components/chat/ScratchBanner";
import { ScratchHistoryModal } from "@/src/components/chat/ScratchHistoryModal";
import { useResetScratchSession } from "@/src/api/hooks/useEphemeralSession";
import { OrchestratorLaunchpad } from "./OrchestratorEmptyState";
import { useChannelPipelines } from "@/src/api/hooks/useChannelPipelines";
import { FindingsPanel, FindingsSheet, useFindings } from "./FindingsPanel";
import { ChatScreenSkeleton } from "./ChatScreenSkeleton";
import { useChannelChat } from "./useChannelChat";
import type { Message } from "@/src/types/api";
import { ChatSession } from "@/src/components/chat/ChatSession";
import { SessionChatView } from "@/src/components/chat/SessionChatView";
import { ThreadParentAnchor } from "@/src/components/chat/ThreadParentAnchor";
import { useSubmitChat } from "@/src/api/hooks/useChat";
import { selectIsStreaming } from "@/src/stores/chat";
import {
  useThreadSummaries,
  useThreadInfo,
} from "@/src/api/hooks/useThreads";
import { MessageCircle, X as CloseIcon } from "lucide-react";

import type { ActiveHud } from "@/src/api/hooks/useChatHud";

/** Peek tab — thin floating chevron on the viewport edge that re-opens a
 *  collapsed dock. Sits above most chat chrome but below modals/drawers so it
 *  doesn't fight a slide-in panel. */
function DockPeekTab({
  side,
  onClick,
  title,
}: {
  side: "left" | "right";
  onClick: () => void;
  title: string;
}) {
  const positionClass = side === "left" ? "left-0" : "right-0";
  const radiusClass = side === "left" ? "rounded-r-md" : "rounded-l-md";
  const Icon = side === "left" ? ChevronRight : ChevronLeft;
  // Absolute positioning anchors to the chat flex-row container (NOT the
  // viewport) so the left tab sits just right of the app shell's channel
  // rail instead of hiding behind it.
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={title}
      title={title}
      className={`absolute top-1/2 -translate-y-1/2 ${positionClass} ${radiusClass} z-[25]
                  flex items-center justify-center
                  w-4 h-16
                  bg-surface-raised/80 hover:bg-surface-raised
                  border border-surface-border/60
                  text-text-dim hover:text-text
                  transition-colors shadow-md
                  backdrop-blur-sm`}
    >
      <Icon size={12} />
    </button>
  );
}

/** Collapsible wrapper around HUD status strips with a toggle icon.
 *
 * On mobile (`compact`), the HUD defaults to collapsed — it's channel chrome
 * the user can opt into, not something we shove above every conversation.
 * On desktop the legacy expanded-by-default behavior is preserved. The
 * `hudCollapsedChannels` store value records the user's *explicit* toggle,
 * so a tap to collapse on desktop also persists to mobile and vice versa.
 */
function HudStripBar({
  statusStrips,
  channelId,
  compact,
}: {
  statusStrips: ActiveHud[];
  channelId: string;
  compact: boolean;
}) {
  const t = useThemeTokens();
  const explicitlyCollapsed = useUIStore((s) => s.hudCollapsedChannels.includes(channelId));
  const explicitlyExpanded = useUIStore((s) => s.hudExpandedOnMobile.includes(channelId));
  const toggleHud = useUIStore((s) => s.toggleHudCollapsed);
  const toggleMobileExpand = useUIStore((s) => s.toggleHudExpandedOnMobile);
  const hudCollapsed = compact
    ? (!explicitlyExpanded || explicitlyCollapsed)
    : explicitlyCollapsed;
  const handleToggle = () => {
    if (compact) toggleMobileExpand(channelId);
    else toggleHud(channelId);
  };

  if (hudCollapsed) {
    return (
      <button
        onClick={handleToggle}
        aria-label="Expand HUD"
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          padding: "10px 0",
          minHeight: 28,
          border: "none",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          background: t.surfaceRaised,
          cursor: "pointer",
          width: "100%",
          opacity: 0.6,
        }}
      >
        <ChevronDown size={12} color={t.textDim} />
        <span style={{ fontSize: 10, color: t.textDim }}>HUD</span>
      </button>
    );
  }

  return (
    <div style={{ position: "relative" }}>
      {statusStrips.map((h) => (
        <HudStatusStrip key={h.key} hud={h} compact={compact} />
      ))}
      <button
        onClick={handleToggle}
        className="header-icon-btn"
        style={{
          position: "absolute",
          right: 0,
          top: 0,
          width: 32,
          height: 32,
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 0,
          borderRadius: 4,
          display: "flex", flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          opacity: 0.4,
        }}
        title="Collapse HUD"
        aria-label="Collapse HUD"
      >
        <ChevronUp size={12} color={t.textDim} />
      </button>
    </div>
  );
}

export default function ChatScreen() {
  const { channelId } = useParams<{ channelId: string }>();
  const goBack = useGoBack("/");
  const navigate = useNavigate();

  const { data: channel, isLoading: channelLoading } = useChannel(channelId);
  const { data: bot } = useBot(channel?.bot_id);
  const { data: systemStatus } = useSystemStatus();
  const { data: savedBudget } = useChannelContextBudget(channelId);
  const { data: configOverheadData } = useChannelConfigOverhead(channelId);
  const isPaused = systemStatus?.paused ?? false;
  const columns = useResponsiveColumns();
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const { statusStrips, sidePanels, inputBars, floatingActions } = useIntegrationHuds(channelId);

  const showHamburger = columns === "single" || sidebarCollapsed;
  const t = useThemeTokens();

  const markRead = useChannelReadStore((s) => s.markRead);

  // Mark channel as read on mount / channel switch
  useEffect(() => {
    if (channelId) markRead(channelId);
  }, [channelId]);

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
    // Scratch sub-pages under /session/:sid get a friendlier recents label
    // so the command palette shows "Scratch · #channel" instead of a URL
    // guid. Archive deep links get the same prefix + " (archive)" suffix.
    const isScratchPath = /\/channels\/[^/]+\/session\//.test(loc.pathname);
    if (isScratchPath) {
      const archiveSuffix = loc.search.includes("archive=true") ? " (archive)" : "";
      enrichRecentPage(loc.pathname, `Scratch · #${channel.name}${archiveSuffix}`);
    } else {
      enrichRecentPage(loc.pathname, channel.name);
    }
  }, [channel?.name, loc.pathname, loc.search, enrichRecentPage]);

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
    handleSendNow,
    cancelQueue,
  } = useChannelChat({ channelId, channel, activeFile });

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

  // ---- Scratch full-page mode (URL-driven) ----
  // Route: /channels/:channelId/session/:sessionId?scratch=true[&archive=true]
  // Swaps the main chat column with the scratch ephemeral chat against the
  // URL-provided session id. Rail/header/dock-right/widgets all keep
  // rendering normally — only the center column changes.
  const sessionMatch = useMatch("/channels/:channelId/session/:sessionId");
  const [scratchSearch] = useSearchParams();
  const isScratchRoute =
    !!sessionMatch && scratchSearch.get("scratch") === "true";
  const scratchUrlSessionId = sessionMatch?.params.sessionId ?? null;
  const scratchIsArchive = scratchSearch.get("archive") === "true";
  const setScratchReturn = useScratchReturnStore((s) => s.setScratchReturn);
  const clearScratchReturn = useScratchReturnStore((s) => s.clearScratchReturn);
  const [scratchHistoryOpen, setScratchHistoryOpen] = useState(false);

  // Track "last scratch session per channel" so a widget-dashboard detour
  // can bring the user back to the same scratch context. Archive deep
  // links should not hijack the return target — only the live scratch
  // does. Explicit exit is the banner's "minimize" click.
  useEffect(() => {
    if (isScratchRoute && scratchUrlSessionId && channelId && !scratchIsArchive) {
      setScratchReturn(channelId, scratchUrlSessionId);
    }
  }, [
    isScratchRoute,
    scratchUrlSessionId,
    channelId,
    scratchIsArchive,
    setScratchReturn,
  ]);

  // Scratch reset — used by the ChannelHeader Reset button when the URL is
  // on the scratch full-page. Two-click speed bump mirrors the in-column
  // reset button behavior in EphemeralChatSession.
  const resetScratchMutation = useResetScratchSession();
  const [scratchResetArmed, setScratchResetArmed] = useState(false);
  useEffect(() => {
    if (!scratchResetArmed) return;
    const t = window.setTimeout(() => setScratchResetArmed(false), 3000);
    return () => window.clearTimeout(t);
  }, [scratchResetArmed]);
  const handleScratchHeaderReset = useCallback(() => {
    if (!scratchResetArmed) {
      setScratchResetArmed(true);
      return;
    }
    if (channelId && channel?.bot_id) {
      resetScratchMutation.mutate({
        parent_channel_id: channelId,
        bot_id: channel.bot_id,
      });
    }
    setScratchResetArmed(false);
  }, [scratchResetArmed, channelId, channel?.bot_id, resetScratchMutation]);

  // ---- Scratch chat (in-channel ephemeral) state ----
  const [scratchOpen, setScratchOpen] = useState(false);

  // Memoize the scratch chat source so EphemeralChatSession doesn't see a
  // new `context`/`source` reference on every channel re-render. Without
  // this, `handleSend` (which closes over `context`) is rebuilt every
  // render, churning MessageInput and downstream effects — the chain that
  // triggers React #185 ("Maximum update depth exceeded") on FAB click.
  const scratchSource = useMemo(
    () =>
      channelId
        ? ({
            kind: "ephemeral" as const,
            sessionStorageKey: `channel:${channelId}:scratch`,
            parentChannelId: channelId,
            defaultBotId: channel?.bot_id,
            context: {
              page_name: "channel_scratch",
              payload: { channel_id: channelId },
            },
            // Cross-device continuity — resolves (user, channel, bot)
            // via /sessions/scratch/current instead of localStorage.
            scratchBoundChannelId: channelId,
          })
        : null,
    [channelId, channel?.bot_id],
  );

  const handleScratchClose = useCallback(() => setScratchOpen(false), []);
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
      const fullTurnText = getTurnText(invertedData, headerIdx);
      const isLatestBotMessage = item.role === "assistant" && index === 0;
      const threadSummary = threadSummaries?.[item.id] ?? null;
      const bubble = <MessageBubble message={item} botName={bot?.name} isGrouped={isGrouped} onBotClick={handleBotClick} fullTurnText={fullTurnText} channelId={channelId} isLatestBotMessage={isLatestBotMessage} isMobile={columns === "single"} threadSummary={threadSummary} onReplyInThread={handleReplyInThread} canReplyInThread={true} chatMode={chatMode} />;
      return <>{dateSep}{bubble}</>;
    },
    [invertedData, bot?.name, handleBotClick, channelId, latestAnchorByGroup, columns, threadSummaries, handleReplyInThread, chatMode]
  );

  // ---- Workspace / file explorer state ----
  const workspaceId = channel?.resolved_workspace_id;
  const explorerWidth = useFileBrowserStore((s) => s.channelExplorerWidth);
  const setExplorerWidth = useFileBrowserStore((s) => s.setChannelExplorerWidth);

  const explorerOpen = useUIStore((s) => s.fileExplorerOpen);
  const toggleExplorer = useUIStore((s) => s.toggleFileExplorer);
  const setExplorerOpen = useUIStore((s) => s.setFileExplorerOpen);
  const splitMode = useUIStore((s) => s.fileExplorerSplit);
  const toggleSplit = useUIStore((s) => s.toggleFileExplorerSplit);
  const rightDockHidden = useUIStore((s) => s.rightDockHidden);
  const setRightDockHidden = useUIStore((s) => s.setRightDockHidden);
  const fileDirtyRef = useRef(false);

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
  const { header: headerChipPins } = useChannelChatZones(channelId ?? "");
  const hasHeaderChips = headerChipPins.length > 0;

  // "Browse files" gesture — opens the OmniPanel on the Files tab and
  // auto-focuses its filter input. Replaces the old BrowseFilesModal.
  const requestFilesFocus = useUIStore((s) => s.requestFilesFocus);
  const openBrowseFiles = useCallback(() => {
    requestFilesFocus();
  }, [requestFilesFocus]);

  // Keyboard shortcuts for explorer/split/file viewer/browse
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      // Cmd+Shift+B → Browse files (OmniPanel Files tab + focus filter).
      // Check before the plain Cmd+B branch since `e.key` is just "b" either way.
      if (mod && e.shiftKey && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        requestFilesFocus();
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
        const tag = (e.target as HTMLElement)?.tagName;
        if (tag !== "INPUT" && tag !== "TEXTAREA") {
          setActiveFile(null);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleExplorer, toggleSplit, activeFile, requestFilesFocus]);

  // Reset file selection when switching channels
  useEffect(() => {
    setActiveFile(null);
    fileDirtyRef.current = false;
  }, [channelId]);

  // OmniPanel is always available — it shows pinned widgets even without a workspace.
  // The file explorer section inside OmniPanel is conditionally shown when workspaceId exists.
  const showExplorer = explorerOpen;
  const showFileViewer = activeFile !== null;
  const isMobile = columns === "single";

  // Chat-screen layout mode. Controls which dashboard zones surface on the
  // chat screen itself. Mobile drawer always shows every zone regardless.
  const showRailZone = layoutMode !== "dashboard-only";
  const showHeaderChips = layoutMode === "full" || layoutMode === "rail-header-chat";
  const showDockZone = layoutMode === "full";
  const dashboardOnly = layoutMode === "dashboard-only";

  // Auto-enable split mode on wide screens when a file is first opened.
  const autoSplitApplied = useRef(false);
  useEffect(() => {
    if (showFileViewer && columns === "triple" && !splitMode && !autoSplitApplied.current) {
      autoSplitApplied.current = true;
      toggleSplit();
    }
  }, [showFileViewer, columns, splitMode, toggleSplit]);

  // Dirty-file guard: instead of window.confirm, use a ConfirmDialog
  type DirtyAction = { type: "select"; path: string } | { type: "close" } | { type: "closeExplorer" };
  const [pendingDirtyAction, setPendingDirtyAction] = useState<DirtyAction | null>(null);

  const tryOrConfirmDirty = useCallback((action: DirtyAction) => {
    if (!fileDirtyRef.current) return action; // not dirty, proceed immediately
    setPendingDirtyAction(action);
    return null; // blocked, waiting for confirm
  }, []);

  const executeDirtyAction = useCallback((action: DirtyAction) => {
    switch (action.type) {
      case "select": setActiveFile(action.path); break;
      case "close": setActiveFile(null); break;
      case "closeExplorer": setExplorerOpen(false); setActiveFile(null); break;
    }
  }, [setExplorerOpen]);

  const handleDirtyChange = useCallback((dirty: boolean) => {
    fileDirtyRef.current = dirty;
  }, []);

  const handleSelectFile = useCallback((path: string) => {
    if (path === activeFile) return;
    const action: DirtyAction = { type: "select", path };
    if (!fileDirtyRef.current) { executeDirtyAction(action); return; }
    setPendingDirtyAction(action);
  }, [activeFile, executeDirtyAction]);

  const handleCloseFile = useCallback(() => {
    const action: DirtyAction = { type: "close" };
    if (!fileDirtyRef.current) { executeDirtyAction(action); return; }
    setPendingDirtyAction(action);
  }, [executeDirtyAction]);

  const handleCloseExplorer = useCallback(() => {
    const action: DirtyAction = { type: "closeExplorer" };
    if (!fileDirtyRef.current) { executeDirtyAction(action); return; }
    setPendingDirtyAction(action);
  }, [executeDirtyAction]);

  // Mobile: back from file viewer goes to explorer, back from explorer goes to chat
  const handleMobileBack = useCallback(() => {
    if (activeFile) {
      setActiveFile(null);
    } else {
      setExplorerOpen(false);
    }
  }, [activeFile, setExplorerOpen]);

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

    if (workspaceId && !isSystemChannel) {
      actions.push({
        id: `channel:${channelId}:browse-files`,
        label: "Browse files in this channel",
        hint: channelLabel,
        icon: FolderOpen,
        category: "This Channel",
        onSelect: () => openBrowseFiles(),
      });
    }

    if (!isSystemChannel) {
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
        onSelect: () => navigate(`/widgets/channel/${channelId}`),
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
    workspaceId,
    isSystemChannel,
    findingsCount,
    channel?.bot_id,
    navigate,
    registerPaletteActions,
  ]);

  // ---- Shared message input props ----
  const messageInputProps = {
    onSend: handleSend,
    onSendAudio: handleSendAudio,
    disabled: isPaused,
    isStreaming: Object.keys(chatState.turns).length > 0 || chatState.isProcessing,
    onCancel: handleCancel,
    modelOverride: turnModelOverride,
    modelProviderIdOverride: turnProviderIdOverride,
    onModelOverrideChange: handleModelOverrideChange,
    defaultModel: channel?.model_override || bot?.model,
    currentBotId: channel?.bot_id,
    isMultiBot: (channel?.member_bots?.length ?? 0) > 0,
    channelId,
    onSlashCommand: handleSlashCommand,
    isQueued,
    onCancelQueue: cancelQueue,
    onSendNow: handleSendNow,
    configOverhead: configOverheadData?.overhead_pct ?? null,
    onConfigOverheadClick: () => setBotInfoBotId(channel?.bot_id || null),
    chatMode,
  };

  // ---- Shared message area props ----
  const messageAreaProps = {
    invertedData,
    renderMessage,
    chatState,
    bot,
    botId: channel?.bot_id,
    pendingApprovalsSlot: channelId
      ? (liveApprovalIds: Set<string>) => (
          <ChannelPendingApprovals channelId={channelId} liveApprovalIds={liveApprovalIds} />
        )
      : undefined,
    isLoading,
    isFetchingNextPage,
    hasNextPage,
    handleLoadMore,
    isProcessing: chatState.isProcessing,
    t,
    chatMode,
  };

  // ---- Scratch column (full-page mode) ----
  // When isScratchRoute is true, swaps in for the normal chat column. Wraps
  // the shared ChatSession ephemeral component in shape="fullpage" so we
  // reuse all the send/reset/history plumbing without a dock or modal
  // around it.
  const scratchFullpageSource = useMemo(() => {
    if (!isScratchRoute || !channelId || !scratchUrlSessionId) return null;
    return {
      kind: "ephemeral" as const,
      sessionStorageKey: `channel:${channelId}:scratch`,
      parentChannelId: channelId,
      defaultBotId: channel?.bot_id,
      context: {
        page_name: "channel_scratch",
        payload: { channel_id: channelId },
      },
      scratchBoundChannelId: channelId,
      pinnedSessionId: scratchUrlSessionId,
      readOnly: scratchIsArchive,
    };
  }, [
    isScratchRoute,
    channelId,
    scratchUrlSessionId,
    channel?.bot_id,
    scratchIsArchive,
  ]);

  const scratchColumnNode =
    scratchFullpageSource && channelId ? (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
        <ScratchBanner
          channelId={channelId}
          channelName={channel?.name}
          archive={scratchIsArchive}
        />
        <div style={{ flex: 1, minHeight: 0 }}>
          <ChatSession
            source={scratchFullpageSource}
            shape="fullpage"
            open
            onClose={() => {
              clearScratchReturn(channelId);
              navigate(`/channels/${channelId}`);
            }}
            title={scratchIsArchive ? "Archived scratch" : "Scratch pad"}
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
          workspaceId={workspaceId}
          explorerOpen={explorerOpen}
          toggleExplorer={toggleExplorer}
          onBrowseWorkspace={openBrowseFiles}
          isMobile={isMobile}
          contextBudget={chatState.contextBudget ?? (
            savedBudget?.utilization != null ? {
              utilization: savedBudget.utilization,
              consumed: savedBudget.consumed_tokens ?? 0,
              total: savedBudget.total_tokens ?? 0,
            } : null
          )}
          onContextBudgetClick={() => setBotInfoBotId(channel?.bot_id || null)}
          isSystemChannel={isSystemChannel}
          findingsPanelOpen={isSystemChannel ? findingsPanelOpen : undefined}
          toggleFindingsPanel={isSystemChannel ? () => setFindingsPanelOpen((p) => !p) : undefined}
          findingsCount={isSystemChannel ? findingsCount : 0}
          scratchOpen={isScratchRoute || scratchOpen}
          onOpenScratch={() => {
            if (isScratchRoute && channelId) {
              // Already in scratch → clicking the button is the "minimize"
              // action. Clear return target + go back to channel chat.
              clearScratchReturn(channelId);
              navigate(`/channels/${channelId}`);
              return;
            }
            setScratchOpen(true);
          }}
          scratchFullpageMode={
            isScratchRoute
              ? {
                  onOpenHistory: () => setScratchHistoryOpen(true),
                  onReset: handleScratchHeaderReset,
                  resetArmed: scratchResetArmed,
                  archive: scratchIsArchive,
                }
              : undefined
          }
        />
        {/* Desktop: integration dots inlined into ChannelHeader subtitle.
            Mobile: retain the compact scrolling bar (no subtitle row to inline into). */}
        {channelId && isMobile && <ActiveBadgeBar channelId={channelId} compact />}

      {statusStrips.length > 0 && (
        <HudStripBar
          statusStrips={statusStrips}
          channelId={channelId!}
          compact={isMobile}
        />
      )}

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
  // `pointer-events-none` on the wrapper lets clicks pass through dead space
  // to the chat below; the chip itself re-enables pointer events. The chip
  // already carries its own surface + border, so no enclosing pill chrome.
  const headerChipOverlay =
    !isMobile && channelId && hasHeaderChips && showHeaderChips ? (
      <div className="absolute left-1/2 -translate-x-1/2 top-1 z-20 pointer-events-none flex justify-center">
        <div className="pointer-events-auto">
          <ChannelHeaderChip channelId={channelId} />
        </div>
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
          {scratchColumnNode ? (
            scratchColumnNode
          ) : (
          <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
            <ChatMessageArea {...messageAreaProps} scrollPaddingBottom={inputOverlayHeight + (isMobile ? 32 : 48)} />
            {floatingActions.map((h) => (
              <HudFloatingAction key={h.key} hud={h} />
            ))}
            {/* Composer overlay — messages scroll behind the frosted input. */}
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
              {inputBars.map((h) => (
                <HudInputBar key={h.key} hud={h} />
              ))}
              <MessageInput {...messageInputProps} />
            </div>
          </div>
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
              workspaceId={workspaceId ?? undefined}
              botId={channel?.bot_id}
              channelDisplayName={channel?.display_name || channel?.name}
              activeFile={activeFile}
              onSelectFile={handleSelectFile}
            />
          )}
          {/* Mobile file viewer — slides in over the chat, chat stays mounted. */}
          <MobileFileViewerSlide
            open={showFileViewer}
            channelId={channelId!}
            workspaceId={workspaceId ?? undefined}
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
           The row beneath houses OmniPanel | chat | PinnedPanelsRail | WidgetDockRight. */
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minHeight: 0 }}>
          {channelHeaderBlock}
        <div style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden", position: "relative", minHeight: 0 }}>
          {headerChipOverlay}
          {/* OmniPanel — always rendered, animated via width clip.
              Hidden on system channels (orchestrator has no workspace files
              or channel-specific pinned widgets worth surfacing) and when
              the channel's layout_mode is "dashboard-only".
              Outer padding (pl-1.5 py-1.5) creates the 6px floating-card gap. */}
          {channelId && !isSystemChannel && showRailZone && (
            <div
              className="pl-2.5 py-2.5"
              style={{
                width: showExplorer ? explorerWidth + 10 : 0,
                overflow: "hidden",
                transition: "width 200ms cubic-bezier(0.4, 0, 0.2, 1)",
                flexShrink: 0,
              }}
            >
              <OmniPanel
                channelId={channelId}
                workspaceId={workspaceId ?? undefined}
                botId={channel?.bot_id}
                channelDisplayName={channel?.display_name || channel?.name}
                activeFile={activeFile}
                onSelectFile={handleSelectFile}
                onClose={handleCloseExplorer}
                width={explorerWidth}
              />
            </div>
          )}
          {showExplorer && channelId && (
            <ResizeHandle
              direction="horizontal"
              onResize={(delta) => setExplorerWidth(explorerWidth + delta)}
              invisible
            />
          )}

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
                  onClick={() => navigate(`/widgets/channel/${channelId}`)}
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
          {!dashboardOnly && (!showFileViewer || splitMode) && scratchColumnNode && (
            scratchColumnNode
          )}
          {!dashboardOnly && (!showFileViewer || splitMode) && !scratchColumnNode && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
              <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
                <ChatMessageArea
                  {...messageAreaProps}
                  scrollPaddingTop={0}
                  scrollPaddingBottom={inputOverlayHeight + 48}
                />
                {floatingActions.map((h) => (
                  <HudFloatingAction key={h.key} hud={h} />
                ))}
                {/* Composer overlay — messages scroll behind the frosted input.
                    Banners + strips + bars + input all share the overlay so
                    they sit above the chat content at the bottom. */}
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
                  {inputBars.map((h) => (
                    <HudInputBar key={h.key} hud={h} />
                  ))}
                  <div className="w-full mx-auto max-w-[820px] px-4">
                    <MessageInput {...messageInputProps} />
                  </div>
                </div>
              </div>
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
                workspaceId={workspaceId ?? undefined}
                filePath={activeFile!}
                onBack={handleCloseFile}
                splitMode={splitMode}
                onToggleSplit={toggleSplit}
                onDirtyChange={handleDirtyChange}
              />
            </div>
          )}

          {/* HUD side panels */}
          {!isMobile && sidePanels.map((h) => (
            <HudSidePanel key={h.key} hud={h} />
          ))}

          {/* Pinned workspace-file panels — hidden on system channels. */}
          {!isMobile && channelId && !isSystemChannel && (
            <PinnedPanelsRail channelId={channelId} workspaceId={workspaceId} />
          )}

          {/* Right-side widget dock — surfaces channel-dashboard pins whose
              left edge sits in the dock-right band. Hidden on system channels
              (no channel dashboard) and when the band is empty. Outer
              `pr-2.5 py-2.5` mirrors the left dock's `pl-2.5 py-2.5` so the
              floating-card gap is symmetric on both sides. */}
          {!isMobile && channelId && !isSystemChannel && !rightDockHidden && showDockZone && (
            <div className="pr-2.5 py-2.5 flex">
              <WidgetDockRight channelId={channelId} />
            </div>
          )}

          {/* Peek tabs — floating chevrons on the viewport edges so the user
              can always un-hide a collapsed dock. The existing in-dock
              chevrons handle the hide direction; these handle un-hide. */}
          {!isMobile && !explorerOpen && channelId && !isSystemChannel && (
            <DockPeekTab side="left" onClick={() => setExplorerOpen(true)} title="Show widgets panel" />
          )}
          {!isMobile && rightDockHidden && channelId && !isSystemChannel && (
            <DockPeekTab side="right" onClick={() => setRightDockHidden(false)} title="Show right dock" />
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
          contextBudget={chatState.contextBudget ?? (
            savedBudget?.utilization != null ? {
              utilization: savedBudget.utilization,
              consumed: savedBudget.consumed_tokens ?? 0,
              total: savedBudget.total_tokens ?? 0,
            } : null
          )}
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
      className={`chat-fade-in${entranceClassActive ? " chat-screen--entering-from-dock" : ""}`}
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
      {threadSource && (
        <ChatSession
          source={threadSource}
          shape="dock"
          open
          onClose={handleClearActiveThread}
          title="Thread"
          initiallyExpanded
        />
      )}
      {scratchSource && !activeThread && !isScratchRoute && (
        <ChatSession
          source={scratchSource}
          shape="dock"
          open={scratchOpen}
          onClose={handleScratchClose}
          title="Scratch chat"
          initiallyExpanded
        />
      )}
      {isScratchRoute && channelId && (
        <ScratchHistoryModal
          open={scratchHistoryOpen}
          onClose={() => setScratchHistoryOpen(false)}
          channelId={channelId}
        />
      )}
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
  const { data: info } = useThreadInfo(threadSessionId);
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
      <ThreadParentAnchor message={info.parent_message ?? null} />
      <ThreadFullScreenBody
        threadSessionId={threadSessionId}
        parentChannelId={channelId}
        botId={info.bot_id}
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
}: {
  threadSessionId: string;
  parentChannelId: string;
  botId: string;
}) {
  const submitChat = useSubmitChat();
  const chatState = useChatStore((s) => s.getChannel(threadSessionId));
  const turnActive = selectIsStreaming(chatState);
  const isSending = submitChat.isPending || turnActive;
  const [sendError, setSendError] = useState<string | null>(null);

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
        });
      } catch (err) {
        setSendError(err instanceof Error ? err.message : "Failed to send message");
      }
    },
    [botId, threadSessionId, parentChannelId, submitChat],
  );

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-1 min-h-0 relative">
        <SessionChatView
          sessionId={threadSessionId}
          parentChannelId={parentChannelId}
          botId={botId}
        />
      </div>
      {sendError && (
        <div className="px-4 py-1.5 text-[11px] text-red-400 border-t border-red-500/20 bg-red-500/5 shrink-0">
          {sendError}
        </div>
      )}
      <div className="shrink-0" style={{ borderTop: "1px solid var(--surface-border)" }}>
        <MessageInput
          onSend={handleSend}
          disabled={!botId}
          isStreaming={isSending}
          currentBotId={botId}
          channelId={threadSessionId}
        />
      </div>
    </div>
  );
}
