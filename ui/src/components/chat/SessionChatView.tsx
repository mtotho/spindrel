import { useEffect, useMemo } from "react";
import type { Message } from "@/src/types/api";
import { useSessionMessages } from "@/src/api/hooks/useSessionMessages";
import { useSessionEvents } from "@/src/api/hooks/useSessionEvents";
import { useChatStore } from "@/src/stores/chat";
import { useThemeTokens } from "@/src/theme/tokens";
import { ChatMessageArea, DateSeparator } from "@/src/components/chat/ChatMessageArea";
import {
  formatDateSeparator,
  isDifferentDay,
  shouldGroup,
  getTurnText,
} from "@/app/(app)/channels/[channelId]/chatUtils";
import { MessageBubble } from "./MessageBubble";
import { TaskRunEnvelope } from "./TaskRunEnvelope";
import { TriggerCard, SUPPORTED_TRIGGERS } from "./TriggerCard";
import { extractDisplayText } from "./MessageBubble";
import {
  getThreadParentPreviewMessage,
  isThreadParentPreviewMessage,
} from "./threadPreview";
import { ThreadParentAnchor } from "./ThreadParentAnchor";

export interface SessionChatViewProps {
  /** The session whose Messages we render (the pipeline run's sub-session). */
  sessionId: string;
  /** The parent channel whose SSE stream carries the sub-session's events.
   *  Omit for channel-less ephemeral sessions — the hook falls back to
   *  ``/sessions/{sessionId}/events``. */
  parentChannelId?: string;
  /** Optional bot id to seed TURN_STARTED display lookups. */
  botId?: string;
  /** Custom empty-state node (pre-message pane can render description, etc). */
  emptyStateComponent?: React.ReactNode;
  /** Reserve space at the bottom of the scroll area so messages scroll
   *  BEHIND an overlay composer. Forwarded to ChatMessageArea. */
  scrollPaddingBottom?: number;
  /** UI-only rows to prepend to the persisted session transcript. Used by
   *  thread reply flows to show the parent message inline without creating
   *  a real Message row in the session. */
  syntheticMessages?: Message[];
  chatMode?: "default" | "terminal";
  bottomSlot?: React.ReactNode;
}

/**
 * Read-only chat transcript for an arbitrary session_id.
 *
 * Powers the pipeline run-view modal: mounts ``ChatMessageArea`` against
 * the sub-session's Messages + live SSE events (filtered from the parent
 * channel's bus). No composer, no queue, no slash commands — Phase 3
 * enables write access.
 *
 * The component keys its chat-store slot by ``sessionId`` so the modal's
 * in-flight turns don't bleed into the parent channel's state. Messages
 * are mirrored from the DB fetch into the store once per page arrival.
 */
export function SessionChatView({
  sessionId,
  parentChannelId,
  botId,
  emptyStateComponent,
  scrollPaddingBottom,
  syntheticMessages = [],
  chatMode = "default",
  bottomSlot,
}: SessionChatViewProps) {
  const t = useThemeTokens();
  const chatState = useChatStore((s) => s.getChannel(sessionId));
  const setMessages = useChatStore((s) => s.setMessages);

  // Subscribe to the parent channel's SSE stream but route filtered events
  // (payload.session_id === sessionId) into the chat store under sessionId.
  useSessionEvents(parentChannelId, sessionId, botId);

  // Fetch persisted messages for this session.
  const {
    data: pages,
    isLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useSessionMessages(sessionId);

  // Flatten pages → newest-first (what ChatMessageArea expects — it then
  // inverts to chronological for DOM rendering). Each page comes from the
  // backend in chronological order (oldest→newest within the page), and
  // pages themselves arrive newest-page first. Reverse each page so it's
  // newest-first internally, then concat in page order — page 0 (newest
  // batch) first, older pages appended.
  const invertedData = useMemo<Message[]>(() => {
    if (!pages) return [];
    return pages.pages.flatMap((p) => [...p.messages].reverse()).filter((m) => {
      const meta = (m.metadata ?? {}) as Record<string, any>;
      // task_run envelopes render even without role/content (metadata-only).
      if (meta.kind === "task_run") return true;
      // step_output Messages are the whole point of this view — assistant
      // rows tagged ui_only by emit_step_output_message.
      if (meta.kind === "step_output") return true;
      if (m.role !== "user" && m.role !== "assistant") return false;
      if (meta.passive && !meta.delegated_by) return false;
      if (m.role === "user" && meta.is_heartbeat) return false;
      // `hidden` rows from pipeline-child turns get re-surfaced here —
      // they ARE the sub-session's agent-step Messages. Only hide when the
      // metadata also flags pipeline_step AND we're not inside this
      // pipeline's run session (can't happen here, but safe).
      if (meta.hidden && !meta.pipeline_step) return false;
      if (
        m.role === "assistant" &&
        !extractDisplayText(m.content) &&
        (!m.attachments || m.attachments.length === 0) &&
        !meta.tool_results &&
        (!m.tool_calls || m.tool_calls.length === 0) &&
        !meta.assistant_turn_body &&
        !meta.transcript_entries
      )
        return false;
      return true;
    });
  }, [pages]);

  const renderedData = useMemo<Message[]>(
    () =>
      [...invertedData, ...syntheticMessages].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [invertedData, syntheticMessages],
  );

  // Sync the DB → chat-store slot so live turns + persisted rows share a
  // single list. Guarded by turn activity so streaming content isn't
  // clobbered mid-flight.
  const turnsCount = Object.keys(chatState.turns).length;
  useEffect(() => {
    if (pages && turnsCount === 0 && !chatState.isProcessing) {
      setMessages(sessionId, invertedData);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, pages, invertedData]);

  // Anchor-card grouping — a sub-session could itself host nested pipeline
  // anchors. Mirror the parent channel's "latest wins" heuristic.
  const latestAnchorByGroup = useMemo(() => {
    const ids = new Set<string>();
    const seen = new Set<string>();
    for (const m of renderedData) {
      const meta = (m.metadata ?? {}) as Record<string, any>;
      if (meta.kind !== "task_run") continue;
      const key =
        (meta.parent_task_id as string | null | undefined) ||
        (meta.title as string | null | undefined) ||
        m.id;
      if (!seen.has(key)) {
        seen.add(key);
        ids.add(m.id);
      }
    }
    return ids;
  }, [renderedData]);

  const renderMessage = ({ item, index }: { item: Message; index: number }) => {
    const prevMsg = renderedData[index + 1];
    const grouped = shouldGroup(item, prevMsg);
    const showDateSep =
      index === renderedData.length - 1 ||
      (prevMsg && isDifferentDay(item.created_at, prevMsg.created_at));
    const dateSep = showDateSep ? (
      <DateSeparator label={formatDateSeparator(item.created_at)} />
    ) : null;
    const meta = (item.metadata ?? {}) as Record<string, any>;
    if (isThreadParentPreviewMessage(item)) {
      return (
        <>
          {dateSep}
          <ThreadParentAnchor
            message={getThreadParentPreviewMessage(item)}
            inline
          />
        </>
      );
    }
    if (meta.kind === "task_run") {
      const collapsedByDefault = !latestAnchorByGroup.has(item.id);
      return (
        <>
          {dateSep}
          <TaskRunEnvelope message={item} collapsedByDefault={collapsedByDefault} />
        </>
      );
    }
    if (item.role === "user" && meta.trigger && SUPPORTED_TRIGGERS.has(meta.trigger)) {
      return (
        <>
          {dateSep}
          <TriggerCard message={item} />
        </>
      );
    }
    const isGrouped = showDateSep ? false : grouped;
    let headerIdx = index;
    while (
      headerIdx < renderedData.length - 1 &&
      shouldGroup(renderedData[headerIdx], renderedData[headerIdx + 1])
    ) {
      headerIdx++;
    }
    const fullTurnText = getTurnText(renderedData, headerIdx);
    const isLatest = item.role === "assistant" && index === 0;
    return (
      <>
        {dateSep}
        <MessageBubble
          message={item}
          isGrouped={isGrouped}
          fullTurnText={fullTurnText}
          isLatestBotMessage={isLatest}
          chatMode={chatMode}
        />
      </>
    );
  };

  const handleLoadMore = () => {
    if (hasNextPage && !isFetchingNextPage) fetchNextPage();
  };

  return (
    <ChatMessageArea
      invertedData={renderedData}
      renderMessage={renderMessage}
      chatState={chatState}
      bot={undefined}
      botId={botId}

      isLoading={isLoading}
      isFetchingNextPage={isFetchingNextPage}
      hasNextPage={hasNextPage}
      handleLoadMore={handleLoadMore}
      isProcessing={chatState.isProcessing}
      t={t}
      emptyStateComponent={emptyStateComponent}
      scrollPaddingBottom={scrollPaddingBottom}
      chatMode={chatMode}
      bottomSlot={bottomSlot}
    />
  );
}
