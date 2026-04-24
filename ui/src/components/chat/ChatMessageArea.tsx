import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { StreamingIndicator, ProcessingIndicator } from "@/src/components/chat/StreamingIndicator";
import { SpindrelLogo } from "@/src/components/layout/SpindrelLogo";
import { useThemeTokens } from "@/src/theme/tokens";
import type { Message } from "@/src/types/api";
import type { TurnState } from "@/src/stores/chat";
import {
  SCROLL_TO_MESSAGE_EVENT,
  notifyScrollMiss,
  type ScrollToMessageDetail,
} from "./renderers/FindResultsRenderer";

function cssEscape(s: string): string {
  // Safe wrapper for browsers that support CSS.escape; fallback strips the
  // handful of characters that would break an attribute selector. Message
  // ids are UUIDs in practice, so this is belt-and-suspenders.
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(s);
  }
  return s.replace(/["\\\]]/g, "");
}

function SkeletonBar({ width, height = 14 }: { width: string; height?: number }) {
  return <div className="rounded bg-skeleton/[0.04] animate-pulse" style={{ width, height }} />;
}

function MessageSkeletonRow({ widths, isUser = false }: { widths: string[]; isUser?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "row", gap: 10, padding: "6px 20px", justifyContent: isUser ? "flex-end" : "flex-start" }}>
      {!isUser && <div className="w-8 h-8 rounded-full bg-skeleton/[0.04] animate-pulse shrink-0" />}
      <div className="flex flex-col gap-1.5" style={{ maxWidth: 480 }}>
        {!isUser && <SkeletonBar width="70px" height={11} />}
        {widths.map((w, i) => <SkeletonBar key={i} width={w} />)}
      </div>
      {isUser && <div className="w-8 h-8 rounded-full bg-skeleton/[0.04] animate-pulse shrink-0" />}
    </div>
  );
}

function MessageSkeletons() {
  return (
    <>
      <MessageSkeletonRow widths={["220px", "160px"]} />
      <MessageSkeletonRow widths={["280px", "200px", "120px"]} />
      <MessageSkeletonRow widths={["180px"]} isUser />
      <MessageSkeletonRow widths={["300px", "240px"]} />
      <MessageSkeletonRow widths={["160px", "100px"]} isUser />
    </>
  );
}

export function DateSeparator({ label }: { label: string }) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
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
  chatState: { turns: Record<string, TurnState>; error?: string | null };
  bot: { name?: string } | undefined;
  botId?: string;
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage?: boolean;
  handleLoadMore: () => void;
  isProcessing?: boolean;
  t: ReturnType<typeof useThemeTokens>;
  /** Render prop for channel-specific pending approvals section.
      Receives the Set of liveApprovalIds (already-tracked by live turns) so
      the caller can deduplicate. Omit for sub-sessions and ephemeral chats. */
  pendingApprovalsSlot?: (liveApprovalIds: Set<string>) => React.ReactNode;
  /** Custom empty-state content shown when there are no messages. Overrides the
      default "Send a message to start the conversation" span. Channel-agnostic:
      any channel can inject a purpose-specific empty-state (e.g. orchestrator's
      launchpad, DM channels' suggested prompts, etc). */
  emptyStateComponent?: React.ReactNode;
  /** Top padding on the scroll container — lets callers reserve space for an
   *  overlay header that messages should scroll behind. Default 8. */
  scrollPaddingTop?: number;
  /** Bottom padding on the scroll container — reserves space for an overlay
   *  composer so messages can scroll behind it. Default 12. */
  scrollPaddingBottom?: number;
  chatMode?: "default" | "terminal";
  bottomSlot?: React.ReactNode;
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
// "stays stuck up" bugs were. See project-notes/Track - UI Polish.md.
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
  pendingApprovalsSlot,
  emptyStateComponent,
  scrollPaddingTop = 8,
  scrollPaddingBottom = 12,
  chatMode = "default",
  bottomSlot,
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

  // Listen for /find clicks requesting a jump to a specific message. If the
  // target DOM node isn't mounted (virtualized far scrollback or a different
  // session's message), fall back to the toast so the user knows to scroll up.
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<ScrollToMessageDetail>).detail;
      if (!detail?.messageId) return;
      const root = scrollRef.current;
      if (!root) return;
      const selector = `[data-message-id="${cssEscape(detail.messageId)}"]`;
      const node = root.querySelector<HTMLElement>(selector);
      if (!node) {
        notifyScrollMiss();
        return;
      }
      node.scrollIntoView({ behavior: "smooth", block: "center" });
      node.classList.add("msg-highlight");
      window.setTimeout(() => node.classList.remove("msg-highlight"), 1600);
    };
    window.addEventListener(SCROLL_TO_MESSAGE_EVENT, handler);
    return () => window.removeEventListener(SCROLL_TO_MESSAGE_EVENT, handler);
  }, []);

  // Render every in-flight turn uniformly. Sort the channel's primary
  // bot first (if present), then by insertion order so concurrent member
  // bot turns appear below.
  const turnEntries = Object.entries(chatState.turns).sort((a, b) => {
    if (a[1].isPrimary && !b[1].isPrimary) return -1;
    if (b[1].isPrimary && !a[1].isPrimary) return 1;
    return 0;
  });
  const turnIndicators = turnEntries.map(([turnId, turn]) => (
    <StreamingIndicator
      key={turnId}
      content={turn.streamingContent}
      toolCalls={turn.toolCalls}
      assistantTurnBody={turn.assistantTurnBody}
      autoInjectedSkills={turn.autoInjectedSkills}
      botName={turn.botName}
      botId={turn.isPrimary ? botId : turn.botId}
      thinkingContent={turn.thinkingContent}
      llmStatus={turn.llmStatus}
      chatMode={chatMode}
    />
  ));

  // Background-task processing without an in-flight turn (e.g. queued
  // task accepted but worker not yet started) gets the simpler indicator.
  const processingIndicator =
    isProcessing && turnIndicators.length === 0 ? (
      <ProcessingIndicator chatMode={chatMode} />
    ) : null;

  // Approval ids already represented by a live turn card — the orphan
  // approvals section dedupes against these so we don't double-render.
  const liveApprovalIds = useMemo(() => {
    const s = new Set<string>();
    for (const turn of Object.values(chatState.turns)) {
      for (const tc of turn.toolCalls) {
        if (tc.approvalId) s.add(tc.approvalId);
      }
    }
    return s;
  }, [chatState.turns]);
  const isTerminalMode = chatMode === "terminal";
  const errorBanner = chatState.error ? (
    <div
      role="status"
      className="rounded-md px-3 py-2 text-xs"
      style={{
        backgroundColor: t.dangerSubtle,
        border: `1px solid ${t.dangerBorder}`,
        color: t.danger,
        marginBottom: 8,
        overflowWrap: "anywhere",
      }}
    >
      {chatState.error}
    </div>
  ) : null;
  const terminalFooterContent = (
    <>
      {errorBanner}
      {pendingApprovalsSlot?.(liveApprovalIds)}
      {turnIndicators}
      {processingIndicator}
      {bottomSlot}
    </>
  );
  const defaultFooterContent = (
    <>
      {errorBanner}
      {bottomSlot}
      {pendingApprovalsSlot?.(liveApprovalIds)}
      {turnIndicators}
      {processingIndicator}
    </>
  );

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
          paddingTop: scrollPaddingTop,
          paddingBottom: scrollPaddingBottom,
          backgroundColor: isTerminalMode ? `${t.overlayLight}08` : undefined,
        }}
      >
        {/* Each column-reverse child is centered within the full-width scroll
            container and capped at 820px. The scroll container itself spans
            edge-to-edge so the scrollbar sits at the right edge of the chat
            column, not at the right edge of the 820px content area. */}
        {/* DOM first == visual BOTTOM — streaming / processing indicators +
            a Spindrel brand mark tucked below the newest message. Scrolls
            with the content so it slips off when the user scrolls up. */}
        <div
          className="w-full mx-auto"
          style={{
            maxWidth: 820,
            paddingLeft: 16,
            paddingRight: 16,
          }}
        >
          {isTerminalMode ? terminalFooterContent : defaultFooterContent}
          {!isTerminalMode && invertedData.length > 0 && (
            <div className="flex flex-row justify-center" style={{ paddingTop: 12, paddingBottom: 6, opacity: isTerminalMode ? 0.16 : 0.7 }}>
              <SpindrelLogo size={20} color={t.purple} />
            </div>
          )}
        </div>

        {/* Messages in chronological DOM order inside a normal-flow div. */}
        {invertedData.length === 0 ? (
          <div
            className="w-full mx-auto px-4"
            style={{
              maxWidth: 820,
              display: "flex",
              flexDirection: "column",
              justifyContent: isLoading ? "flex-end" : "center",
              alignItems: isLoading ? "stretch" : "center",
              padding: isLoading ? "16px 0" : emptyStateComponent ? "20px 0" : "80px 20px",
              flex: 1,
            }}
          >
            {isLoading ? (
              <MessageSkeletons />
            ) : emptyStateComponent ? (
              emptyStateComponent
            ) : (
              <span style={{ color: t.textDim, fontSize: 14 }}>
                Send a message to start the conversation
              </span>
            )}
          </div>
        ) : (
          <div className="w-full mx-auto px-4" style={{ maxWidth: 820 }}>
            {Array.from({ length: invertedData.length }, (_, i) => {
              const chronIdx = invertedData.length - 1 - i;
              const item = invertedData[chronIdx];
              return (
                <div key={item.id} data-message-id={item.id} style={{ userSelect: "text" }}>
                  {renderMessage({ item, index: chronIdx })}
                </div>
              );
            })}
          </div>
        )}

        {/* DOM last == visual TOP — sentinel for loading older pages. */}
        <div ref={sentinelRef} style={{ minHeight: 1, flexShrink: 0 }}>
          {isFetchingNextPage && (
            <div style={{ display: "flex", flexDirection: "row", justifyContent: "center", padding: "12px 0" }}>
              <div className="chat-spinner" />
            </div>
          )}
        </div>
      </div>

      {showFab && (
        // Anchor the FAB to the COMPOSER's right edge, not the chat column's.
        // The composer is `max-w-[820px] mx-auto`, so on wide viewports its
        // right edge sits far inboard of the column edge — a FAB pinned to
        // the column edge lands in the right-margin gap; on narrow viewports
        // the composer stretches to the column edge and the same FAB sits
        // on top of the input. Mirror the composer's max-w-820 centered
        // container so the FAB always tracks the composer's right edge.
        // `pointer-events: none` on the wrapper lets clicks fall through
        // the empty areas to the chat behind; the button itself re-enables
        // pointer events.
        <div
          aria-hidden={false}
          style={{
            position: "absolute",
            bottom: scrollPaddingBottom + 12,
            left: 0,
            right: 0,
            display: "flex",
            justifyContent: "center",
            pointerEvents: "none",
          }}
        >
          <div
            style={{
              width: "100%",
              maxWidth: 820,
              padding: "0 16px",
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <button
              onClick={doScrollToBottom}
              className="scroll-fab"
              aria-label="Scroll to latest message"
              title="Scroll to latest"
              style={{
                pointerEvents: "auto",
                width: 36,
                height: 36,
                borderRadius: 18,
                backgroundColor: t.surfaceRaised,
                border: `1px solid ${t.surfaceBorder}`,
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
                cursor: "pointer",
                padding: 0,
              }}
            >
              <ChevronDown size={18} color={t.textMuted} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
