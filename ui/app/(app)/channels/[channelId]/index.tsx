import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable } from "react-native";
import { useLocalSearchParams, Link } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Settings, Menu, ArrowLeft } from "lucide-react";
import { MessageBubble } from "@/src/components/chat/MessageBubble";
import { MessageInput } from "@/src/components/chat/MessageInput";
import { StreamingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { useChatStream } from "@/src/api/hooks/useChat";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useBot } from "@/src/api/hooks/useBots";
import { apiFetch } from "@/src/api/client";
import type { Message } from "@/src/types/api";

interface MessagePage {
  messages: Message[];
  has_more: boolean;
}

const PAGE_SIZE = 50;

export default function ChatScreen() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const goBack = useGoBack("/");
  const flatListRef = useRef<FlatList>(null);

  const { data: channel } = useChannel(channelId);
  const { data: bot } = useBot(channel?.bot_id);
  const columns = useResponsiveColumns();
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  // Show hamburger when sidebar is not visible (mobile or collapsed)
  const showHamburger = columns === "single" || sidebarCollapsed;

  const chatState = useChatStore((s) => s.getChannel(channelId!));
  const setMessages = useChatStore((s) => s.setMessages);
  const addMessage = useChatStore((s) => s.addMessage);
  const startStreaming = useChatStore((s) => s.startStreaming);
  const handleSSEEvent = useChatStore((s) => s.handleSSEEvent);
  const finishStreaming = useChatStore((s) => s.finishStreaming);
  const setError = useChatStore((s) => s.setError);

  // Cursor-based paginated message loading
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

  // Sync fetched pages into the chat store (reversed for inverted FlatList)
  useEffect(() => {
    if (channelId && pages) {
      // Combine oldest pages first, then newer pages → chronological order
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
    (text: string) => {
      if (!channelId || !channel) return;

      addMessage(channelId, {
        id: `msg-${Date.now()}`,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      });

      startStreaming(channelId);

      chatStream.mutate({
        message: text,
        bot_id: channel.bot_id,
        client_id: channel.client_id ?? "",
        channel_id: channelId,
      });
    },
    [channelId, channel]
  );

  // For inverted FlatList, data must be newest-first
  const invertedData = [...chatState.messages].reverse();

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border">
        {columns === "single" && (
          <Pressable onPress={goBack} className="p-1.5 rounded-md hover:bg-surface-overlay">
            <ArrowLeft size={18} color="#9ca3af" />
          </Pressable>
        )}
        {showHamburger && columns !== "single" && (
          <Pressable onPress={toggleSidebar} className="p-1.5 rounded-md hover:bg-surface-overlay">
            <Menu size={18} color="#9ca3af" />
          </Pressable>
        )}
        <View className="flex-1 min-w-0">
          <Text className="text-text font-semibold" numberOfLines={1}>
            {(channel as any)?.display_name || channel?.name || channel?.client_id || "Chat"}
          </Text>
          {bot && (
            <Link href={`/admin/bots/${bot.id}` as any}>
              <Text className="text-text-muted text-xs hover:text-accent">{bot.name}</Text>
            </Link>
          )}
        </View>
        {channelId && (
          <Link href={`/channels/${channelId}/settings` as any} asChild>
            <Pressable className="p-2 rounded-md hover:bg-surface-overlay">
              <Settings size={16} color="#999999" />
            </Pressable>
          </Link>
        )}
      </View>

      {/* Messages — inverted FlatList so it naturally starts at the bottom */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <FlatList
          ref={flatListRef}
          inverted
          data={invertedData}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => <MessageBubble message={item} />}
          contentContainerStyle={{ padding: 16 }}
          scrollEventThrottle={100}
          onEndReached={handleLoadMore}
          onEndReachedThreshold={0.5}
          ListHeaderComponent={
            chatState.isStreaming ? (
              <StreamingIndicator
                content={chatState.streamingContent}
                toolCalls={chatState.toolCalls}
              />
            ) : null
          }
          ListFooterComponent={
            isFetchingNextPage ? (
              <View className="items-center py-3">
                <ActivityIndicator size="small" color="#3b82f6" />
              </View>
            ) : hasNextPage ? (
              <Pressable onPress={handleLoadMore} className="items-center py-3">
                <Text className="text-accent text-xs">Load older messages</Text>
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
        disabled={chatState.isStreaming}
      />
    </View>
  );
}
