import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable, Platform } from "react-native";
import { useLocalSearchParams, Link } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Settings, Menu, ArrowLeft, Hash } from "lucide-react";
import { MessageBubble } from "@/src/components/chat/MessageBubble";
import { MessageInput, type PendingFile } from "@/src/components/chat/MessageInput";
import { StreamingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { useChatStream } from "@/src/api/hooks/useChat";
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
  const dt = new Date(current.created_at).getTime() - new Date(prev.created_at).getTime();
  return Math.abs(dt) < 5 * 60 * 1000; // 5 minutes
}

export default function ChatScreen() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const goBack = useGoBack("/");
  const flatListRef = useRef<FlatList>(null);

  const { data: channel } = useChannel(channelId);
  const { data: bot } = useBot(channel?.bot_id);
  const { data: systemStatus } = useSystemStatus();
  const isPaused = systemStatus?.paused ?? false;
  const columns = useResponsiveColumns();
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const showHamburger = columns === "single" || sidebarCollapsed;

  const [turnModelOverride, setTurnModelOverride] = useState<string | undefined>();

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
      const allMessages = [...pages.pages].reverse().flatMap((p) => p.messages);
      setMessages(channelId, allMessages);
    }
  }, [channelId, pages]);

  const chatStream = useChatStream({
    onEvent: (event) => {
      if (channelId) handleSSEEvent(channelId, event);
    },
    onError: (error) => {
      if (channelId) setError(channelId, error.message);
    },
    onComplete: () => {
      if (channelId) finishStreaming(channelId);
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

  // For inverted FlatList, data must be newest-first
  const invertedData = [...chatState.messages].reverse();

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const openMobileSidebar = useUIStore((s) => s.openMobileSidebar);

  // Build a lookup for grouping: for each message index in invertedData,
  // is it grouped with the message below it (which is the chronological next)?
  // Note: inverted means index 0 = newest. "previous" in chrono = index + 1.
  const renderMessage = useCallback(
    ({ item, index }: { item: Message; index: number }) => {
      // In inverted list: index+1 is the chronologically previous message
      const prevMsg = invertedData[index + 1];
      const grouped = shouldGroup(item, prevMsg);
      return <MessageBubble message={item} botName={bot?.name} isGrouped={grouped} />;
    },
    [invertedData, bot?.name]
  );

  const displayName = (channel as any)?.display_name || channel?.name || channel?.client_id || "Chat";

  return (
    <View className="flex-1 bg-surface" style={{ overflow: "hidden" }}>
      {/* Header */}
      <View
        className="flex-row items-center gap-3 px-4 border-b border-surface-border"
        style={{
          flexShrink: 0,
          zIndex: 10,
          minHeight: 52,
          backgroundColor: "#111111",
        }}
      >
        {columns === "single" && (
          <Pressable
            onPress={goBack}
            className="items-center justify-center rounded-md hover:bg-surface-overlay"
            style={{ width: 36, height: 36 }}
          >
            <ArrowLeft size={20} color="#9ca3af" />
          </Pressable>
        )}
        {showHamburger && columns !== "single" && (
          <Pressable
            onPress={toggleSidebar}
            className="items-center justify-center rounded-md hover:bg-surface-overlay"
            style={{ width: 36, height: 36 }}
          >
            <Menu size={20} color="#9ca3af" />
          </Pressable>
        )}
        <Hash size={18} color="#666666" style={{ marginLeft: 2 }} />
        <View className="flex-1 min-w-0 py-2">
          <Text style={{ fontSize: 16, fontWeight: "700", color: "#e5e5e5" }} numberOfLines={1}>
            {displayName}
          </Text>
          {bot && (
            <View className="flex-row items-center gap-1.5 mt-0.5">
              <Link href={`/admin/bots/${bot.id}` as any}>
                <Text style={{ fontSize: 12, color: "#999" }}>{bot.name}</Text>
              </Link>
              <Text style={{ fontSize: 11, color: "#555" }}>
                {channel?.model_override || bot?.model}
              </Text>
            </View>
          )}
        </View>
        {channelId && (
          <Link href={`/channels/${channelId}/settings` as any} asChild>
            <Pressable
              className="items-center justify-center rounded-md hover:bg-surface-overlay"
              style={{ width: 36, height: 36 }}
            >
              <Settings size={18} color="#666666" />
            </Pressable>
          </Link>
        )}
      </View>

      {/* Messages */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#666666" />
        </View>
      ) : (
        <FlatList
          ref={flatListRef}
          inverted
          style={{ flex: 1 }}
          data={invertedData}
          keyExtractor={(item) => item.id}
          renderItem={renderMessage}
          contentContainerStyle={{ paddingTop: 8, paddingBottom: 8 }}
          scrollEventThrottle={100}
          onEndReached={handleLoadMore}
          onEndReachedThreshold={0.5}
          ListHeaderComponent={
            chatState.isStreaming ? (
              <StreamingIndicator
                content={chatState.streamingContent}
                toolCalls={chatState.toolCalls}
                botName={bot?.name}
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
            <View className="flex-1 items-center justify-center py-20">
              <Text className="text-text-dim text-sm">
                Send a message to start the conversation
              </Text>
            </View>
          }
        />
      )}

      {/* Error */}
      {chatState.error && (
        <View className="px-4 py-2 bg-red-500/10 border-t border-red-500/20">
          <Text className="text-red-400 text-sm">{chatState.error}</Text>
        </View>
      )}

      {/* Input */}
      <MessageInput
        onSend={handleSend}
        disabled={chatState.isStreaming || isPaused}
        modelOverride={turnModelOverride}
        onModelOverrideChange={setTurnModelOverride}
        defaultModel={channel?.model_override || bot?.model}
      />
    </View>
  );
}
