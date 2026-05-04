import { memo, useMemo, useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Brain, ChevronRight } from "lucide-react";
import { useIsMobile } from "../../hooks/useIsMobile";
import { useThemeTokens, type ThemeTokens } from "../../theme/tokens";
import { formatTimeShort } from "../../utils/time";
import { DelegationCard } from "./DelegationCard";
import { MarkdownContent } from "./MarkdownContent";
import { AttachmentImages } from "./AttachmentDisplay";
import { MessageActions, TimestampActions, Avatar } from "./MessageActions";
import { CollapsedHeartbeat, CollapsedWorkflow } from "./CollapsedMessages";
import { ThreadAnchor } from "./ThreadAnchor";
import { TurnFeedbackControls } from "./TurnFeedbackControls";
import { extractDisplayText, stripLegacyIngestPrefix, resolveDisplay, terminalTranscriptRole, avatarColor } from "./messageUtils";
import { normalizeToolCall } from "../../types/api";
import { usePinnedWidgetsStore } from "../../stores/pinnedWidgets";
import type { AssistantTurnBody, Message, ToolCall, ToolResultEnvelope } from "../../types/api";
import type { ThreadSummary } from "../../api/hooks/useThreads";
import { SlashCommandResultCard } from "./SlashCommandResultCard";
import {
  buildAssistantTurnBodyItems,
  buildLegacyAssistantTurnBody,
  type OrderedTurnBodyItem,
} from "./toolTranscriptModel";
import { OrderedTranscript } from "./OrderedTranscript";
import { isHarnessQuestionMessage } from "./harnessQuestionMessages";
import {
  CHAT_ROW_CONTENT_INDENT,
  CHAT_ROW_GAP,
  CHAT_ROW_NARROW_X_PADDING,
  CHAT_ROW_TERMINAL_X_PADDING,
  CHAT_ROW_X_PADDING,
} from "./chatRowLayout";

// Re-export for external consumers
export { extractDisplayText } from "./messageUtils";
export { MarkdownContent } from "./MarkdownContent";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";
const WIDGET_LIBRARY_URI_RE = /^widget:\/\/(bot|workspace)\/([^/]+)(?:\/|$)/i;
const FILE_WRITE_OPERATIONS = new Set([
  "create",
  "overwrite",
  "append",
  "edit",
  "json_patch",
  "delete",
  "mkdir",
  "move",
  "restore",
]);
const EMPTY_FEEDBACK = { mine: null, totals: { up: 0, down: 0 }, comment_mine: null };

function isFeedbackEligibleAssistantMessage(message: Message): boolean {
  return (
    message.role === "assistant" &&
    !!message.correlation_id &&
    !!extractDisplayText(message.content).trim() &&
    !(Array.isArray(message.tool_calls) && message.tool_calls.length > 0)
  );
}

function extractWidgetLibraryRef(rawPath: unknown): string | null {
  if (typeof rawPath !== "string") return null;
  const match = WIDGET_LIBRARY_URI_RE.exec(rawPath.trim());
  if (!match) return null;
  return `${match[1].toLowerCase()}/${match[2]}`;
}

function collectInvalidatedLibraryRefs(toolCalls?: ToolCall[]): string[] {
  if (!toolCalls?.length) return [];
  const refs = new Set<string>();
  for (const call of toolCalls) {
    const norm = normalizeToolCall(call);
    const shortName = norm.name.includes("-") ? norm.name.slice(norm.name.lastIndexOf("-") + 1) : norm.name;
    if (shortName !== "file") continue;
    try {
      const parsed = JSON.parse(norm.arguments);
      const operation = typeof parsed?.operation === "string" ? parsed.operation.toLowerCase() : "";
      if (!FILE_WRITE_OPERATIONS.has(operation)) continue;
      const pathRef = extractWidgetLibraryRef(parsed?.path);
      const destinationRef = extractWidgetLibraryRef(parsed?.destination);
      if (pathRef) refs.add(pathRef);
      if (destinationRef) refs.add(destinationRef);
    } catch {
      // Ignore malformed persisted args.
    }
  }
  return Array.from(refs);
}

interface Props {
  message: Message;
  botName?: string;
  /** Whether this message is "grouped" with the previous (same author, close in time) */
  isGrouped?: boolean;
  /** Called when user clicks a bot's avatar/name (passes sender_bot_id if available, else null) */
  onBotClick?: (senderBotId: string | null) => void;
  /** Full concatenated text for multi-segment bot turns (only set on the turn header) */
  fullTurnText?: string;
  /** Full grouped assistant response rows for copy/debug actions. */
  fullTurnMessages?: Message[];
  /** Channel id — used to look up the per-channel "compact tool results"
   *  preference and to thread sessionId-style auth into RichToolResult's
   *  lazy-fetch path. Optional for back-compat with non-channel call sites. */
  channelId?: string;
  /** When true, this is the newest bot message in the channel. Still used for
   *  widget-card collapse defaults, but not for persisted tool-row expansion. */
  isLatestBotMessage?: boolean;
  /** Mobile layout: avatar inlined with name header, content flows flush-left
   *  (no avatar-column indent) so the narrow viewport gets full width. */
  isMobile?: boolean;
  /** Constrained-container layout. Same "no avatar column, flush-left content"
   *  treatment as `isMobile` — for desktop dock / drawer mounts that still want
   *  the mobile-style bubble. Kept separate from `isMobile` so the latter can
   *  retain its "touch device" semantics elsewhere. */
  compact?: boolean;
  /** Thread summary for this message (if any). When set, a compact
   *  ``ThreadAnchor`` card renders beneath the bubble and the
   *  Reply-in-thread action opens the existing thread instead of spawning
   *  a new one. */
  threadSummary?: ThreadSummary | null;
  /** Click-thread handler — fires on both the anchor card and the
   *  hover-row "Reply in thread" button. Caller decides whether to
   *  spawn-new or open-existing based on ``threadSummary``. */
  onReplyInThread?: (messageId: string) => void;
  /** Gate on the Reply-in-thread hover action. Caller passes false inside
   *  thread / ephemeral views so the action doesn't spawn nested threads
   *  (UI-only guard — backend permits nesting). */
  canReplyInThread?: boolean;
  chatMode?: "default" | "terminal";
  /** Per-channel toggle from ``Channel.show_message_feedback``. Defaults
   *  to true to match the column default; pass false to suppress the
   *  thumbs-up/down affordance on this channel. */
  showMessageFeedback?: boolean;
}

// ---------------------------------------------------------------------------
// HistoricalThinking — collapsed reasoning block on persisted messages
// ---------------------------------------------------------------------------
function HistoricalThinking({ text, t, chatMode = "default" }: { text: string; t: ThemeTokens; chatMode?: "default" | "terminal" }) {
  const [expanded, setExpanded] = useState(false);
  const isTerminalMode = chatMode === "terminal";
  return (
    <div className="mb-2 mt-0.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wider opacity-70 hover:opacity-100"
        style={{ color: isTerminalMode ? t.textMuted : t.purpleMuted }}
      >
        <ChevronRight
          size={12}
          style={{
            transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 120ms",
          }}
        />
        <Brain size={12} />
        <span>Thinking</span>
      </button>
      {expanded && (
        <div
          className="pl-3 pt-1.5 pb-1.5 mt-1 text-[13px] italic whitespace-pre-wrap break-words"
          style={{
            borderLeft: `2px solid ${t.textDim}`,
            color: t.textMuted,
            lineHeight: 1.55,
            maxHeight: 320,
            overflowY: "auto",
          }}
        >
          {text}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble -- Slack-style flat layout
// ---------------------------------------------------------------------------

export const MessageBubble = memo(function MessageBubble({ message, botName, isGrouped, onBotClick, fullTurnText, fullTurnMessages, channelId, isLatestBotMessage, isMobile = false, compact: compactLayout = false, threadSummary = null, onReplyInThread, canReplyInThread = false, chatMode = "default", showMessageFeedback = true }: Props) {
  const t = useThemeTokens();
  const detectedMobile = useIsMobile();
  const effectiveMobile = isMobile || detectedMobile;
  const narrow = effectiveMobile || compactLayout;
  const isTerminalMode = chatMode === "terminal";
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // Add the inline widget to the channel's implicit dashboard (slug
  // `channel:<uuid>`). Hydrate the store to that slug first so the pin
  // lands in the right scope, then navigate to the dashboard in edit
  // mode with the new tile highlighted so the user sees where it landed
  // and can immediately position it.
  const handlePinWidget = useCallback(
    async (info: { widgetId: string; envelope: ToolResultEnvelope; toolName: string; channelId: string; botId: string | null }) => {
      const toolShort = info.toolName.includes("-") ? info.toolName.slice(info.toolName.indexOf("-") + 1) : info.toolName;
      const displayName = info.envelope.display_label || toolShort;

      const { useDashboardPinsStore } = await import("../../stores/dashboardPins");
      const slug = `channel:${info.channelId}`;
      const store = useDashboardPinsStore.getState();
      if (store.currentSlug !== slug) {
        await store.hydrate(slug);
      }
      try {
        const created = await useDashboardPinsStore.getState().pinWidget({
          source_kind: "channel",
          source_channel_id: info.channelId,
          source_bot_id: info.botId,
          tool_name: info.toolName,
          envelope: info.envelope,
          display_label: displayName,
        });
        navigate(
          `/widgets/channel/${info.channelId}?edit=true&highlight=${encodeURIComponent(created.id)}`,
        );
      } catch (err) {
        // Surface the server's detail (e.g. "Bot 'X' has no API permissions")
        // instead of the generic ApiError string. The bare console.error
        // leaves the user guessing which field the backend rejected.
        const { ApiError } = await import("../../api/client");
        const detail = err instanceof ApiError ? err.detail : null;
        const summary = detail ?? (err instanceof Error ? err.message : String(err));
        console.error("Failed to pin widget from chat:", summary, err);
        try {
          const { useToastStore } = await import("../../stores/toast");
          useToastStore.getState().push({
            kind: "error",
            message: `Pin failed: ${summary}`,
            durationMs: 6000,
          });
        } catch {
          // Toast store unavailable — console message above is enough.
        }
      }
    },
    [navigate],
  );
  const meta = message.metadata || {};
  // Extract text from content (handles JSON-array content blocks). Current
  // integrations emit clean content per the ingest contract; stripLegacyIngestPrefix
  // covers rows written before that refactor (remove after 2026-Q3).
  const rawText = extractDisplayText(message.content);
  const displayContent = stripLegacyIngestPrefix(rawText, meta.source as string | undefined);
  const { name: displayName, isCurrentUser, isMemberBot, sourceLabel } = resolveDisplay(message, botName);
  const isUser = isCurrentUser;
  const timestamp = formatTimeShort(message.created_at);
  const toolsUsed: string[] = (meta.tools_used as string[]) || [];
  const toolResults: (ToolResultEnvelope | undefined)[] | undefined = meta.tool_results as
    | (ToolResultEnvelope | undefined)[]
    | undefined;
  const richEnvelope: ToolResultEnvelope | undefined = meta.envelope as ToolResultEnvelope | undefined;
  const msgToolCalls: ToolCall[] | undefined = message.tool_calls;
  const isFeedbackAnchor = useMemo(() => {
    if (!isFeedbackEligibleAssistantMessage(message)) return false;
    const anchor = [...(fullTurnMessages ?? [message])].reverse().find(isFeedbackEligibleAssistantMessage);
    return anchor?.id === message.id;
  }, [fullTurnMessages, message]);
  const feedbackControls = isFeedbackAnchor ? (
    <TurnFeedbackControls
      messageId={message.id}
      sessionId={message.session_id}
      feedback={message.feedback ?? EMPTY_FEEDBACK}
      hidden={!showMessageFeedback}
      variant="actionBar"
    />
  ) : undefined;
  const trigger = meta.trigger as string | undefined;
  const localStatus = meta.local_status as string | undefined;
  const turnCancelled = meta.turn_cancelled === true;
  const llmStatus = meta.llm_status as { retries?: number; fallback_model?: string; vision_fallback?: boolean } | undefined;
  const delegations = (meta.delegations as any[]) || [];
  const delegatedByDisplay = meta.delegated_by_display as string | undefined;
  const widgetLibraryInvalidations = useMemo(
    () => collectInvalidatedLibraryRefs(msgToolCalls),
    [msgToolCalls],
  );
  const triggerBadge = trigger === "workflow"
    ? { label: meta.workflow_name || "workflow", icon: "\u27f3", color: "#6366f1" }
    : trigger === "heartbeat"
    ? { label: "heartbeat", icon: "\ud83d\udc93", color: "#ec4899" }
    : trigger === "scheduled_task"
      ? { label: meta.task_title || "scheduled", icon: "\ud83d\udd01", color: "#8b5cf6" }
      : trigger === "delegation_callback"
        ? { label: meta.delegation_child_display || "delegation", icon: "\u21a9", color: "#8b5cf6" }
        : trigger === "callback"
          ? { label: "callback", icon: "\u21a9", color: "#8b5cf6" }
          : meta.is_heartbeat
            ? { label: "heartbeat", icon: "\ud83d\udc93", color: "#ec4899" }
            : null;

  if (meta.kind === "slash_command_result") {
    return <SlashCommandResultCard message={message} chatMode={chatMode} />;
  }

  // Message metadata carries the emitting bot as `sender_id: "bot:<id>"`
  // (stamped by persist_turn + finishTurn). Strip the prefix to get the bare
  // bot id that WidgetCard / RichToolResult need for pin + mint flows.
  const senderId = (meta.sender_id as string | undefined) ?? undefined;
  const senderBotId = senderId?.startsWith("bot:") ? senderId.slice(4) : undefined;
  const rawThinking = typeof meta.thinking === "string"
    ? meta.thinking
    : typeof meta.thinking_content === "string"
      ? meta.thinking_content
      : "";
  const thinkingText = rawThinking.trim();
  const persistedAssistantTurnBody = meta.assistant_turn_body as AssistantTurnBody | undefined;
  const legacyTranscriptEntries = meta.transcript_entries as AssistantTurnBody["items"] | undefined;
  const assistantTurnBody = useMemo(
    () =>
      message.role === "assistant"
        ? (
            persistedAssistantTurnBody
            ?? buildLegacyAssistantTurnBody({
              displayContent,
              transcriptEntries: legacyTranscriptEntries,
              toolCalls: msgToolCalls,
              rootEnvelope: richEnvelope,
            })
          )
        : null,
    [displayContent, legacyTranscriptEntries, message.role, msgToolCalls, persistedAssistantTurnBody, richEnvelope],
  );
  const orderedTurnBodyItems = useMemo(
    () =>
      assistantTurnBody
        ? buildAssistantTurnBodyItems({
            assistantTurnBody,
            toolCalls: msgToolCalls ?? [],
            toolResults,
            rootEnvelope: richEnvelope,
            renderMode: chatMode,
          })
        : [],
    [assistantTurnBody, chatMode, msgToolCalls, richEnvelope, toolResults],
  );
  const orderedWidgetItems = useMemo(
    () => orderedTurnBodyItems.filter((item): item is Extract<OrderedTurnBodyItem, { kind: "widget" }> => item.kind === "widget"),
    [orderedTurnBodyItems],
  );

  // Broadcast envelopes when new tool results arrive in messages.
  // Seeds the shared envelope map so pinned widgets and inline widgets stay in sync.
  const broadcastRef = useRef<string | null>(null);
  const broadcastEnvelope = usePinnedWidgetsStore((s) => s.broadcastEnvelope);
  useEffect(() => {
    if (!channelId || !orderedWidgetItems.length) return;
    // Key by message id to only fire once per message
    const key = message.id;
    if (broadcastRef.current === key) return;
    broadcastRef.current = key;
    for (const item of orderedWidgetItems) {
      broadcastEnvelope(channelId, item.widget.toolName, item.widget.envelope, {
        kind: "tool_result",
      });
    }
  }, [broadcastEnvelope, channelId, message.id, orderedWidgetItems]);

  const invalidatedWidgetLibrariesRef = useRef<string | null>(null);
  useEffect(() => {
    if (!widgetLibraryInvalidations.length) return;
    if (invalidatedWidgetLibrariesRef.current === message.id) return;
    invalidatedWidgetLibrariesRef.current = message.id;
    for (const ref of widgetLibraryInvalidations) {
      queryClient.invalidateQueries({
        predicate: (query) => {
          const key = query.queryKey;
          return Array.isArray(key)
            && key[0] === "interactive-html-widget-content"
            && key[1] === "library"
            && key[4] === ref;
        },
      });
    }
  }, [message.id, queryClient, widgetLibraryInvalidations]);

  // Collapsed non-dispatched heartbeat messages
  const isNonDispatchedHeartbeat = (trigger === "heartbeat" || meta.is_heartbeat) && meta.dispatched === false;
  if (isNonDispatchedHeartbeat) {
    return (
      <CollapsedHeartbeat
        displayContent={displayContent}
        timestamp={timestamp}
        toolsUsed={toolsUsed}
        toolCalls={msgToolCalls}
        t={t}
      />
    );
  }

  // Collapsed workflow lifecycle messages
  const isWorkflowMessage = trigger === "workflow";
  if (isWorkflowMessage) {
    return (
      <CollapsedWorkflow
        message={message}
        displayContent={displayContent}
        timestamp={timestamp}
        t={t}
      />
    );
  }

  const hasAssistantTurnBody = message.role === "assistant" && orderedTurnBodyItems.length > 0;

  const messageContent = (
    <>
      {thinkingText.length > 0 && <HistoricalThinking text={thinkingText} t={t} chatMode={chatMode} />}
      {hasAssistantTurnBody ? (
        <OrderedTranscript
          items={orderedTurnBodyItems}
          t={t}
          chatMode={chatMode}
          sessionId={message.session_id}
          channelId={channelId}
          botId={senderBotId}
          isLatestBotMessage={isLatestBotMessage}
          onPin={handlePinWidget}
          sourceLabel={(meta.source as string) || "event"}
        />
      ) : displayContent.length > 0 ? (
        <MarkdownContent text={displayContent} t={t} chatMode={chatMode} channelId={channelId} />
      ) : null}
      {((message.attachments && message.attachments.length > 0)
        || Array.isArray(meta.local_attachments)
        || Array.isArray(meta.workspace_uploads)) && (
        <AttachmentImages
          attachments={message.attachments ?? []}
          localAttachments={Array.isArray(meta.local_attachments) ? meta.local_attachments : undefined}
          workspaceUploads={Array.isArray(meta.workspace_uploads) ? meta.workspace_uploads : undefined}
          channelId={channelId}
          chatMode={chatMode}
        />
      )}
      {delegations.length > 0 && <DelegationCard delegations={delegations} t={t} />}
      {turnCancelled && (
        <div
          className="mt-1 text-xs"
          style={{
            color: t.textDim,
            fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
          }}
        >
          Stopped by user
        </div>
      )}
    </>
  );

  const threadAnchorEl = threadSummary && onReplyInThread ? (
    <ThreadAnchor
      summary={threadSummary}
      onOpen={() => onReplyInThread(message.id)}
    />
  ) : null;
  const terminalUserBlock = isTerminalMode && message.role === "user";
  const isHarnessQuestion = isHarnessQuestionMessage(message);

  if (isHarnessQuestion) {
    return (
      <>
        <div
          className="msg-hover"
          style={{
            paddingLeft: isTerminalMode ? 0 : narrow ? CHAT_ROW_NARROW_X_PADDING : CHAT_ROW_X_PADDING,
            paddingRight: isTerminalMode ? 0 : narrow ? CHAT_ROW_NARROW_X_PADDING : CHAT_ROW_X_PADDING,
            paddingTop: isTerminalMode ? 9 : 14,
            paddingBottom: isTerminalMode ? 9 : 8,
            borderRadius: 4,
            fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
          }}
        >
          {messageContent}
        </div>
        {threadAnchorEl}
      </>
    );
  }

  // Grouped message -- compact, no avatar or name header.
  // Mobile: no left indent (flush-left like non-grouped).
  if (isGrouped) {
    const groupedMessageContent = terminalUserBlock ? (
      <div
        style={{
          background: t.overlayLight,
          padding: "9px 11px 10px",
          fontFamily: TERMINAL_FONT_STACK,
        }}
      >
        {messageContent}
      </div>
    ) : messageContent;
    return (
      <>
        <div
          className="msg-hover"
          style={{
            paddingLeft: isTerminalMode ? CHAT_ROW_TERMINAL_X_PADDING : narrow ? CHAT_ROW_NARROW_X_PADDING : CHAT_ROW_CONTENT_INDENT,
            paddingRight: isTerminalMode ? CHAT_ROW_TERMINAL_X_PADDING : narrow ? CHAT_ROW_NARROW_X_PADDING : CHAT_ROW_X_PADDING,
            paddingTop: isTerminalMode ? 3 : 1,
            paddingBottom: isTerminalMode ? 3 : 1,
            borderRadius: 4,
          }}
        >
          {groupedMessageContent}
          {(displayContent.length > 0 || !!fullTurnMessages?.length || feedbackControls) && <MessageActions text={displayContent} fullTurnText={fullTurnText} fullTurnMessages={fullTurnMessages} correlationId={message.correlation_id} feedbackControls={feedbackControls} t={t} canReplyInThread={canReplyInThread && !!onReplyInThread} onReplyInThread={onReplyInThread ? () => onReplyInThread(message.id) : undefined} />}
        </div>
        {threadAnchorEl}
      </>
    );
  }

  // Click handler for bot avatar/name — passes sender_bot_id from metadata when available
  const handleBotClick = !isUser && onBotClick
    ? () => onBotClick((meta.sender_bot_id as string) || null)
    : undefined;

  // Full message -- avatar + name header + content.
  // Mobile: avatar is inlined in the name header (small badge), content flows
  // flush-left with no avatar-column indent — reclaims the full chat width.
  return (
    <>
    <div
      className="msg-hover"
      style={{
        display: "flex",
        flexDirection: narrow ? "column" : "row",
        gap: narrow ? 0 : CHAT_ROW_GAP,
        paddingLeft: isTerminalMode ? CHAT_ROW_TERMINAL_X_PADDING : narrow ? CHAT_ROW_NARROW_X_PADDING : CHAT_ROW_X_PADDING,
        paddingRight: narrow ? CHAT_ROW_NARROW_X_PADDING : CHAT_ROW_X_PADDING,
        paddingTop: isTerminalMode ? 9 : 14,
        paddingBottom: isTerminalMode ? 9 : 6,
        borderRadius: 4,
      }}
    >
      {/* Avatar — full-width layouts only. Narrow layouts (mobile, dock, drawer)
          drop the avatar entirely; the colored name carries identity and the
          layout feels better balanced without a tiny badge sitting off to the
          left of the header. */}
      {!narrow && !isTerminalMode && (
        <div style={{ paddingTop: 2 }}>
          <Avatar name={displayName} isUser={isUser} onClick={handleBotClick} />
        </div>
      )}

      {/* Content */}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          background: terminalUserBlock ? t.overlayLight : undefined,
          padding: terminalUserBlock ? "9px 11px 10px" : undefined,
        }}
      >
        {/* Name + timestamp header */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: terminalUserBlock ? 6 : 2, flexWrap: "wrap" }}>
          <span
            onClick={handleBotClick}
            className={handleBotClick ? "bot-name-link" : undefined}
            style={{
              fontSize: isTerminalMode ? 12 : 15,
              fontWeight: isTerminalMode ? 600 : 700,
              color: isTerminalMode ? t.textMuted : isUser ? t.text : avatarColor(displayName),
              cursor: handleBotClick ? "pointer" : undefined,
              borderBottom: handleBotClick ? "1px solid transparent" : undefined,
              transition: handleBotClick ? "border-color 0.15s" : undefined,
              fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
              textTransform: isTerminalMode ? "lowercase" : undefined,
            }}
            onMouseEnter={handleBotClick ? (e) => { (e.currentTarget as HTMLSpanElement).style.borderBottomColor = isTerminalMode ? t.textMuted : avatarColor(displayName); } : undefined}
            onMouseLeave={handleBotClick ? (e) => { (e.currentTarget as HTMLSpanElement).style.borderBottomColor = "transparent"; } : undefined}
          >
            {isTerminalMode ? `${terminalTranscriptRole(message)}:${displayName}` : displayName}
          </span>
          <TimestampActions
            timestamp={timestamp}
            text={displayContent}
            fullTurnText={fullTurnText}
            fullTurnMessages={fullTurnMessages}
            correlationId={message.correlation_id}
            onBotClick={handleBotClick}
            canReplyInThread={canReplyInThread && !!onReplyInThread}
            onReplyInThread={onReplyInThread ? () => onReplyInThread(message.id) : undefined}
            t={t}
          />
          {isMemberBot && (
            <span style={{
              fontSize: 10,
              fontWeight: 600,
              color: isTerminalMode ? t.textMuted : "#06b6d4",
              background: isTerminalMode ? "transparent" : "#06b6d415",
              border: isTerminalMode ? `1px solid ${t.overlayBorder}` : "1px solid #06b6d430",
              borderRadius: 10,
              padding: "1px 6px",
              letterSpacing: 0.3,
            }}>
              member
            </span>
          )}
          {sourceLabel && (
            <span style={{ fontSize: 11, color: t.textMuted, fontStyle: "italic" }}>
              {sourceLabel}
            </span>
          )}
          {isUser && localStatus === "queued" && (
            <span style={{
              fontSize: 10,
              fontWeight: 600,
              color: t.warning,
              background: `${t.warning}18`,
              border: `1px solid ${t.warning}30`,
              borderRadius: 10,
              padding: "1px 6px",
              letterSpacing: 0.3,
            }}>
              queued
            </span>
          )}
          {delegatedByDisplay && (
            <span style={{ fontSize: 11, color: isTerminalMode ? t.textMuted : "#8b5cf6", fontStyle: "italic" }}>
              delegated by {delegatedByDisplay}
            </span>
          )}
          {triggerBadge && (
            <span
              style={{
                display: "inline-flex", flexDirection: "row",
                alignItems: "center",
                gap: 3,
                fontSize: 10,
                fontWeight: 600,
                color: isTerminalMode ? t.textMuted : triggerBadge.color,
                background: isTerminalMode ? "transparent" : `${triggerBadge.color}18`,
                border: isTerminalMode ? `1px solid ${t.overlayBorder}` : `1px solid ${triggerBadge.color}30`,
                borderRadius: 10,
                padding: "1px 7px",
                letterSpacing: 0.3,
              }}
            >
              <span style={{ fontSize: 11 }}>{triggerBadge.icon}</span>
              {triggerBadge.label}
            </span>
          )}
          {llmStatus && (
            <>
              {llmStatus.fallback_model && (
                <span className="inline-flex flex-row items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-semibold"
                  style={{ color: t.warning, background: `${t.warning}18`, border: `1px solid ${t.warning}30` }}>
                  {"⇄"} fallback: {llmStatus.fallback_model}
                </span>
              )}
              {(llmStatus.retries ?? 0) > 0 && (
                <span className="inline-flex flex-row items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-semibold"
                  style={{ color: t.warning, background: `${t.warning}18`, border: `1px solid ${t.warning}30` }}>
                  {"↻"} {llmStatus.retries} {llmStatus.retries === 1 ? "retry" : "retries"}
                </span>
              )}
              {llmStatus.vision_fallback && (
                <span className="inline-flex flex-row items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-semibold"
                  style={{ color: t.warning, background: `${t.warning}18`, border: `1px solid ${t.warning}30` }}>
                  {"🖼"} image described
                </span>
              )}
            </>
          )}
        </div>

        {/* Message content */}
        <div style={{ fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined }}>
          {messageContent}
        </div>
      </div>

      {(displayContent.length > 0 || !!fullTurnMessages?.length || feedbackControls) && <MessageActions text={displayContent} fullTurnText={fullTurnText} fullTurnMessages={fullTurnMessages} correlationId={message.correlation_id} feedbackControls={feedbackControls} t={t} canReplyInThread={canReplyInThread && !!onReplyInThread} onReplyInThread={onReplyInThread ? () => onReplyInThread(message.id) : undefined} />}
    </div>
    {threadAnchorEl}
    </>
  );
});
