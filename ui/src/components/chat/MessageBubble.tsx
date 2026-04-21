import { memo, useMemo, useCallback, useEffect, useRef } from "react";
import { useThemeTokens, type ThemeTokens } from "../../theme/tokens";
import { formatTimeShort } from "../../utils/time";
import { DelegationCard } from "./DelegationCard";
import { MarkdownContent } from "./MarkdownContent";
import { AttachmentImages } from "./AttachmentDisplay";
import { ToolBadges } from "./ToolBadges";
import { WidgetCard } from "./WidgetCard";
import { MessageActions, TimestampActions, Avatar } from "./MessageActions";
import { CollapsedHeartbeat, CollapsedWorkflow } from "./CollapsedMessages";
import { RichToolResult } from "./RichToolResult";
import { ThreadAnchor } from "./ThreadAnchor";
import { extractDisplayText, stripLegacyIngestPrefix, resolveDisplay, avatarColor } from "./messageUtils";
import { normalizeToolCall } from "../../types/api";
import { useToolResultCompact } from "../../stores/toolResultPref";
import { usePinnedWidgetsStore } from "../../stores/pinnedWidgets";
import { useUIStore } from "../../stores/ui";
import type { Message, ToolCall, ToolResultEnvelope } from "../../types/api";
import type { ThreadSummary } from "../../api/hooks/useThreads";

// Re-export for external consumers
export { extractDisplayText } from "./messageUtils";
export { MarkdownContent } from "./MarkdownContent";

interface Props {
  message: Message;
  botName?: string;
  /** Whether this message is "grouped" with the previous (same author, close in time) */
  isGrouped?: boolean;
  /** Called when user clicks a bot's avatar/name (passes sender_bot_id if available, else null) */
  onBotClick?: (senderBotId: string | null) => void;
  /** Full concatenated text for multi-segment bot turns (only set on the turn header) */
  fullTurnText?: string;
  /** Channel id — used to look up the per-channel "compact tool results"
   *  preference and to thread sessionId-style auth into RichToolResult's
   *  lazy-fetch path. Optional for back-compat with non-channel call sites. */
  channelId?: string;
  /** When true, this is the newest bot message in the channel — tool results
   *  auto-expand. Older messages render collapsed. */
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
}

// ---------------------------------------------------------------------------
// MessageBubble -- Slack-style flat layout
// ---------------------------------------------------------------------------

export const MessageBubble = memo(function MessageBubble({ message, botName, isGrouped, onBotClick, fullTurnText, channelId, isLatestBotMessage, isMobile = false, compact: compactLayout = false, threadSummary = null, onReplyInThread, canReplyInThread = false }: Props) {
  const t = useThemeTokens();
  const narrow = isMobile || compactLayout;
  const [compact] = useToolResultCompact(channelId ?? "");
  const setExplorerOpen = useUIStore((s) => s.setFileExplorerOpen);

  // Pin the inline widget to the channel's implicit dashboard (slug
  // `channel:<uuid>`). Hydrate the store to that slug first so the pin
  // lands in the right scope — the store re-hydrates lazily on navigation,
  // so from the chat view we may be looking at a different slug.
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
        await useDashboardPinsStore.getState().pinWidget({
          source_kind: "channel",
          source_channel_id: info.channelId,
          source_bot_id: info.botId,
          tool_name: info.toolName,
          envelope: info.envelope,
          display_label: displayName,
        });
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
      setExplorerOpen(true);
    },
    [setExplorerOpen],
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
  const toolResults: ToolResultEnvelope[] | undefined = meta.tool_results as ToolResultEnvelope[] | undefined;
  const richEnvelope: ToolResultEnvelope | undefined = meta.envelope as ToolResultEnvelope | undefined;
  const msgToolCalls: ToolCall[] | undefined = message.tool_calls;
  const trigger = meta.trigger as string | undefined;
  const llmStatus = meta.llm_status as { retries?: number; fallback_model?: string; vision_fallback?: boolean } | undefined;
  const delegations = (meta.delegations as any[]) || [];
  const delegatedByDisplay = meta.delegated_by_display as string | undefined;
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

  // Partition tool results: extract inline widget envelopes for WidgetCard rendering.
  // Widget tools are fully owned by WidgetCard — no badge or collapsed result shown.
  // (must be above early returns to satisfy rules of hooks)
  const { inlineWidgets, remainingToolNames, remainingToolCalls, remainingToolResults } = useMemo(() => {
    const inlineWidgets: { envelope: ToolResultEnvelope; toolName: string; recordId?: string }[] = [];
    const remainingToolNames: string[] = [];
    const remainingToolCalls: ToolCall[] = [];
    const remainingToolResults: (ToolResultEnvelope | undefined)[] = [];

    const calls = msgToolCalls ?? [];
    const names = toolsUsed;
    const results = toolResults;
    const count = Math.max(calls.length, names.length);

    // First pass: identify which indices are inline widgets
    const inlineIndices = new Set<number>();
    for (let i = 0; i < count; i++) {
      const env = results?.[i];
      if (
        env &&
        env.display === "inline" &&
        (env.content_type === "application/vnd.spindrel.components+json" ||
          env.content_type === "application/vnd.spindrel.html+interactive")
      ) {
        const call = calls[i];
        const name = call ? normalizeToolCall(call).name : names[i];
        inlineWidgets.push({ envelope: env, toolName: name ?? "", recordId: env.record_id ?? undefined });
        inlineIndices.add(i);
      }
    }

    // Build the set of inline widget tool names for dedup across misaligned arrays
    const inlineToolNames = new Set(inlineWidgets.map((w) => w.toolName));

    // Second pass: collect remaining (non-widget) entries, skipping any that were inlined
    for (let i = 0; i < count; i++) {
      if (inlineIndices.has(i)) continue;
      const call = calls[i];
      const name = call ? normalizeToolCall(call).name : names[i];
      // Skip if this tool name was already captured as an inline widget (dedup)
      if (name && inlineToolNames.has(name)) continue;
      const env = results?.[i];
      if (call) remainingToolCalls.push(call);
      else if (names[i]) remainingToolNames.push(names[i]);
      remainingToolResults.push(env);
    }

    return { inlineWidgets, remainingToolNames, remainingToolCalls, remainingToolResults };
  }, [msgToolCalls, toolsUsed, toolResults]);

  // Broadcast envelopes when new tool results arrive in messages.
  // Seeds the shared envelope map so pinned widgets and inline widgets stay in sync.
  const broadcastRef = useRef<string | null>(null);
  const broadcastEnvelope = usePinnedWidgetsStore((s) => s.broadcastEnvelope);
  useEffect(() => {
    if (!channelId || !inlineWidgets.length) return;
    // Key by message id to only fire once per message
    const key = message.id;
    if (broadcastRef.current === key) return;
    broadcastRef.current = key;
    for (const w of inlineWidgets) {
      broadcastEnvelope(channelId, w.toolName, w.envelope);
    }
  }, [channelId, message.id, inlineWidgets, broadcastEnvelope]);

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

  // Message metadata carries the emitting bot as `sender_id: "bot:<id>"`
  // (stamped by persist_turn + finishTurn). Strip the prefix to get the bare
  // bot id that WidgetCard / RichToolResult need for pin + mint flows.
  const senderId = (meta.sender_id as string | undefined) ?? undefined;
  const senderBotId = senderId?.startsWith("bot:") ? senderId.slice(4) : undefined;

  const messageContent = (
    <>
      {richEnvelope ? (
        <div className="rounded-lg border mt-1.5" style={{ borderColor: t.surfaceBorder, backgroundColor: t.surfaceRaised }}>
          <div className="px-3 pt-2 pb-0.5">
            <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: t.textDim }}>
              {(meta.source as string) || "event"}
            </span>
          </div>
          <div className="px-3 pb-2">
            <RichToolResult envelope={richEnvelope} sessionId={message.session_id} channelId={channelId} botId={senderBotId} t={t} />
          </div>
        </div>
      ) : displayContent.length > 0 ? (
        <MarkdownContent text={displayContent} t={t} />
      ) : null}
      {message.attachments && message.attachments.length > 0 && (
        <AttachmentImages attachments={message.attachments} />
      )}
      {/* Inline widget cards — rendered outside ToolBadges chrome */}
      {inlineWidgets.map((w, i) => (
        <WidgetCard
          key={w.recordId ?? i}
          envelope={w.envelope}
          toolName={w.toolName}
          sessionId={message.session_id}
          channelId={channelId}
          botId={senderBotId}
          widgetId={w.recordId}
          t={t}
          isLatestBotMessage={isLatestBotMessage}
          defaultCollapsed={i < inlineWidgets.length - 1 && inlineWidgets[i + 1].toolName === w.toolName}
          onPin={handlePinWidget}
        />
      ))}
      {/* Remaining tool badges for non-widget results */}
      {(remainingToolNames.length > 0 || remainingToolCalls.length > 0) && (
        <ToolBadges
          toolNames={remainingToolNames}
          toolCalls={remainingToolCalls}
          toolResults={remainingToolResults as ToolResultEnvelope[]}
          sessionId={message.session_id}
          channelId={channelId}
          botId={senderBotId}
          compact={compact}
          autoExpand={isLatestBotMessage}
          t={t}
        />
      )}
      {delegations.length > 0 && <DelegationCard delegations={delegations} t={t} />}
    </>
  );

  const threadAnchorEl = threadSummary && onReplyInThread ? (
    <ThreadAnchor
      summary={threadSummary}
      onOpen={() => onReplyInThread(message.id)}
    />
  ) : null;

  // Grouped message -- compact, no avatar or name header.
  // Mobile: no left indent (flush-left like non-grouped).
  if (isGrouped) {
    return (
      <>
        <div
          className="msg-hover"
          style={{
            paddingLeft: narrow ? 12 : 68,
            paddingRight: narrow ? 12 : 20,
            paddingTop: 1,
            paddingBottom: 1,
            borderRadius: 4,
          }}
        >
          {messageContent}
          {displayContent.length > 0 && <MessageActions text={displayContent} fullTurnText={fullTurnText} correlationId={message.correlation_id} t={t} canReplyInThread={canReplyInThread && !!onReplyInThread} onReplyInThread={onReplyInThread ? () => onReplyInThread(message.id) : undefined} />}
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
        gap: narrow ? 0 : 12,
        paddingLeft: narrow ? 12 : 20,
        paddingRight: narrow ? 12 : 20,
        paddingTop: 14,
        paddingBottom: 6,
        borderRadius: 4,
      }}
    >
      {/* Avatar — full-width layouts only. Narrow layouts (mobile, dock, drawer)
          drop the avatar entirely; the colored name carries identity and the
          layout feels better balanced without a tiny badge sitting off to the
          left of the header. */}
      {!narrow && (
        <div style={{ paddingTop: 2 }}>
          <Avatar name={displayName} isUser={isUser} onClick={handleBotClick} />
        </div>
      )}

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Name + timestamp header */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <span
            onClick={handleBotClick}
            className={handleBotClick ? "bot-name-link" : undefined}
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: isUser ? t.text : avatarColor(displayName),
              cursor: handleBotClick ? "pointer" : undefined,
              borderBottom: handleBotClick ? "1px solid transparent" : undefined,
              transition: handleBotClick ? "border-color 0.15s" : undefined,
            }}
            onMouseEnter={handleBotClick ? (e) => { (e.currentTarget as HTMLSpanElement).style.borderBottomColor = avatarColor(displayName); } : undefined}
            onMouseLeave={handleBotClick ? (e) => { (e.currentTarget as HTMLSpanElement).style.borderBottomColor = "transparent"; } : undefined}
          >
            {displayName}
          </span>
          <TimestampActions
            timestamp={timestamp}
            text={displayContent}
            fullTurnText={fullTurnText}
            correlationId={message.correlation_id}
            onBotClick={handleBotClick}
            t={t}
          />
          {isMemberBot && (
            <span style={{
              fontSize: 10,
              fontWeight: 600,
              color: "#06b6d4",
              background: "#06b6d415",
              border: "1px solid #06b6d430",
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
          {delegatedByDisplay && (
            <span style={{ fontSize: 11, color: "#8b5cf6", fontStyle: "italic" }}>
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
                color: triggerBadge.color,
                background: `${triggerBadge.color}18`,
                border: `1px solid ${triggerBadge.color}30`,
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
        {messageContent}
      </div>

      {displayContent.length > 0 && <MessageActions text={displayContent} fullTurnText={fullTurnText} correlationId={message.correlation_id} t={t} canReplyInThread={canReplyInThread && !!onReplyInThread} onReplyInThread={onReplyInThread ? () => onReplyInThread(message.id) : undefined} />}
    </div>
    {threadAnchorEl}
    </>
  );
});
