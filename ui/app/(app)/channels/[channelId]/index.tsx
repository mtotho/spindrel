import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, useLocation, useMatch } from "react-router-dom";
import { PipelineRunModal } from "./PipelineRunModal";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ChevronUp, ChevronDown } from "lucide-react";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { OmniPanel } from "./OmniPanel";
import { MobileOmniSheet } from "./MobileOmniSheet";
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
import { FolderOpen, Cog, Settings as SettingsIcon, Users as UsersIcon, PanelRight as PanelRightIcon, LayoutDashboard as LayoutDashboardIcon } from "lucide-react";
import { SecretWarningDialog } from "@/src/components/chat/SecretWarningDialog";
import { ActiveWorkflowStrip } from "./ActiveWorkflowStrip";
import { ActiveBadgeBar } from "./ActiveBadgeBar";
import { useIntegrationHuds } from "@/src/api/hooks/useChatHud";
import { HudStatusStrip } from "./hud/HudStatusStrip";
import { HudSidePanel } from "./hud/HudSidePanel";
import { HudInputBar } from "./hud/HudInputBar";
import { HudFloatingAction } from "./hud/HudFloatingAction";
import { ErrorBanner, SecretWarningBanner } from "./ChatBanners";
import { PinnedPanelsRail } from "@/src/components/chat/PinnedPanels";
import { ParticipantsPanel } from "./ParticipantsPanel";
import { BotInfoPanel } from "@/src/components/chat/BotInfoPanel";
import { TriggerCard, SUPPORTED_TRIGGERS } from "@/src/components/chat/TriggerCard";
import { TaskRunEnvelope } from "@/src/components/chat/TaskRunEnvelope";
import { shouldGroup, formatDateSeparator, isDifferentDay, getTurnText } from "./chatUtils";
import { ChatMessageArea, DateSeparator } from "./ChatMessageArea";
import { ChannelPendingApprovals } from "./ChannelPendingApprovals";
import { ChannelHeader } from "./ChannelHeader";
import { OrchestratorLaunchpad } from "./OrchestratorEmptyState";
import { useChannelPipelines } from "@/src/api/hooks/useChannelPipelines";
import { FindingsPanel, FindingsSheet, useFindings } from "./FindingsPanel";
import { ChatScreenSkeleton } from "./ChatScreenSkeleton";
import { useChannelChat } from "./useChannelChat";
import type { Message } from "@/src/types/api";

import type { ActiveHud } from "@/src/api/hooks/useChatHud";

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
    if (channel?.name) enrichRecentPage(loc.pathname, channel.name);
  }, [channel?.name, loc.pathname, enrichRecentPage]);

  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [participantsPanelOpen, setParticipantsPanelOpen] = useState(false);
  const [findingsPanelOpen, setFindingsPanelOpen] = useState(false);
  const [botInfoBotId, setBotInfoBotId] = useState<string | null>(null);
  const memberBotCount = channel?.member_bots?.length ?? 0;
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
      const bubble = <MessageBubble message={item} botName={bot?.name} isGrouped={isGrouped} onBotClick={handleBotClick} fullTurnText={fullTurnText} channelId={channelId} isLatestBotMessage={isLatestBotMessage} isMobile={columns === "single"} />;
      return <>{dateSep}{bubble}</>;
    },
    [invertedData, bot?.name, handleBotClick, channelId, latestAnchorByGroup, columns]
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
  const fileDirtyRef = useRef(false);

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

    if (memberBotCount > 0 && !isSystemChannel) {
      actions.push({
        id: `channel:${channelId}:participants`,
        label: "Participants",
        hint: channelLabel,
        icon: UsersIcon,
        category: "This Channel",
        onSelect: () => setParticipantsPanelOpen((p) => !p),
      });
    }

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
    memberBotCount,
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
  };

  // Measured height of the header overlay (desktop) so the chat scroll can
  // reserve matching top padding — content flows under the frosted header.
  const headerOverlayRef = useRef<HTMLDivElement>(null);
  const [headerOverlayHeight, setHeaderOverlayHeight] = useState(52);
  useEffect(() => {
    if (!headerOverlayRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height;
      if (h) setHeaderOverlayHeight(Math.ceil(h));
    });
    ro.observe(headerOverlayRef.current);
    return () => ro.disconnect();
  }, []);

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
    <div ref={headerOverlayRef} style={{
      flexShrink: 0,
      backdropFilter: "blur(12px)",
      WebkitBackdropFilter: "blur(12px)",
      backgroundColor: `${t.surface}cc`,
    }}>
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
          activeFile={activeFile}
          splitMode={splitMode}
          onToggleSplit={toggleSplit}
          memberBotCount={memberBotCount}
          participantsPanelOpen={participantsPanelOpen}
          toggleParticipantsPanel={() => setParticipantsPanelOpen((p) => !p)}
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
              <ActiveWorkflowStrip channelId={channelId!} />
              {inputBars.map((h) => (
                <HudInputBar key={h.key} hud={h} />
              ))}
              <MessageInput {...messageInputProps} />
            </div>
          </div>
          {/* Mobile participants overlay */}
          {participantsPanelOpen && channelId && (
            <ParticipantsPanel
              channelId={channelId}
              primaryBotId={channel?.bot_id ?? ""}
              primaryBotName={bot?.name}
              onClose={() => setParticipantsPanelOpen(false)}
              mobile
            />
          )}
          {/* Mobile OmniPanel bottom sheet — hidden on system channels. */}
          {channelId && !isSystemChannel && (
            <MobileOmniSheet
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
        /* ---- Desktop/tablet: side-by-side layout ----
           OmniPanel runs floor-to-ceiling (it owns its own header); the channel
           header overlays ONLY the chat column so the panel feels like a
           standalone card with its own top edge, per the Claude-style reference. */
        <div style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden" }}>
          {/* OmniPanel — always rendered, animated via width clip.
              Hidden on system channels (orchestrator has no workspace files
              or channel-specific pinned widgets worth surfacing).
              Outer padding (pl-1.5 py-1.5) creates the 6px floating-card gap. */}
          {channelId && !isSystemChannel && (
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

          {/* Chat column -- header + messages + input stacked vertically.
              Header lives HERE (inside the column) on desktop so it doesn't
              overlap the full-height OmniPanel. Messages and input cap at
              820px centered for readability. */}
          {(!showFileViewer || splitMode) && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
              <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
                {/* Header overlays the chat area so messages scroll behind
                    the frosted bar (bg + blur applied to the wrapper). */}
                <div style={{ position: "absolute", top: 0, left: 0, right: 0, zIndex: 5 }}>
                  {channelHeaderBlock}
                </div>
                <ChatMessageArea
                  {...messageAreaProps}
                  scrollPaddingTop={headerOverlayHeight}
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
                  <ActiveWorkflowStrip channelId={channelId!} />
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

          {/* Participants panel (multi-bot channels) */}
          {!isMobile && participantsPanelOpen && channelId && (
            <ParticipantsPanel
              channelId={channelId}
              primaryBotId={channel?.bot_id ?? ""}
              primaryBotName={bot?.name}
              onClose={() => setParticipantsPanelOpen(false)}
            />
          )}

          {/* Findings panel — pipelines awaiting user approval (system channels only) */}
          {!isMobile && isSystemChannel && findingsPanelOpen && channelId && (
            <FindingsPanel
              channelId={channelId}
              onClose={() => setFindingsPanelOpen(false)}
            />
          )}
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
    <div className="chat-fade-in" style={{ display: "flex", flexDirection: "column", flex: 1, backgroundColor: t.surface, overflow: "hidden" }}>
      {outerChildren}
      <ChannelModalMount />
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
  return null;
}
