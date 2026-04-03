import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable, Platform, type NativeSyntheticEvent, type NativeScrollEvent } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, Link, useRouter } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Settings, Menu, ArrowLeft, Hash, ChevronDown, FolderOpen, Code, PanelLeft, Shield } from "lucide-react";
import { ChannelFileExplorer } from "./ChannelFileExplorer";
import { ChannelFileViewer } from "./ChannelFileViewer";
import { ResizeHandle } from "@/src/components/workspace/ResizeHandle";
import { MessageBubble, extractDisplayText } from "@/src/components/chat/MessageBubble";
import { MessageInput, type PendingFile } from "@/src/components/chat/MessageInput";
import { StreamingIndicator, ProcessingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { useChannelReadStore } from "@/src/stores/channelRead";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChatStream, useCancelChat, useSessionStatus } from "@/src/api/hooks/useChat";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useBot } from "@/src/api/hooks/useBots";
import { useSystemStatus } from "@/src/api/hooks/useSystemStatus";
import { apiFetch } from "@/src/api/client";
import { useEnableEditor } from "@/src/api/hooks/useWorkspaces";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { useSecretCheck, type SecretCheckResult } from "@/src/api/hooks/useSecretCheck";
import { SecretWarningDialog } from "@/src/components/chat/SecretWarningDialog";
import { ActiveWorkflowStrip } from "./ActiveWorkflowStrip";
import { ActiveBadgeBar } from "./ActiveBadgeBar";
import { ErrorBanner, SecretWarningBanner } from "./ChatBanners";
import { TriggerCard, SUPPORTED_TRIGGERS } from "@/src/components/chat/TriggerCard";
import type { Message, ChatAttachment, ChatFileMetadata, ChatRequest } from "@/src/types/api";

interface MessagePage {
  messages: Message[];
  has_more: boolean;
}

const PAGE_SIZE = 50;

/** Should this message be grouped (compact, no avatar) with the previous? */
function shouldGroup(current: Message, prev: Message | undefined): boolean {
  if (!prev) return false;
  if (current.role !== prev.role) return false;
  // Don't group bot response with preceding trigger card
  if (prev.role === "user" && (prev.metadata as any)?.trigger) return false;
  // Don't group across different senders (e.g. two different bots)
  const curSender = current.metadata?.sender_id ?? current.role;
  const prevSender = prev.metadata?.sender_id ?? prev.role;
  if (curSender !== prevSender) return false;
  const dt = new Date(current.created_at).getTime() - new Date(prev.created_at).getTime();
  return Math.abs(dt) < 5 * 60 * 1000; // 5 minutes
}

/** Format a date for the day separator: "Today", "Yesterday", or "Wed, Mar 26" */
function formatDateSeparator(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = today.getTime() - msgDay.getTime();
  if (diff === 0) return "Today";
  if (diff === 86400000) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

/** Are two timestamps on different calendar days (local time)? */
function isDifferentDay(a: string, b: string): boolean {
  const da = new Date(a);
  const db = new Date(b);
  return da.getFullYear() !== db.getFullYear() || da.getMonth() !== db.getMonth() || da.getDate() !== db.getDate();
}


function DateSeparator({ label }: { label: string }) {
  const t = useThemeTokens();
  if (Platform.OS === "web") {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "12px 20px",
          userSelect: "none",
        }}
      >
        <div style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: t.textDim, whiteSpace: "nowrap" }}>
          {label}
        </span>
        <div style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder }} />
      </div>
    );
  }
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 16, paddingHorizontal: 20, paddingVertical: 12 }}>
      <View style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder }} />
      <Text style={{ fontSize: 12, fontWeight: "600", color: t.textDim }}>{label}</Text>
      <View style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder }} />
    </View>
  );
}

/** Extracted chat message list + scroll-to-bottom FAB so it can be reused in both mobile and desktop layouts */
function ChatMessageArea({
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
  isProcessing,
  t,
}: {
  flatListRef: React.RefObject<FlatList | null>;
  invertedData: Message[];
  renderMessage: (info: { item: Message; index: number }) => React.JSX.Element;
  chatState: { isStreaming: boolean; streamingContent: string; toolCalls: any[]; thinkingContent: string };
  bot: { name?: string } | undefined;
  isLoading: boolean;
  isFetchingNextPage: boolean;
  showScrollBtn: boolean;
  scrollToBottom: () => void;
  handleScroll: (e: NativeSyntheticEvent<NativeScrollEvent>) => void;
  handleListLayout: (e: any) => void;
  handleContentSizeChange: (w: number, h: number) => void;
  handleLoadMore: () => void;
  isProcessing?: boolean;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <View style={{ flex: 1, position: "relative" }}>
      <FlatList
        ref={flatListRef}
        inverted
        style={{ flex: 1 }}
        data={invertedData}
        keyExtractor={(item) => item.id}
        renderItem={renderMessage}
        contentContainerStyle={{ paddingTop: 8, paddingBottom: 8 }}
        scrollEventThrottle={100}
        onScroll={handleScroll}
        onLayout={handleListLayout}
        onContentSizeChange={handleContentSizeChange}
        onEndReached={handleLoadMore}
        onEndReachedThreshold={1.5}
        initialNumToRender={20}
        maxToRenderPerBatch={15}
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
        automaticallyAdjustContentInsets={false}
        contentInsetAdjustmentBehavior="never"
        ListHeaderComponent={
          chatState.isStreaming ? (
            <StreamingIndicator
              content={chatState.streamingContent}
              toolCalls={chatState.toolCalls}
              botName={bot?.name}
              thinkingContent={chatState.thinkingContent}
            />
          ) : isProcessing ? (
            <ProcessingIndicator botName={bot?.name} />
          ) : null
        }
        ListFooterComponent={
          isFetchingNextPage ? (
            <View className="items-center py-3">
              <ActivityIndicator size="small" color="#666666" />
            </View>
          ) : null
        }
        ListEmptyComponent={
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 80, transform: [{ scaleY: -1 }] }}>
            {isLoading ? (
              <ActivityIndicator color={t.textDim} />
            ) : (
              <Text style={{ color: t.textDim, fontSize: 14 }}>
                Send a message to start the conversation
              </Text>
            )}
          </View>
        }
      />
      {showScrollBtn && (
        <Pressable
          onPress={scrollToBottom}
          style={{
            position: "absolute",
            bottom: 16,
            right: 24,
            width: 40,
            height: 40,
            borderRadius: 20,
            backgroundColor: t.surfaceRaised,
            borderWidth: 1,
            borderColor: t.surfaceBorder,
            alignItems: "center",
            justifyContent: "center",
            ...Platform.select({
              web: { boxShadow: "0 2px 8px rgba(0,0,0,0.3)", cursor: "pointer" } as any,
              default: { elevation: 4 },
            }),
          }}
        >
          <ChevronDown size={20} color={t.textMuted} />
        </Pressable>
      )}
    </View>
  );
}

export default function ChatScreen() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const goBack = useGoBack("/");
  const flatListRef = useRef<FlatList>(null);

  const queryClient = useQueryClient();
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

  const [turnModelOverride, setTurnModelOverride] = useState<string | undefined>();
  const [turnProviderIdOverride, setTurnProviderIdOverride] = useState<string | null | undefined>();
  const handleModelOverrideChange = useCallback((m: string | undefined, providerId?: string | null) => {
    setTurnModelOverride(m);
    setTurnProviderIdOverride(m ? providerId : undefined);
  }, []);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [secretWarning, setSecretWarning] = useState<{
    result: SecretCheckResult;
    text: string;
    files?: PendingFile[];
  } | null>(null);
  const secretCheck = useSecretCheck();
  const router = useRouter();

  const chatState = useChatStore((s) => s.getChannel(channelId!));
  const setMessages = useChatStore((s) => s.setMessages);
  const addMessage = useChatStore((s) => s.addMessage);
  const startStreaming = useChatStore((s) => s.startStreaming);
  const handleSSEEvent = useChatStore((s) => s.handleSSEEvent);
  const finishStreaming = useChatStore((s) => s.finishStreaming);
  const clearProcessing = useChatStore((s) => s.clearProcessing);
  const setError = useChatStore((s) => s.setError);

  const {
    data: pages,
    isLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["session-messages", channel?.active_session_id],
    queryFn: async ({ pageParam }) => {
      if (!channel?.active_session_id) return { messages: [], has_more: false };
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (pageParam) params.set("before", pageParam);
      return apiFetch<MessagePage>(
        `/sessions/${channel.active_session_id}/messages?${params}`
      );
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more || lastPage.messages.length === 0) return undefined;
      return lastPage.messages[0].id;
    },
    enabled: !!channel?.active_session_id,
  });

  // Sync DB messages into the chat store when new page data arrives.
  // IMPORTANT: Only depend on [channelId, pages] — NOT streaming/processing state.
  // Streaming state is checked as a guard inside, but must not be a trigger.
  // If it were a dep, finishing a stream would re-run this effect with stale pages
  // (the invalidateQueries refetch hasn't completed yet), overwriting the synthetic
  // message that finishStreaming() just materialized.
  useEffect(() => {
    if (channelId && pages && !chatState.isStreaming && !chatState.isProcessing) {
      const allMessages = [...pages.pages].reverse().flatMap((p) => p.messages)
        .filter((m) => {
          if (m.role !== "user" && m.role !== "assistant") return false;
          const meta = (m as any).metadata ?? {};
          // Hide passive dispatch echoes (ambient messages bot didn't respond to)
          // But show delegated child responses (they arrive as passive with delegated_by attribution)
          if (meta.passive && !meta.delegated_by) return false;
          // Hide heartbeat trigger prompts (injected user messages), but keep bot responses
          if (m.role === "user" && meta.is_heartbeat) return false;
          // Hide assistant messages with no displayable content (tool-call-only messages)
          // BUT keep messages that have attachments so download links are visible
          if (m.role === "assistant" && !extractDisplayText(m.content)
              && (!m.attachments || m.attachments.length === 0)) return false;
          return true;
        });
      setMessages(channelId, allMessages);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId, pages]);

  // Poll session status while background processing is active
  const { data: sessionStatus } = useSessionStatus(channelId, chatState.isProcessing);

  // When background processing completes, clear state and refetch messages
  useEffect(() => {
    if (
      chatState.isProcessing &&
      sessionStatus &&
      !sessionStatus.processing &&
      sessionStatus.pending_tasks === 0
    ) {
      if (channelId) clearProcessing(channelId);
      queryClient.invalidateQueries({ queryKey: ["session-messages"] });
    }
  }, [chatState.isProcessing, sessionStatus, channelId, clearProcessing, queryClient]);

  // Per-channel pending buffers so concurrent streams don't mix deltas
  const pendingTextRef = useRef<Record<string, string>>({});
  const pendingThinkRef = useRef<Record<string, string>>({});
  const rafRef = useRef<Record<string, number>>({});
  const lastRequestRef = useRef<Record<string, ChatRequest>>({});

  /** Flush buffered text/thinking deltas for a specific channel */
  const flushChannel = useCallback((chId: string) => {
    rafRef.current[chId] = 0;
    const text = pendingTextRef.current[chId];
    const think = pendingThinkRef.current[chId];
    if (text) {
      handleSSEEvent(chId, { event: "text_delta", data: { delta: text } });
      pendingTextRef.current[chId] = "";
    }
    if (think) {
      handleSSEEvent(chId, { event: "thinking", data: { delta: think } });
      pendingThinkRef.current[chId] = "";
    }
  }, [handleSSEEvent]);

  const cancelChat = useCancelChat();

  const handleCancel = useCallback(() => {
    if (!channel || !channelId) return;
    // Send server-side cancel (sets flag + cancels queued tasks)
    cancelChat.mutate({
      client_id: channel.client_id ?? "",
      bot_id: channel.bot_id,
    });
    // Abort local SSE for THIS channel immediately so UI is responsive
    chatStream.abort(channelId);
    // Flush pending RAF deltas so partial content isn't lost
    if (pendingTextRef.current[channelId] || pendingThinkRef.current[channelId]) {
      cancelAnimationFrame(rafRef.current[channelId] || 0);
      flushChannel(channelId);
    }
    // Materialize partial streaming content as a message, then clear streaming state
    finishStreaming(channelId);
    // Also clear any background processing state
    clearProcessing(channelId);
    // Refetch messages to replace synthetic messages with clean DB data
    queryClient.invalidateQueries({ queryKey: ["session-messages"] });
  }, [channel, channelId, flushChannel, finishStreaming, clearProcessing, queryClient]);

  const chatStream = useChatStream({
    onEvent: (event) => {
      if (!channelId) return;
      // Batch text and thinking deltas — flush at ~60fps instead of per-token
      if (event.event === "text_delta") {
        pendingTextRef.current[channelId] = (pendingTextRef.current[channelId] ?? "") + ((event.data as any).delta ?? "");
        if (!rafRef.current[channelId]) {
          const chId = channelId;
          rafRef.current[chId] = requestAnimationFrame(() => flushChannel(chId));
        }
        return;
      }
      if (event.event === "thinking") {
        pendingThinkRef.current[channelId] = (pendingThinkRef.current[channelId] ?? "") + ((event.data as any).delta ?? "");
        if (!rafRef.current[channelId]) {
          const chId = channelId;
          rafRef.current[chId] = requestAnimationFrame(() => flushChannel(chId));
        }
        return;
      }
      // Flush pending text before processing other events (tool_start, response, etc.)
      if (pendingTextRef.current[channelId] || pendingThinkRef.current[channelId]) {
        cancelAnimationFrame(rafRef.current[channelId] || 0);
        flushChannel(channelId);
      }
      handleSSEEvent(channelId, event);
    },
    onError: (error) => {
      if (channelId) {
        // Flush any pending text for this channel
        if (pendingTextRef.current[channelId] || pendingThinkRef.current[channelId]) {
          cancelAnimationFrame(rafRef.current[channelId] || 0);
          flushChannel(channelId);
        }
        // Finish streaming first so any partial content is preserved in messages
        finishStreaming(channelId);
        setError(channelId, error.message);
      }
      // SSE dropped but server likely still processed the message.
      // Refetch messages after a short delay so the response appears.
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
      }, 2000);
    },
    onComplete: () => {
      if (channelId) {
        // Flush any pending text for this channel
        if (pendingTextRef.current[channelId] || pendingThinkRef.current[channelId]) {
          cancelAnimationFrame(rafRef.current[channelId] || 0);
          flushChannel(channelId);
        }
        finishStreaming(channelId);
      }
      // Refetch messages to get real DB records (with attachments, full metadata, etc.)
      // persist_turn runs before the SSE connection closes, so data is ready.
      queryClient.invalidateQueries({ queryKey: ["session-messages"] });
    },
  });

  const handleRetry = useCallback(() => {
    const req = channelId ? lastRequestRef.current[channelId] : undefined;
    if (!channelId || !req) return;
    setError(channelId, "");
    startStreaming(channelId);
    chatStream.mutate(req);
  }, [channelId, setError, startStreaming]);

  const doSend = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;

      // If viewing a file in non-split mode, auto-enable split so the user sees the response
      if (activeFile && !useUIStore.getState().fileExplorerSplit) {
        useUIStore.getState().toggleFileExplorerSplit();
      }

      addMessage(channelId, {
        id: `msg-${Date.now()}`,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      });

      startStreaming(channelId);

      let attachments: ChatAttachment[] | undefined;
      let file_metadata: ChatFileMetadata[] | undefined;
      if (files && files.length > 0) {
        attachments = [];
        file_metadata = [];
        for (const pf of files) {
          if (pf.file.type.startsWith("image/")) {
            attachments.push({
              type: "image",
              content: pf.base64,
              mime_type: pf.file.type,
              name: pf.file.name,
            });
          }
          file_metadata.push({
            filename: pf.file.name,
            mime_type: pf.file.type,
            size_bytes: pf.file.size,
            file_data: pf.base64,
          });
        }
      }

      const request: ChatRequest = {
        message: text,
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
        ...(turnModelOverride ? { model_override: turnModelOverride } : {}),
        ...(turnProviderIdOverride != null ? { model_provider_id_override: turnProviderIdOverride } : {}),
        ...(attachments?.length ? { attachments } : {}),
        ...(file_metadata?.length ? { file_metadata } : {}),
      };
      lastRequestRef.current[channelId] = request;
      chatStream.mutate(request);

      setTurnModelOverride(undefined);
      setTurnProviderIdOverride(undefined);
    },
    [channelId, channel, activeFile, turnModelOverride, turnProviderIdOverride]
  );

  const handleSend = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;

      // Pre-flight secret check — fail-open on error
      secretCheck.mutate(text, {
        onSuccess: (result) => {
          if (result.has_secrets) {
            setSecretWarning({ result, text, files });
          } else {
            doSend(text, files);
          }
        },
        onError: () => {
          // Fail open — send anyway if check fails
          doSend(text, files);
        },
      });
    },
    [channelId, channel, doSend]
  );

  const handleSendAudio = useCallback(
    (audioBase64: string, audioFormat: string, message?: string) => {
      if (!channelId || !channel) return;

      if (activeFile && !useUIStore.getState().fileExplorerSplit) {
        useUIStore.getState().toggleFileExplorerSplit();
      }

      addMessage(channelId, {
        id: `msg-${Date.now()}`,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: message || "[voice message]",
        created_at: new Date().toISOString(),
      });

      startStreaming(channelId);

      const request: ChatRequest = {
        message: message || "",
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
        audio_data: audioBase64,
        audio_format: audioFormat,
        ...(turnModelOverride ? { model_override: turnModelOverride } : {}),
        ...(turnProviderIdOverride != null ? { model_provider_id_override: turnProviderIdOverride } : {}),
      };
      lastRequestRef.current[channelId] = request;
      chatStream.mutate(request);

      setTurnModelOverride(undefined);
      setTurnProviderIdOverride(undefined);
    },
    [channelId, channel, activeFile, turnModelOverride, turnProviderIdOverride]
  );

  // Slash command handler
  const handleSlashCommand = useCallback(
    async (id: string) => {
      if (!channelId) return;
      switch (id) {
        case "context":
          router.push(`/channels/${channelId}/settings#context` as any);
          break;
        case "clear":
          try {
            await apiFetch(`/channels/${channelId}/reset`, { method: "POST" });
            setMessages(channelId, []);
            queryClient.invalidateQueries({ queryKey: ["session-messages"] });
            queryClient.invalidateQueries({ queryKey: ["channel", channelId] });
          } catch (err) {
            console.error("Failed to reset session:", err);
          }
          break;
        case "compact":
          try {
            await apiFetch(`/channels/${channelId}/compact`, { method: "POST" });
            queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          } catch (err) {
            console.error("Failed to compact:", err);
          }
          break;
      }
    },
    [channelId, router, setMessages, queryClient],
  );

  // Reverse for inverted FlatList (visual grouping is handled by shouldGroup + isGrouped on MessageBubble)
  const invertedData = useMemo(
    () => [...chatState.messages].reverse(),
    [chatState.messages],
  );

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Auto-load older pages when content doesn't fill the viewport
  const listHeightRef = useRef(0);
  const handleListLayout = useCallback((e: any) => {
    listHeightRef.current = e.nativeEvent.layout.height;
  }, []);
  const handleContentSizeChange = useCallback((_w: number, h: number) => {
    if (h < listHeightRef.current && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

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

  // Workspace header buttons
  const workspaceEnabled = channel?.channel_workspace_enabled;
  const workspaceId = channel?.resolved_workspace_id;
  const enableEditorMutation = useEnableEditor(workspaceId ?? "");
  const expandDir = useFileBrowserStore((s) => s.expandDir);
  const explorerWidth = useFileBrowserStore((s) => s.channelExplorerWidth);
  const setExplorerWidth = useFileBrowserStore((s) => s.setChannelExplorerWidth);

  // File explorer state
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
      // dirty guard is handled inside ChannelFileViewer's onBack
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

  return (
    <View className="flex-1 bg-surface" style={{ paddingTop: safeInsets.top, paddingBottom: safeInsets.bottom }}>
      {/* Header */}
      <View
        className={`flex-row items-center ${isMobile ? "gap-2 px-3" : "gap-3 px-4"} border-b border-surface-border bg-surface`}
        style={{
          flexShrink: 0,
          zIndex: 10,
          minHeight: 52,
        }}
      >
        {columns === "single" && (
          <Pressable
            onPress={goBack}
            className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 44, height: 44 }}
          >
            <ArrowLeft size={20} color={t.textMuted} />
          </Pressable>
        )}
        {showHamburger && columns !== "single" && (
          <Pressable
            onPress={toggleSidebar}
            className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 44, height: 44 }}
          >
            <Menu size={20} color={t.textMuted} />
          </Pressable>
        )}
        <Hash size={18} color={t.textDim} style={{ marginLeft: 2 }} />
        <View className="flex-1 min-w-0 py-2">
          <Text style={{ fontSize: 16, fontWeight: "700", color: t.text }} numberOfLines={1}>
            {displayName}
          </Text>
          {bot && (
            <View className="flex-row items-center gap-1.5 mt-0.5 min-w-0">
              <Link href={`/admin/bots/${bot.id}` as any}>
                <Text style={{ fontSize: 12, color: t.textMuted }} numberOfLines={1}>{bot.name}</Text>
              </Link>
              <Text style={{ fontSize: 11, color: t.textDim, flexShrink: 1 }} numberOfLines={1}>
                {(channel?.model_override || bot?.model || "").split("/").pop()}
              </Text>
            </View>
          )}
        </View>
        {workspaceEnabled && workspaceId && (
          <>
            <Pressable
              onPress={toggleExplorer}
              className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
              style={{
                width: 36,
                height: 36,
                backgroundColor: explorerOpen ? t.surfaceOverlay : "transparent",
                borderRadius: 6,
              }}
              {...(Platform.OS === "web" ? { title: explorerOpen ? "Hide file explorer" : "Show file explorer" } as any : {})}
            >
              <PanelLeft size={16} color={explorerOpen ? t.accent : t.textDim} />
            </Pressable>
            {!isMobile && (
              <Link href={`/admin/workspaces/${workspaceId}/files` as any} asChild>
                <Pressable
                  onPress={handleBrowseWorkspace}
                  className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
                  style={{ width: 36, height: 36 }}
                  {...(Platform.OS === "web" ? { title: "Browse workspace" } as any : {})}
                >
                  <FolderOpen size={16} color={t.textDim} />
                </Pressable>
              </Link>
            )}
            {!isMobile && Platform.OS === "web" && (
              <Pressable
                onPress={handleOpenEditor}
                className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
                style={{ width: 36, height: 36 }}
                {...{ title: "Open in VS Code" } as any}
              >
                <Code size={16} color={t.textDim} />
              </Pressable>
            )}
          </>
        )}
        {channelId && (
          <Link href={`/channels/${channelId}/settings` as any} asChild>
            <Pressable
              className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
              style={{ width: 44, height: 44 }}
            >
              <Settings size={18} color={t.textDim} />
            </Pressable>
          </Link>
        )}
      </View>

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

      {/* Content area — explorer + chat/file viewer */}
      {isMobile ? (
        /* ---- Mobile: full-screen modes ---- */
        showExplorer && !showFileViewer ? (
          /* Mobile explorer full-screen */
          <ChannelFileExplorer
            channelId={channelId!}
            activeFile={activeFile}
            onSelectFile={handleSelectFile}
            onClose={handleCloseExplorer}
            fullWidth
          />
        ) : showFileViewer ? (
          /* Mobile file viewer full-screen */
          <ChannelFileViewer
            channelId={channelId!}
            filePath={activeFile!}
            onBack={handleMobileBack}
            onDirtyChange={handleDirtyChange}
          />
        ) : (
          /* Mobile chat (default) */
          <>
            <ChatMessageArea
              flatListRef={flatListRef}
              invertedData={invertedData}
              renderMessage={renderMessage}
              chatState={chatState}
              bot={bot}
              isLoading={isLoading}
              isFetchingNextPage={isFetchingNextPage}
              showScrollBtn={showScrollBtn}
              scrollToBottom={scrollToBottom}
              handleScroll={handleScroll}
              handleListLayout={handleListLayout}
              handleContentSizeChange={handleContentSizeChange}
              handleLoadMore={handleLoadMore}
              isProcessing={chatState.isProcessing}
              t={t}
            />
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
            <MessageInput
              onSend={handleSend}
              onSendAudio={handleSendAudio}
              disabled={isPaused}
              isStreaming={chatState.isStreaming || chatState.isProcessing}
              onCancel={handleCancel}
              modelOverride={turnModelOverride}
              modelProviderIdOverride={turnProviderIdOverride}
              onModelOverrideChange={handleModelOverrideChange}
              defaultModel={channel?.model_override || bot?.model}
              currentBotId={channel?.bot_id}
              channelId={channelId}
              onSlashCommand={handleSlashCommand}
            />
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

          {/* Chat column — messages + input stacked vertically */}
          {(!showFileViewer || splitMode) && (
            <View style={{ flex: 1, minWidth: 0 }}>
              <ChatMessageArea
                flatListRef={flatListRef}
                invertedData={invertedData}
                renderMessage={renderMessage}
                chatState={chatState}
                bot={bot}
                isLoading={isLoading}
                isFetchingNextPage={isFetchingNextPage}
                showScrollBtn={showScrollBtn}
                scrollToBottom={scrollToBottom}
                handleScroll={handleScroll}
                handleListLayout={handleListLayout}
                handleContentSizeChange={handleContentSizeChange}
                handleLoadMore={handleLoadMore}
                isProcessing={chatState.isProcessing}
                t={t}
              />
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
              <MessageInput
                onSend={handleSend}
                onSendAudio={handleSendAudio}
                disabled={isPaused}
                isStreaming={chatState.isStreaming || chatState.isProcessing}
                onCancel={handleCancel}
                modelOverride={turnModelOverride}
                modelProviderIdOverride={turnProviderIdOverride}
                onModelOverrideChange={handleModelOverrideChange}
                defaultModel={channel?.model_override || bot?.model}
                currentBotId={channel?.bot_id}
                channelId={channelId}
                onSlashCommand={handleSlashCommand}
              />
            </View>
          )}

          {/* File viewer — visible when a file is selected */}
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
