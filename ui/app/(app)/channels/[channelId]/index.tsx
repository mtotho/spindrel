import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable } from "react-native";
import { useLocalSearchParams, Link } from "expo-router";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Settings, Menu } from "lucide-react";
import { MessageBubble } from "@/src/components/chat/MessageBubble";
import { MessageInput } from "@/src/components/chat/MessageInput";
import { StreamingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useChatStore } from "@/src/stores/chat";
import { useUIStore } from "@/src/stores/ui";
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
  const flatListRef = useRef<FlatList>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const didInitScroll = useRef(false);

  const { data: channel } = useChannel(channelId);
  const { data: bot } = useBot(channel?.bot_id);
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

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
      return lastPage.messages[0].id; // oldest message id in the page
    },
    enabled: !!channel?.active_session_id,
  });

  // Sync fetched pages into the chat store
  useEffect(() => {
    if (channelId && pages) {
      // Pages are loaded newest-first (page 0 = newest), each page is in chronological order.
      // Combine: oldest pages first, then newer pages.
      const allMessages = [...pages.pages].reverse().flatMap((p) => p.messages);
      setMessages(channelId, allMessages);
    }
  }, [channelId, pages]);

  // Scroll to bottom when content size changes (reliable for initial load + new messages)
  const handleContentSizeChange = useCallback((_w: number, h: number) => {
    if (!didInitScroll.current && h > 0) {
      didInitScroll.current = true;
      flatListRef.current?.scrollToEnd({ animated: false });
    } else if (isAtBottom) {
      flatListRef.current?.scrollToEnd({ animated: true });
    }
  }, [isAtBottom]);

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

  // Track scroll position — auto-scroll when near bottom, load more when near top
  const handleScroll = useCallback((e: any) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const distanceFromBottom = contentSize.height - contentOffset.y - layoutMeasurement.height;
    setIsAtBottom(distanceFromBottom < 100);

    // Load older messages when scrolled near top
    if (contentOffset.y < 100 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border">
        {sidebarCollapsed && (
          <Pressable onPress={toggleSidebar} className="p-1.5 rounded-md hover:bg-surface-overlay">
            <Menu size={18} color="#9ca3af" />
          </Pressable>
        )}
        <View className="flex-1 min-w-0">
          <Text className="text-text font-semibold" numberOfLines={1}>
            {(channel as any)?.display_name || channel?.name || channel?.client_id || "Chat"}
          </Text>
          {bot && (
            <Text className="text-text-muted text-xs">{bot.name}</Text>
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

      {/* Messages */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <FlatList
          ref={flatListRef}
          data={chatState.messages}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => <MessageBubble message={item} />}
          contentContainerStyle={{ padding: 16, flexGrow: 1, justifyContent: "flex-end" }}
          onScroll={handleScroll}
          scrollEventThrottle={100}
          onContentSizeChange={handleContentSizeChange}
          ListHeaderComponent={
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
          ListFooterComponent={
            chatState.isStreaming ? (
              <StreamingIndicator
                content={chatState.streamingContent}
                toolCalls={chatState.toolCalls}
              />
            ) : null
          }
          ListEmptyComponent={
            <View className="flex-1 items-center justify-center">
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
