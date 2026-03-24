import { useCallback, useEffect, useRef } from "react";
import { View, Text, FlatList, ActivityIndicator } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { MessageBubble } from "@/src/components/chat/MessageBubble";
import { MessageInput } from "@/src/components/chat/MessageInput";
import { StreamingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useChatStore } from "@/src/stores/chat";
import { useChatStream } from "@/src/api/hooks/useChat";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useBot } from "@/src/api/hooks/useBots";
import { apiFetch } from "@/src/api/client";
import type { Message, Session } from "@/src/types/api";

export default function ChatScreen() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const flatListRef = useRef<FlatList>(null);

  const { data: channel } = useChannel(channelId);
  const { data: bot } = useBot(channel?.bot_id);

  const chatState = useChatStore((s) => s.getChannel(channelId!));
  const setMessages = useChatStore((s) => s.setMessages);
  const addMessage = useChatStore((s) => s.addMessage);
  const startStreaming = useChatStore((s) => s.startStreaming);
  const handleSSEEvent = useChatStore((s) => s.handleSSEEvent);
  const finishStreaming = useChatStore((s) => s.finishStreaming);
  const setError = useChatStore((s) => s.setError);

  // Load session messages
  const { isLoading } = useQuery({
    queryKey: ["session-messages", channel?.active_session_id],
    queryFn: async () => {
      if (!channel?.active_session_id) return [];
      const session = await apiFetch<Session & { messages: Message[] }>(
        `/sessions/${channel.active_session_id}`
      );
      return session.messages ?? [];
    },
    enabled: !!channel?.active_session_id,
    onSuccess: (messages: Message[]) => {
      if (channelId) setMessages(channelId, messages);
    },
  });

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

      // Add user message immediately
      addMessage(channelId, {
        id: `msg-${Date.now()}`,
        session_id: channel.active_session_id ?? "",
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      });

      // Start streaming
      startStreaming(channelId);

      chatStream.mutate({
        message: text,
        bot_id: channel.bot_id,
        client_id: channel.client_id,
        channel_id: channelId,
      });
    },
    [channelId, channel]
  );

  // Auto-scroll on new messages
  useEffect(() => {
    if (chatState.messages.length > 0 || chatState.streamingContent) {
      setTimeout(() => flatListRef.current?.scrollToEnd({ animated: true }), 100);
    }
  }, [chatState.messages.length, chatState.streamingContent]);

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border">
        <View className="flex-1 min-w-0">
          <Text className="text-text font-semibold" numberOfLines={1}>
            {channel?.display_name || channel?.client_id || "Chat"}
          </Text>
          {bot && (
            <Text className="text-text-muted text-xs">{bot.name}</Text>
          )}
        </View>
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
