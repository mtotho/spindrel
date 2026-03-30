import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable, Platform, type NativeSyntheticEvent, type NativeScrollEvent } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, Link } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Settings, Menu, ArrowLeft, Hash, ChevronDown } from "lucide-react";
import { MessageBubble, extractDisplayText } from "@/src/components/chat/MessageBubble";
import { MessageInput, type PendingFile } from "@/src/components/chat/MessageInput";
import { StreamingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { useChannelReadStore } from "@/src/stores/channelRead";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChatStream, useCancelChat } from "@/src/api/hooks/useChat";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useBot } from "@/src/api/hooks/useBots";
import { useSystemStatus } from "@/src/api/hooks/useSystemStatus";
import { apiFetch } from "@/src/api/client";
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

  const markRead = useChannelReadStore((s) => s.markRead);

  // Mark channel as read on mount / channel switch
  useEffect(() => {
    if (channelId) markRead(channelId);
  }, [channelId]);

  const [turnModelOverride, setTurnModelOverride] = useState<string | undefined>();
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const chatState = useChatStore((s) => s.getChannel(channelId!));
  const setMessages = useChatStore((s) => s.setMessages);
  const addMessage = useChatStore((s) => s.addMessage);
  const startStreaming = useChatStore((s) => s.startStreaming);
  const handleSSEEvent = useChatStore((s) => s.handleSSEEvent);
  const finishStreaming = useChatStore((s) => s.finishStreaming);
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

  useEffect(() => {
    if (channelId && pages) {
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
  }, [channelId, pages]);

  const cancelChat = useCancelChat();

  const handleCancel = useCallback(() => {
    if (!channel) return;
    cancelChat.mutate({
      client_id: channel.client_id ?? "",
      bot_id: channel.bot_id,
    });
  }, [channel]);

  const chatStream = useChatStream({
    onEvent: (event) => {
      if (channelId) handleSSEEvent(channelId, event);
    },
    onError: (error) => {
      // Finish streaming first so any partial content is preserved in messages
      if (channelId) finishStreaming(channelId);
      if (channelId) setError(channelId, error.message);
      // SSE dropped but server likely still processed the message.
      // Refetch messages after a short delay so the response appears.
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
      }, 2000);
    },
    onComplete: () => {
      if (channelId) finishStreaming(channelId);
      // Refetch messages to get real DB records (with attachments, full metadata, etc.)
      // persist_turn runs before the SSE connection closes, so data is ready.
      queryClient.invalidateQueries({ queryKey: ["session-messages"] });
    },
  });

  const handleSend = useCallback(
    (text: string, files?: PendingFile[]) => {
      if (!channelId || !channel) return;

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

      chatStream.mutate({
        message: text,
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
        ...(turnModelOverride ? { model_override: turnModelOverride } : {}),
        ...(attachments?.length ? { attachments } : {}),
        ...(file_metadata?.length ? { file_metadata } : {}),
      });

      setTurnModelOverride(undefined);
    },
    [channelId, channel, turnModelOverride]
  );

  // Reverse for inverted FlatList (newest-first)
  const invertedData = [...chatState.messages].reverse();

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
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
      return (
        <>
          <MessageBubble message={item} botName={bot?.name} isGrouped={showDateSep ? false : grouped} />
          {showDateSep && <DateSeparator label={formatDateSeparator(item.created_at)} />}
        </>
      );
    },
    [invertedData, bot?.name]
  );

  const displayName = (channel as any)?.display_name || channel?.name || channel?.client_id || "Chat";

  return (
    <SafeAreaView className="flex-1 bg-surface" edges={["top"]} style={{ overflow: "hidden" }}>
      {/* Header */}
      <View
        className="flex-row items-center gap-3 px-4 border-b border-surface-border bg-surface"
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
            <View className="flex-row items-center gap-1.5 mt-0.5">
              <Link href={`/admin/bots/${bot.id}` as any}>
                <Text style={{ fontSize: 12, color: t.textMuted }}>{bot.name}</Text>
              </Link>
              <Text style={{ fontSize: 11, color: t.textDim }}>
                {channel?.model_override || bot?.model}
              </Text>
            </View>
          )}
        </View>
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

      {/* Messages */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color={t.textDim} />
        </View>
      ) : (
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
            onEndReached={handleLoadMore}
            onEndReachedThreshold={0.5}
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
              ) : null
            }
            ListFooterComponent={
              isFetchingNextPage ? (
                <View className="items-center py-3">
                  <ActivityIndicator size="small" color="#666666" />
                </View>
              ) : hasNextPage ? (
                <Pressable onPress={handleLoadMore} className="items-center py-3">
                  <Text className="text-text-muted text-xs">Load older messages</Text>
                </Pressable>
              ) : null
            }
            ListEmptyComponent={
              <View style={{ flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 80, transform: [{ scaleY: -1 }] }}>
                <Text style={{ color: t.textDim, fontSize: 14 }}>
                  Send a message to start the conversation
                </Text>
              </View>
            }
          />
          {/* Scroll-to-bottom FAB */}
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
      )}

      {/* Error (tap to dismiss) */}
      {chatState.error && (
        <Pressable
          onPress={() => channelId && setError(channelId, "")}
          className="px-4 py-2 bg-red-500/10 border-t border-red-500/20"
        >
          <Text className="text-red-400 text-sm">{chatState.error}</Text>
        </Pressable>
      )}

      {/* Input */}
      <MessageInput
        onSend={handleSend}
        disabled={isPaused}
        isStreaming={chatState.isStreaming}
        onCancel={handleCancel}
        modelOverride={turnModelOverride}
        onModelOverrideChange={setTurnModelOverride}
        defaultModel={channel?.model_override || bot?.model}
      />
    </SafeAreaView>
  );
}
