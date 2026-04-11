import { useCallback, useEffect, useRef, useState } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { Shield, ChevronUp, ChevronDown } from "lucide-react";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { ChannelFileExplorer } from "./ChannelFileExplorer";
import { ChannelFileViewer } from "./ChannelFileViewer";
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
import { useEnableEditor } from "@/src/api/hooks/useWorkspaces";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { SecretWarningDialog } from "@/src/components/chat/SecretWarningDialog";
import { ActiveWorkflowStrip } from "./ActiveWorkflowStrip";
import { ActiveBadgeBar } from "./ActiveBadgeBar";
import { useIntegrationHuds } from "@/src/api/hooks/useChatHud";
import { HudStatusStrip } from "./hud/HudStatusStrip";
import { HudSidePanel } from "./hud/HudSidePanel";
import { HudInputBar } from "./hud/HudInputBar";
import { HudFloatingAction } from "./hud/HudFloatingAction";
import { ErrorBanner, SecretWarningBanner } from "./ChatBanners";
import { ParticipantsPanel } from "./ParticipantsPanel";
import { BotInfoPanel } from "@/src/components/chat/BotInfoPanel";
import { TriggerCard, SUPPORTED_TRIGGERS } from "@/src/components/chat/TriggerCard";
import { shouldGroup, formatDateSeparator, isDifferentDay, getTurnText } from "./chatUtils";
import { ChatMessageArea, DateSeparator } from "./ChatMessageArea";
import { ChannelHeader } from "./ChannelHeader";
import { useChannelChat } from "./useChannelChat";
import type { Message } from "@/src/types/api";

import type { ActiveHud } from "@/src/api/hooks/useChatHud";

/** Collapsible wrapper around HUD status strips with a toggle icon. */
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
  const hudCollapsed = useUIStore((s) => s.hudCollapsedChannels.includes(channelId));
  const toggleHud = useUIStore((s) => s.toggleHudCollapsed);

  if (hudCollapsed) {
    return (
      <button
        onClick={() => toggleHud(channelId)}
        aria-label="Expand HUD"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          padding: "6px 0",
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
        onClick={() => toggleHud(channelId)}
        className="header-icon-btn"
        style={{
          position: "absolute",
          right: 4,
          top: 2,
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 6,
          borderRadius: 4,
          display: "flex",
          alignItems: "center",
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
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const goBack = useGoBack("/");
  const router = useRouter();

  const { data: channel } = useChannel(channelId);
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

  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [participantsPanelOpen, setParticipantsPanelOpen] = useState(false);
  const [botInfoBotId, setBotInfoBotId] = useState<string | null>(null);
  const memberBotCount = channel?.member_bots?.length ?? 0;

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

  const renderMessage = useCallback(
    ({ item, index }: { item: Message; index: number }) => {
      const prevMsg = invertedData[index + 1];
      const grouped = shouldGroup(item, prevMsg);
      const showDateSep = index === invertedData.length - 1 || (prevMsg && isDifferentDay(item.created_at, prevMsg.created_at));
      const dateSep = showDateSep ? <DateSeparator label={formatDateSeparator(item.created_at)} /> : null;
      const meta = (item.metadata ?? {}) as Record<string, any>;
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
      const bubble = <MessageBubble message={item} botName={bot?.name} isGrouped={isGrouped} onBotClick={handleBotClick} fullTurnText={fullTurnText} />;
      return <>{dateSep}{bubble}</>;
    },
    [invertedData, bot?.name, handleBotClick]
  );

  // ---- Workspace / file explorer state ----
  const workspaceEnabled = channel?.channel_workspace_enabled;
  const workspaceId = channel?.resolved_workspace_id;
  const enableEditorMutation = useEnableEditor(workspaceId ?? "");
  const expandDir = useFileBrowserStore((s) => s.expandDir);
  const explorerWidth = useFileBrowserStore((s) => s.channelExplorerWidth);
  const setExplorerWidth = useFileBrowserStore((s) => s.setChannelExplorerWidth);

  const explorerOpen = useUIStore((s) => s.fileExplorerOpen);
  const toggleExplorer = useUIStore((s) => s.toggleFileExplorer);
  const setExplorerOpen = useUIStore((s) => s.setFileExplorerOpen);
  const splitMode = useUIStore((s) => s.fileExplorerSplit);
  const toggleSplit = useUIStore((s) => s.toggleFileExplorerSplit);
  const fileDirtyRef = useRef(false);

  // Reset file selection when switching channels
  useEffect(() => {
    setActiveFile(null);
    fileDirtyRef.current = false;
  }, [channelId]);

  // Explorer is available whenever the channel resolves to a workspace.
  // (Channel-workspace-enabled is no longer required — the explorer falls back
  // to bot memory when the channel itself has no workspace dir.)
  const showExplorer = !!workspaceId && explorerOpen;
  const showFileViewer = activeFile !== null;
  const isMobile = columns === "single";

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

  const handleBrowseWorkspace = useCallback(() => {
    if (!workspaceId || !channelId) return;
    const segments = ["channels", `channels/${channelId}`, `channels/${channelId}/workspace`];
    for (const seg of segments) expandDir(seg);
  }, [workspaceId, channelId, expandDir]);

  const handleOpenEditor = useCallback(async () => {
    if (!workspaceId || !channelId) return;
    try {
      await enableEditorMutation.mutateAsync();
      const { serverUrl } = useAuthStore.getState();
      const token = getAuthToken();
      const folder = `/workspace/channels/${channelId}`;
      const editorUrl = `${serverUrl}/api/v1/workspaces/${workspaceId}/editor/?tkn=${encodeURIComponent(token || "")}&folder=${encodeURIComponent(folder)}`;
      window.open(editorUrl, `editor-${workspaceId}`);
    } catch (err) {
      console.error("Failed to open editor:", err);
    }
  }, [workspaceId, channelId, enableEditorMutation]);

  const displayName = (channel as any)?.display_name || channel?.name || channel?.client_id || "Chat";

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
    isLoading,
    isFetchingNextPage,
    hasNextPage,
    handleLoadMore,
    isProcessing: chatState.isProcessing,
    t,
  };

  const outerChildren = (
    <>
      {/* Unified header block — glass bg + single bottom border */}
      <div style={{
        borderBottom: `1px solid ${t.surfaceBorder}`,
        flexShrink: 0,
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        backgroundColor: `${t.surface}e6`,
      }}>
        <ChannelHeader
          channelId={channelId!}
          displayName={displayName}
          bot={bot}
          channelModelOverride={channel?.model_override ?? undefined}
          columns={columns}
          showHamburger={showHamburger}
          goBack={goBack}
          toggleSidebar={toggleSidebar}
          workspaceEnabled={workspaceEnabled}
          workspaceId={workspaceId}
          explorerOpen={explorerOpen}
          toggleExplorer={toggleExplorer}
          onBrowseWorkspace={handleBrowseWorkspace}
          onOpenEditor={handleOpenEditor}
          isMobile={isMobile}
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
        />
        {channelId && <ActiveBadgeBar channelId={channelId} compact={isMobile} />}
      </div>

      {/* HUD status strips — collapsible */}
      {statusStrips.length > 0 && (
        <HudStripBar
          statusStrips={statusStrips}
          channelId={channelId!}
          compact={isMobile}
        />
      )}

      {/* Protected channel warning */}
      {channel?.client_id === "orchestrator:home" && (
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            padding: "6px 16px",
            borderBottom: "1px solid rgba(245, 158, 11, 0.2)",
            backgroundColor: "rgba(245, 158, 11, 0.08)",
          }}
        >
          <Shield size={13} color="#d97706" />
          <span style={{ fontSize: 12, color: "#d97706" }}>
            System admin channel — this bot has unrestricted tool access and can delegate to all bots.
          </span>
        </div>
      )}

      {/* Content area -- explorer + chat/file viewer */}
      {isMobile ? (
        /* ---- Mobile: full-screen modes ---- */
        showExplorer && !showFileViewer ? (
          <ChannelFileExplorer
            channelId={channelId!}
            botId={channel?.bot_id}
            workspaceId={workspaceId ?? undefined}
            channelDisplayName={channel?.display_name || channel?.name}
            channelWorkspaceEnabled={!!workspaceEnabled}
            activeFile={activeFile}
            onSelectFile={handleSelectFile}
            onClose={handleCloseExplorer}
            fullWidth
          />
        ) : showFileViewer ? (
          <ChannelFileViewer
            channelId={channelId!}
            workspaceId={workspaceId ?? undefined}
            filePath={activeFile!}
            onBack={handleMobileBack}
            onDirtyChange={handleDirtyChange}
          />
        ) : (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative", minHeight: 0 }}>
            <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
              <ChatMessageArea {...messageAreaProps} />
              {floatingActions.map((h) => (
                <HudFloatingAction key={h.key} hud={h} />
              ))}
            </div>
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
          </div>
        )
      ) : (
        /* ---- Desktop/tablet: side-by-side layout ---- */
        <div style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden" }}>
          {/* Explorer panel + resize handle */}
          {showExplorer && channelId && (
            <>
              <ChannelFileExplorer
                channelId={channelId}
                botId={channel?.bot_id}
                workspaceId={workspaceId ?? undefined}
                channelDisplayName={channel?.display_name || channel?.name}
                channelWorkspaceEnabled={!!workspaceEnabled}
                activeFile={activeFile}
                onSelectFile={handleSelectFile}
                onClose={handleCloseExplorer}
                width={explorerWidth}
              />
              <ResizeHandle
                direction="horizontal"
                onResize={(delta) => setExplorerWidth(explorerWidth + delta)}
              />
            </>
          )}

          {/* Chat column -- messages + input stacked vertically */}
          {(!showFileViewer || splitMode) && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
              <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
                <ChatMessageArea {...messageAreaProps} />
                {floatingActions.map((h) => (
                  <HudFloatingAction key={h.key} hud={h} />
                ))}
              </div>
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

          {/* Participants panel (multi-bot channels) */}
          {!isMobile && participantsPanelOpen && channelId && (
            <ParticipantsPanel
              channelId={channelId}
              primaryBotId={channel?.bot_id ?? ""}
              primaryBotName={bot?.name}
              onClose={() => setParticipantsPanelOpen(false)}
            />
          )}
        </div>
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
            router.push("/admin/secret-values" as any);
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

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, backgroundColor: t.surface, overflow: "hidden" }}>
      {outerChildren}
    </div>
  );
}
