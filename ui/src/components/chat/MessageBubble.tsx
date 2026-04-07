import { memo } from "react";
import { View, Text, Platform } from "react-native";
import { useThemeTokens } from "../../theme/tokens";
import { formatTimeShort } from "../../utils/time";
import { DelegationCard } from "./DelegationCard";
import { MarkdownContent } from "./MarkdownContent";
import { AttachmentImages } from "./AttachmentDisplay";
import { ToolBadges } from "./ToolBadges";
import { MessageActions, Avatar } from "./MessageActions";
import { CollapsedHeartbeat, CollapsedWorkflow } from "./CollapsedMessages";
import { extractDisplayText, parseSlackPrefix, stripBBPrefix, resolveDisplay, avatarColor } from "./messageUtils";
import type { Message, ToolCall } from "../../types/api";

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
}

// ---------------------------------------------------------------------------
// MessageBubble -- Slack-style flat layout
// ---------------------------------------------------------------------------

export const MessageBubble = memo(function MessageBubble({ message, botName, isGrouped, onBotClick }: Props) {
  const isWeb = Platform.OS === "web";
  const t = useThemeTokens();
  const meta = message.metadata || {};
  // Extract text from content (handles JSON-array content blocks) then strip integration prefixes
  const rawText = extractDisplayText(message.content);
  const { slackUserId, cleaned: afterSlack } = parseSlackPrefix(rawText);
  const { name: displayName, isCurrentUser, isSlack, isMemberBot, sourceLabel } = resolveDisplay(message, botName, slackUserId);
  // Strip BB sender prefix from display when metadata provides sender info.
  // Use strict === false to avoid stripping legacy messages (where is_from_me is undefined).
  const displayContent = meta.source === "bluebubbles" && meta.is_from_me === false ? stripBBPrefix(afterSlack) : afterSlack;
  const isUser = isCurrentUser;
  const timestamp = formatTimeShort(message.created_at);
  const toolsUsed: string[] = (meta.tools_used as string[]) || [];
  const msgToolCalls: ToolCall[] | undefined = message.tool_calls;
  const trigger = meta.trigger as string | undefined;
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

  const messageContent = isWeb ? (
    <>
      {displayContent.length > 0 && (
        <MarkdownContent text={displayContent} t={t} />
      )}
      {message.attachments && message.attachments.length > 0 && (
        <AttachmentImages attachments={message.attachments} t={t} />
      )}
      {toolsUsed.length > 0 && <ToolBadges toolNames={toolsUsed} toolCalls={msgToolCalls} t={t} />}
      {delegations.length > 0 && <DelegationCard delegations={delegations} t={t} />}
    </>
  ) : (
    <>
      <Text
        className="text-[15px] leading-relaxed"
        style={{ color: t.contentText }}
        selectable
      >
        {displayContent}
      </Text>
      {toolsUsed.length > 0 && <ToolBadges toolNames={toolsUsed} toolCalls={msgToolCalls} t={t} />}
      {delegations.length > 0 && <DelegationCard delegations={delegations} t={t} />}
    </>
  );

  // Grouped message -- compact, no avatar or name header
  if (isGrouped) {
    if (isWeb) {
      return (
        <div
          className="msg-hover"
          style={{
            paddingLeft: 68,
            paddingRight: 20,
            paddingTop: 1,
            paddingBottom: 1,
            borderRadius: 4,
          }}
        >
          {messageContent}
          {displayContent.length > 0 && <MessageActions text={displayContent} correlationId={message.correlation_id} t={t} />}
        </div>
      );
    }
    return (
      <View
        style={{
          paddingLeft: 68,
          paddingRight: 20,
          paddingTop: 1,
          paddingBottom: 1,
        }}
      >
        {messageContent}
      </View>
    );
  }

  // Click handler for bot avatar/name — passes sender_bot_id from metadata when available
  const handleBotClick = !isUser && onBotClick
    ? () => onBotClick((meta.sender_bot_id as string) || null)
    : undefined;

  // Full message -- avatar + name header + content
  const webInner = isWeb ? (
    <>
      {/* Avatar */}
      <div style={{ paddingTop: 2 }}>
        <Avatar name={displayName} isUser={isUser} onClick={handleBotClick} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Name + timestamp header */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2, userSelect: "none" }}>
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
          <span style={{ fontSize: 12, color: t.textDim }}>
            {timestamp}
          </span>
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
                display: "inline-flex",
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
        </div>

        {/* Message content */}
        {messageContent}
      </div>
    </>
  ) : null;

  const nativeInner = !isWeb ? (
    <>
      {/* Avatar */}
      <View style={{ paddingTop: 2 }}>
        <Avatar name={displayName} isUser={isUser} />
      </View>

      {/* Content */}
      <View style={{ flex: 1, minWidth: 0 }}>
        {/* Name + timestamp header */}
        <View className="select-none" style={{ flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <Text
            style={{
              fontSize: 15,
              fontWeight: "700",
              color: isUser ? t.text : avatarColor(displayName),
            }}
          >
            {displayName}
          </Text>
          <Text style={{ fontSize: 12, color: t.textDim }}>
            {timestamp}
          </Text>
          {sourceLabel && (
            <Text style={{ fontSize: 11, color: t.textMuted, fontStyle: "italic" }}>
              {sourceLabel}
            </Text>
          )}
          {delegatedByDisplay && (
            <Text style={{ fontSize: 11, color: "#8b5cf6", fontStyle: "italic" }}>
              delegated by {delegatedByDisplay}
            </Text>
          )}
          {triggerBadge && (
            <Text style={{ fontSize: 10, color: triggerBadge.color, fontWeight: "600" }}>
              {triggerBadge.icon} {triggerBadge.label}
            </Text>
          )}
        </View>

        {/* Message content */}
        {messageContent}
      </View>
    </>
  ) : null;

  if (isWeb) {
    return (
      <div
        className="msg-hover"
        style={{
          display: "flex",
          flexDirection: "row",
          gap: 12,
          paddingLeft: 20,
          paddingRight: 20,
          paddingTop: 8,
          paddingBottom: 4,
          borderRadius: 4,
        }}
      >
        {webInner}
        {displayContent.length > 0 && <MessageActions text={displayContent} correlationId={message.correlation_id} t={t} />}
      </div>
    );
  }

  return (
    <View
      style={{
        flexDirection: "row",
        gap: 12,
        paddingHorizontal: 20,
        paddingTop: 8,
        paddingBottom: 4,
      }}
    >
      {nativeInner}
    </View>
  );
});
