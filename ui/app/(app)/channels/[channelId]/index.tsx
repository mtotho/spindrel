import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, FlatList, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { Shield } from "lucide-react";
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
import { useChannel } from "@/src/api/hooks/useChannels";
import { useBot } from "@/src/api/hooks/useBots";
import { useSystemStatus } from "@/src/api/hooks/useSystemStatus";
import { useEnableEditor } from "@/src/api/hooks/useWorkspaces";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { SecretWarningDialog } from "@/src/components/chat/SecretWarningDialog";
import { ActiveWorkflowStrip } from "./ActiveWorkflowStrip";
import { ActiveBadgeBar } from "./ActiveBadgeBar";
import { ErrorBanner, SecretWarningBanner } from "./ChatBanners";
import { TriggerCard, SUPPORTED_TRIGGERS } from "@/src/components/chat/TriggerCard";
import { shouldGroup, formatDateSeparator, isDifferentDay } from "./chatUtils";
import { ChatMessageArea, DateSeparator } from "./ChatMessageArea";
import { ChannelHeader } from "./ChannelHeader";
import { useChannelChat } from "./useChannelChat";
import type { Message } from "@/src/types/api";
import type { NativeSyntheticEvent, NativeScrollEvent } from "react-native";

export default function ChatScreen() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const goBack = useGoBack("/");
  const flatListRef = useRef<FlatList>(null);
  const router = useRouter();

  const { data: channel } = useChannel(channelId);
  const { data: bot } = useBot(channel?.bot_id);
  const { data: systemStatus } = useSystemStatus();
  const isPaused = systemStatus?.paused ?? false;
  const columns = useResponsiveColumns();
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const showHamburger = columns === "single" || sidebarCollapsed;
  const t = useThemeTokens();
  const safeInsets = useSafeAreaInsets();

  const markRead = useChannelReadStore((s) => s.markRead);

  // Mark channel as read on mount / channel switch
  useEffect(() => {
    if (channelId) markRead(channelId);
  }, [channelId]);

  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const {
    chatState,
    invertedData,
    isLoading,
    isFetchingNextPage,
    handleSend,
    handleSendAudio,
    handleCancel,
    handleRetry,
    handleSlashCommand,
    handleLoadMore,
    handleListLayout,
    handleContentSizeChange,
    turnModelOverride,
    turnProviderIdOverride,
    handleModelOverrideChange,
    secretWarning,
    setSecretWarning,
    doSend,
    setError,
  } = useChannelChat({ channelId, channel, activeFile });

  const handleScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const y = e.nativeEvent.contentOffset.y;
    setShowScrollBtn(y > 300);
  }, []);

  const scrollToBottom = useCallback(() => {
    flatListRef.current?.scrollToOffset({ offset: 0, animated: true });
  }, []);

  // In inverted list: index 0 = newest, index+1 = chronologically previous (older).
  // Show date separator when the current message starts a new day vs the older message above it.
  const renderMessage = useCallback(
    ({ item, index }: { item: Message; index: number }) => {
      const prevMsg = invertedData[index + 1];
      const grouped = shouldGroup(item, prevMsg);
      // Show date separator above this message if it's the oldest loaded or on a different day than the one above
      const showDateSep = index === invertedData.length - 1 || (prevMsg && isDifferentDay(item.created_at, prevMsg.created_at));
      // Render trigger card for automated user messages
      const meta = (item.metadata ?? {}) as Record<string, any>;
      if (item.role === "user" && meta.trigger && SUPPORTED_TRIGGERS.has(meta.trigger)) {
        return (
          <>
            <TriggerCard message={item} botName={bot?.name} />
            {showDateSep && <DateSeparator label={formatDateSeparator(item.created_at)} />}
          </>
        );
      }
      return (
        <>
          <MessageBubble message={item} botName={bot?.name} isGrouped={showDateSep ? false : grouped} />
          {showDateSep && <DateSeparator label={formatDateSeparator(item.created_at)} />}
        </>
      );
    },
    [invertedData, bot?.name]
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

  const showExplorer = workspaceEnabled && !!workspaceId && explorerOpen;
  const showFileViewer = activeFile !== null;
  const isMobile = columns === "single";

  /** Gate navigation away from a dirty file with a confirm prompt */
  const confirmIfDirty = useCallback((): boolean => {
    if (!fileDirtyRef.current) return true;
    return confirm("You have unsaved changes. Discard them?");
  }, []);

  const handleDirtyChange = useCallback((dirty: boolean) => {
    fileDirtyRef.current = dirty;
  }, []);

  const handleSelectFile = useCallback((path: string) => {
    if (path === activeFile) return;
    if (!confirmIfDirty()) return;
    setActiveFile(path);
  }, [activeFile, confirmIfDirty]);

  const handleCloseFile = useCallback(() => {
    if (!confirmIfDirty()) return;
    setActiveFile(null);
  }, [confirmIfDirty]);

  const handleCloseExplorer = useCallback(() => {
    if (!confirmIfDirty()) return;
    setExplorerOpen(false);
    setActiveFile(null);
  }, [setExplorerOpen, confirmIfDirty]);

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
    if (!workspaceId || !channelId || Platform.OS !== "web") return;
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
    isStreaming: chatState.isStreaming || chatState.isProcessing,
    onCancel: handleCancel,
    modelOverride: turnModelOverride,
    modelProviderIdOverride: turnProviderIdOverride,
    onModelOverrideChange: handleModelOverrideChange,
    defaultModel: channel?.model_override || bot?.model,
    currentBotId: channel?.bot_id,
    channelId,
    onSlashCommand: handleSlashCommand,
  };

  // ---- Shared message area props ----
  const messageAreaProps = {
    flatListRef,
    invertedData,
    renderMessage,
    chatState,
    bot,
    isLoading,
    isFetchingNextPage,
    showScrollBtn,
    scrollToBottom,
    handleScroll,
    handleListLayout,
    handleContentSizeChange,
    handleLoadMore,
    isProcessing: chatState.isProcessing,
    t,
  };

  return (
    <View
      className={`flex-1 bg-surface ${Platform.OS === "web" ? "safe-area-pad" : ""}`}
      style={Platform.OS !== "web" ? { paddingTop: safeInsets.top, paddingBottom: safeInsets.bottom } : undefined}
    >
      {/* Header */}
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
      />

      {/* What's active badge bar */}
      {channelId && <ActiveBadgeBar channelId={channelId} compact={isMobile} />}

      {/* Protected channel warning */}
      {channel?.client_id === "orchestrator:home" && (
        <View
          className="flex-row items-center gap-2 px-4 py-1.5 border-b border-amber-500/20"
          style={{ backgroundColor: "rgba(245,158,11,0.08)" }}
        >
          <Shield size={13} color="#d97706" />
          <Text style={{ fontSize: 12, color: "#d97706" }}>
            System admin channel — this bot has unrestricted tool access and can delegate to all bots.
          </Text>
        </View>
      )}

      {/* Content area -- explorer + chat/file viewer */}
      {isMobile ? (
        /* ---- Mobile: full-screen modes ---- */
        showExplorer && !showFileViewer ? (
          <ChannelFileExplorer
            channelId={channelId!}
            activeFile={activeFile}
            onSelectFile={handleSelectFile}
            onClose={handleCloseExplorer}
            fullWidth
          />
        ) : showFileViewer ? (
          <ChannelFileViewer
            channelId={channelId!}
            filePath={activeFile!}
            onBack={handleMobileBack}
            onDirtyChange={handleDirtyChange}
          />
        ) : (
          <>
            <ChatMessageArea {...messageAreaProps} />
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
            <MessageInput {...messageInputProps} />
          </>
        )
      ) : (
        /* ---- Desktop/tablet: side-by-side layout ---- */
        <View style={{ flex: 1, flexDirection: "row", overflow: "hidden" }}>
          {/* Explorer panel + resize handle */}
          {showExplorer && channelId && (
            <>
              <ChannelFileExplorer
                channelId={channelId}
                activeFile={activeFile}
                onSelectFile={handleSelectFile}
                onClose={handleCloseExplorer}
                width={explorerWidth}
              />
              {Platform.OS === "web" && (
                <ResizeHandle
                  direction="horizontal"
                  onResize={(delta) => setExplorerWidth(explorerWidth + delta)}
                />
              )}
            </>
          )}

          {/* Chat column -- messages + input stacked vertically */}
          {(!showFileViewer || splitMode) && (
            <View style={{ flex: 1, minWidth: 0 }}>
              <ChatMessageArea {...messageAreaProps} />
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
              <MessageInput {...messageInputProps} />
            </View>
          )}

          {/* File viewer -- visible when a file is selected */}
          {showFileViewer && channelId && (
            <View style={{
              flex: 1,
              minWidth: 0,
              borderLeftWidth: splitMode ? 1 : 0,
              borderLeftColor: t.surfaceBorder,
            }}>
              <ChannelFileViewer
                channelId={channelId}
                filePath={activeFile!}
                onBack={handleCloseFile}
                splitMode={splitMode}
                onToggleSplit={toggleSplit}
                onDirtyChange={handleDirtyChange}
              />
            </View>
          )}
        </View>
      )}
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
    </View>
  );
}
