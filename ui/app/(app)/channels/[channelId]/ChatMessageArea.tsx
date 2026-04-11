import React, { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { StreamingIndicator, ProcessingIndicator } from "@/src/components/chat/StreamingIndicator";
import { useThemeTokens } from "@/src/theme/tokens";
import type { Message } from "@/src/types/api";
import type { MemberStreamState } from "@/src/stores/chat";

export function DateSeparator({ label }: { label: string }) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "12px 20px",
        maxWidth: 480,
        margin: "0 auto",
        userSelect: "none",
      }}
    >
      <div style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder }} />
      <span style={{ fontSize: 11, fontWeight: 600, color: t.textDim, whiteSpace: "nowrap", textTransform: "uppercase" as const, letterSpacing: 1.5 }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder }} />
    </div>
  );
}

export interface ChatMessageAreaProps {
  invertedData: Message[];
  renderMessage: (info: { item: Message; index: number }) => React.JSX.Element;
  chatState: { isStreaming: boolean; streamingContent: string; toolCalls: any[]; thinkingContent: string; respondingBotName?: string | null; memberStreams?: Record<string, MemberStreamState> };
  bot: { name?: string } | undefined;
  botId?: string;
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage?: boolean;
  handleLoadMore: () => void;
  isProcessing?: boolean;
  t: ReturnType<typeof useThemeTokens>;
}

// ---------------------------------------------------------------------------
// Web chat scroll container.
//
// Layout strategy: `flex-direction: column-reverse` on the OUTER scroll
// container (DOM-first child == visual bottom), but the messages live inside
// a normal-flow inner div so their DOM order matches their visual order.
// This is the canonical "best of both worlds" chat pattern:
//
//   1. The browser natively pins scroll position to the visual bottom —
//      scrollTop === 0 always means "at the newest message", no JS required.
//      New messages, streaming chunks, and late-loading images all stay
//      pinned without any manual scrollTop math.
//   2. Older-page prepend requires no scroll-preservation hack — growing the
//      content above the visual bottom simply extends the scroll range
//      upward; visible content does not jump.
//   3. Native text selection works because the messages live in DOM order
//      inside a normal-flow wrapper (the reversal affects only the scroll
//      container's immediate children, not the message list).
//
// Do NOT reintroduce imperative `scrollTop = scrollHeight` effects — they
// race with image loads, streaming reflows, and prepend adjustments, and
// that race is what the "starts scrolled up, then jumps down" and
// "stays stuck up" bugs were. See vault: Track - UI Polish, April 10 session.
// ---------------------------------------------------------------------------

export function ChatMessageArea({
  invertedData,
  renderMessage,
  chatState,
  botId,
  isLoading,
  isFetchingNextPage,
  hasNextPage,
  handleLoadMore,
  isProcessing,
  t,
}: ChatMessageAreaProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const [showFab, setShowFab] = useState(false);

  // Stable ref for load-more callback
  const handleLoadMoreRef = useRef(handleLoadMore);
  handleLoadMoreRef.current = handleLoadMore;

  // Load older pages when the sentinel at the visual top becomes visible.
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

  // FAB visibility. In column-reverse, scrollTop is 0 at the visual bottom
  // and becomes negative as the user scrolls up (Chrome/Firefox + Safari
  // 16+). Treat "within 100px of the bottom" as at-bottom.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      setShowFab(Math.abs(el.scrollTop) > 100);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // IntersectionObserver does not always re-fire if the sentinel was already
  // intersecting when an entry landed (short threads where page 1 doesn't
  // fill the viewport). After each page settles, re-check the sentinel and
  // request another page if it's still visible.
  useEffect(() => {
    if (!hasNextPage || isFetchingNextPage) return;
    const root = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel) return;
    const rootRect = root.getBoundingClientRect();
    const sentinelRect = sentinel.getBoundingClientRect();
    if (sentinelRect.bottom >= rootRect.top - 200 && sentinelRect.top <= rootRect.bottom) {
      handleLoadMoreRef.current();
    }
  }, [invertedData.length, hasNextPage, isFetchingNextPage]);

  const doScrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const streamingBotName = chatState.respondingBotName ?? undefined;
  const primaryIndicator = chatState.isStreaming ? (
    <StreamingIndicator
      content={chatState.streamingContent}
      toolCalls={chatState.toolCalls}
      botName={streamingBotName}
      botId={botId}
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

  const hasIndicators = !!primaryIndicator || memberIndicators.length > 0;

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
        {/* DOM first == visual BOTTOM — streaming / processing indicators.
            Wrap in a single div so the reverse order of memberIndicators +
            primaryIndicator is determined by normal DOM flow inside, not by
            the outer reverse. */}
        {hasIndicators && (
          <div>
            {memberIndicators}
            {primaryIndicator}
          </div>
        )}

        {/* Messages in chronological DOM order inside a normal-flow div.
            Native selection works because DOM order matches visual order
            within this wrapper; the reverse only applies to the outer
            container's children. */}
        {invertedData.length === 0 ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "80px 20px", flex: 1 }}>
            {isLoading ? (
              <div className="chat-spinner" />
            ) : (
              <span style={{ color: t.textDim, fontSize: 14 }}>
                Send a message to start the conversation
              </span>
            )}
          </div>
        ) : (
          <div>
            {Array.from({ length: invertedData.length }, (_, i) => {
              const chronIdx = invertedData.length - 1 - i;
              const item = invertedData[chronIdx];
              return (
                <div key={item.id} style={{ userSelect: "text" }}>
                  {renderMessage({ item, index: chronIdx })}
                </div>
              );
            })}
          </div>
        )}

        {/* DOM last == visual TOP — sentinel for loading older pages. */}
        <div ref={sentinelRef} style={{ minHeight: 1, flexShrink: 0 }}>
          {isFetchingNextPage && (
            <div style={{ display: "flex", justifyContent: "center", padding: "12px 0" }}>
              <div className="chat-spinner" />
            </div>
          )}
        </div>
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
