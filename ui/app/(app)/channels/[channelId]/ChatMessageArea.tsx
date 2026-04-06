import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, FlatList, ActivityIndicator, Pressable, Platform, type NativeSyntheticEvent, type NativeScrollEvent } from "react-native";
import { ChevronDown } from "lucide-react";
import { StreamingIndicator, ProcessingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useThemeTokens } from "@/src/theme/tokens";
import type { Message } from "@/src/types/api";
import type { MemberStreamState } from "@/src/stores/chat";

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
  chatState: { isStreaming: boolean; streamingContent: string; toolCalls: any[]; thinkingContent: string; respondingBotName?: string | null; memberStreams?: Record<string, MemberStreamState> };
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

  // Stable ref for load-more callback — prevents IntersectionObserver from
  // disconnecting/reconnecting every time handleLoadMore identity changes
  // (which happens on every hasNextPage/isFetchingNextPage state transition).
  const handleLoadMoreRef = useRef(handleLoadMore);
  handleLoadMoreRef.current = handleLoadMore;

  // Load older pages when the sentinel at the visual top becomes visible.
  // Observer is created once and never reconnects — uses ref for callback.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = scrollRef.current;
    if (!sentinel || !root) return;
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          handleLoadMoreRef.current();
        }
      },
      { root, rootMargin: "200px 0px 0px 0px", threshold: 0 },
    );
    obs.observe(sentinel);
    return () => obs.disconnect();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After a page finishes loading, re-check if the sentinel is still visible.
  // The stable observer above won't re-fire if the sentinel never left the
  // viewport (e.g. short message list that doesn't fill the screen).
  // Only triggers on isFetchingNextPage true→false transitions.  The natural
  // sentinel-visibility check stops loading once content fills the viewport.
  const recheckRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevFetchingRef = useRef(false);
  const wasAtBottomRef = useRef(true);
  useEffect(() => {
    const wasFetching = prevFetchingRef.current;
    prevFetchingRef.current = isFetchingNextPage;

    // When a fetch starts, record whether the user is at the bottom.
    if (isFetchingNextPage && !wasFetching) {
      const el = scrollRef.current;
      wasAtBottomRef.current = !el || el.scrollTop >= -100;
      return;
    }
    if (isFetchingNextPage) return;

    // Page just finished loading (true→false transition).
    if (!wasFetching) return;

    // Pin to bottom if user was at bottom before the load started.
    // This counteracts any browser scroll-shift from DOM changes.
    if (wasAtBottomRef.current) {
      const el = scrollRef.current;
      if (el) el.scrollTop = 0;
    }

    // Re-check sentinel visibility — if content still doesn't fill the
    // viewport, load another page.  Once content fills the viewport the
    // sentinel moves off-screen and loading stops naturally.
    if (recheckRef.current) clearTimeout(recheckRef.current);
    recheckRef.current = setTimeout(() => {
      const sentinel = sentinelRef.current;
      const root = scrollRef.current;
      if (!sentinel || !root) return;
      const rootRect = root.getBoundingClientRect();
      const sentinelRect = sentinel.getBoundingClientRect();
      if (sentinelRect.bottom >= rootRect.top - 200 && sentinelRect.top <= rootRect.bottom) {
        handleLoadMoreRef.current();
      }
    }, 500);
    return () => { if (recheckRef.current) clearTimeout(recheckRef.current); };
  }, [isFetchingNextPage]);

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

  // Auto-scroll: keep the view pinned to the bottom (scrollTop=0 in
  // column-reverse) while streaming or when new messages arrive.
  // Only fires when the user hasn't scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && el.scrollTop >= -100) {
      el.scrollTop = 0;
    }
  });

  const doScrollToBottom = useCallback(() => {
    scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const streamingBotName = chatState.respondingBotName || bot?.name;
  const primaryIndicator = chatState.isStreaming ? (
    <StreamingIndicator
      content={chatState.streamingContent}
      toolCalls={chatState.toolCalls}
      botName={streamingBotName}
      thinkingContent={chatState.thinkingContent}
    />
  ) : isProcessing ? (
    <ProcessingIndicator botName={streamingBotName} />
  ) : null;

  // Concurrent member bot streams
  const memberEntries = Object.entries(chatState.memberStreams ?? {});
  const memberIndicators = memberEntries.map(([streamId, stream]) => (
    <StreamingIndicator
      key={streamId}
      content={stream.streamingContent}
      toolCalls={stream.toolCalls}
      botName={stream.botName}
      thinkingContent={stream.thinkingContent}
    />
  ));

  const hasIndicators = primaryIndicator || memberIndicators.length > 0;
  // In column-reverse, first child = visual bottom (closest to input).
  // Primary bot goes first (bottom), member bots stack above it.
  const indicators = hasIndicators ? (
    <>
      {primaryIndicator}
      {memberIndicators}
    </>
  ) : null;

  return (
    <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}>
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
        {indicators}

        {invertedData.map((item, index) => (
          <div key={item.id} style={{ userSelect: "text" }}>
            {renderMessage({ item, index })}
          </div>
        ))}

        {/* Last in DOM = visual top — sentinel for loading older pages */}
        <div ref={sentinelRef} style={{ minHeight: 1, flexShrink: 0 }}>
          {isFetchingNextPage && (
            <div style={{ display: "flex", justifyContent: "center", padding: "12px 0" }}>
              <div className="chat-spinner" />
            </div>
          )}
        </div>

        {/* Empty / loading state (last in DOM = visual top) */}
        {invertedData.length === 0 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "80px 0", flex: 1 }}>
            {isLoading ? (
              <div className="chat-spinner" />
            ) : (
              <span style={{ color: t.textDim, fontSize: 14 }}>
                Send a message to start the conversation
              </span>
            )}
          </div>
        )}
      </div>

      {showFab && (
        <button
          onClick={doScrollToBottom}
          className="scroll-fab"
          style={{
            position: "absolute",
            bottom: 16,
            right: 24,
            width: 40,
            height: 40,
            borderRadius: 20,
            backgroundColor: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
            cursor: "pointer",
            padding: 0,
          }}
        >
          <ChevronDown size={20} color={t.textMuted} />
        </button>
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
        ListHeaderComponent={(() => {
          const nativeBotName = chatState.respondingBotName || bot?.name;
          const nativePrimary = chatState.isStreaming ? (
            <StreamingIndicator
              content={chatState.streamingContent}
              toolCalls={chatState.toolCalls}
              botName={nativeBotName}
              thinkingContent={chatState.thinkingContent}
            />
          ) : isProcessing ? (
            <ProcessingIndicator botName={nativeBotName} />
          ) : null;
          const nativeMemberEntries = Object.entries(chatState.memberStreams ?? {});
          const nativeMemberIndicators = nativeMemberEntries.map(([sid, ms]) => (
            <StreamingIndicator
              key={sid}
              content={ms.streamingContent}
              toolCalls={ms.toolCalls}
              botName={ms.botName}
              thinkingContent={ms.thinkingContent}
            />
          ));
          if (!nativePrimary && nativeMemberIndicators.length === 0) return null;
          // Primary bot first (at bottom in inverted list), member bots above
          return (
            <>
              {nativePrimary}
              {nativeMemberIndicators}
            </>
          );
        })()
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
