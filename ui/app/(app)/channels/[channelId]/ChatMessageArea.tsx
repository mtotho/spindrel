import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable, Platform, type NativeSyntheticEvent, type NativeScrollEvent } from "react-native";
import { ChevronDown } from "lucide-react";
import { StreamingIndicator, ProcessingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useThemeTokens } from "@/src/theme/tokens";
import type { Message } from "@/src/types/api";

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

// ---------------------------------------------------------------------------
// Web: column-reverse scroll container (no scaleY transforms = proper text selection)
// ---------------------------------------------------------------------------

function WebChatList({
  invertedData,
  renderMessage,
  chatState,
  bot,
  isLoading,
  isFetchingNextPage,
  handleLoadMore,
  isProcessing,
  t,
}: ChatMessageAreaProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const [showFab, setShowFab] = useState(false);

  // Load older pages when the sentinel at the visual top becomes visible
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = scrollRef.current;
    if (!sentinel || !root) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) handleLoadMore(); },
      { root, rootMargin: "200px 0px 0px 0px", threshold: 0 },
    );
    obs.observe(sentinel);
    return () => obs.disconnect();
  }, [handleLoadMore]);

  // Track scroll position for FAB visibility
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      // In column-reverse, scrollTop=0 is at the bottom (newest).
      // Scrolling up toward older messages gives negative scrollTop.
      setShowFab(el.scrollTop < -300);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Auto-scroll: column-reverse doesn't reliably pin to the bottom when
  // content grows (streaming text, new messages).  After every render, if
  // the user is near the bottom, snap to scrollTop=0 (the visual bottom).
  useEffect(() => {
    const el = scrollRef.current;
    if (el && el.scrollTop >= -100) {
      el.scrollTop = 0;
    }
  });

  const doScrollToBottom = useCallback(() => {
    scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const indicator = chatState.isStreaming ? (
    <StreamingIndicator
      content={chatState.streamingContent}
      toolCalls={chatState.toolCalls}
      botName={bot?.name}
      thinkingContent={chatState.thinkingContent}
    />
  ) : isProcessing ? (
    <ProcessingIndicator botName={bot?.name} />
  ) : null;

  return (
    <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
      <div
        ref={scrollRef}
        className="chat-scroll-web"
        style={{
          display: "flex",
          flexDirection: "column-reverse",
          overflowY: "auto",
          height: "100%",
          paddingTop: 8,
          paddingBottom: 8,
        }}
      >
        {/* First in DOM = visual bottom in column-reverse */}
        {indicator}

        {invertedData.map((item, index) => (
          <div key={item.id} style={{ display: "flex", flexDirection: "column-reverse", userSelect: "text" }}>
            {renderMessage({ item, index })}
          </div>
        ))}

        {/* Last in DOM = visual top — sentinel for loading older pages */}
        <div ref={sentinelRef} style={{ minHeight: 1, flexShrink: 0 }}>
          {isFetchingNextPage && (
            <div style={{ display: "flex", justifyContent: "center", padding: "12px 0" }}>
              <ActivityIndicator size="small" color="#666666" />
            </div>
          )}
        </div>

        {/* Empty / loading state (last in DOM = visual top) */}
        {invertedData.length === 0 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "80px 0", flex: 1 }}>
            {isLoading ? (
              <ActivityIndicator color={t.textDim} />
            ) : (
              <Text style={{ color: t.textDim, fontSize: 14 }}>
                Send a message to start the conversation
              </Text>
            )}
          </div>
        )}
      </div>

      {showFab && (
        <Pressable
          onPress={doScrollToBottom}
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
            boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
            cursor: "pointer",
          } as any}
        >
          <ChevronDown size={20} color={t.textMuted} />
        </Pressable>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Native: inverted FlatList (scaleY is fine on native — no text selection issue)
// ---------------------------------------------------------------------------

/**
 * Cell wrapper that enables text selection on web.
 * Kept for the native FlatList path as a no-op on non-web.
 */
const SelectableCell = Platform.OS === "web"
  ? React.forwardRef<View, any>((props, ref) => (
      <View {...props} ref={ref} style={[props.style, { userSelect: "text" } as any]} />
    ))
  : undefined;
if (SelectableCell) SelectableCell.displayName = "SelectableCell";

function NativeChatList({
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

// ---------------------------------------------------------------------------
// Public component — picks the right implementation per platform
// ---------------------------------------------------------------------------

export function ChatMessageArea(props: ChatMessageAreaProps) {
  if (Platform.OS === "web") {
    return <WebChatList {...props} />;
  }
  return <NativeChatList {...props} />;
}
