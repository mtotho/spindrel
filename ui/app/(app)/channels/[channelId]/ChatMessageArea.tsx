import React from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable, Platform, type NativeSyntheticEvent, type NativeScrollEvent } from "react-native";
import { ChevronDown } from "lucide-react";
import { StreamingIndicator, ProcessingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useThemeTokens } from "@/src/theme/tokens";
import type { Message } from "@/src/types/api";

/**
 * Cell wrapper that enables text selection on web.
 * React Native Web's View defaults to user-select: none, which prevents
 * selecting text across multiple messages. This override restores it.
 */
const SelectableCell = Platform.OS === "web"
  ? React.forwardRef<View, any>((props, ref) => (
      <View {...props} ref={ref} style={[props.style, { userSelect: "text" } as any]} />
    ))
  : undefined;
if (SelectableCell) SelectableCell.displayName = "SelectableCell";

export function DateSeparator({ label }: { label: string }) {
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

export interface ChatMessageAreaProps {
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
}

/** Extracted chat message list + scroll-to-bottom FAB so it can be reused in both mobile and desktop layouts */
export function ChatMessageArea({
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
}: ChatMessageAreaProps) {
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
        CellRendererComponent={SelectableCell}
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
