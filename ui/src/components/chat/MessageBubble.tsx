import { memo, useMemo } from "react";
import { useThemeTokens, type ThemeTokens } from "../../theme/tokens";
import { formatTimeShort } from "../../utils/time";
import { DelegationCard } from "./DelegationCard";
import { MarkdownContent } from "./MarkdownContent";
import { AttachmentImages } from "./AttachmentDisplay";
import { ToolBadges } from "./ToolBadges";
import { WidgetCard } from "./WidgetCard";
import { MessageActions, Avatar } from "./MessageActions";
import { CollapsedHeartbeat, CollapsedWorkflow } from "./CollapsedMessages";
import { RichToolResult } from "./RichToolResult";
import { extractDisplayText, parseSlackPrefix, stripBBPrefix, resolveDisplay, avatarColor } from "./messageUtils";
import { normalizeToolCall } from "../../types/api";
import { useToolResultCompact } from "../../stores/toolResultPref";
import type { Message, ToolCall, ToolResultEnvelope } from "../../types/api";

type AutoInjectedSkillMeta = { skillId?: string; skill_id?: string; skillName?: string; skill_name?: string; similarity?: number };

/** Compact inline skill badges for persisted messages */
function SkillBadges({ skills, t }: { skills: AutoInjectedSkillMeta[]; t: ThemeTokens }) {
  if (!skills.length) return null;
  return (
    <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 4, marginBottom: 2 }}>
      {skills.map((s, i) => {
        const name = s.skillName ?? s.skill_name ?? "skill";
        const sim = s.similarity ?? 0;
        return (
          <div
            key={s.skillId ?? s.skill_id ?? i}
            style={{
              display: "inline-flex", flexDirection: "row",
              alignItems: "center",
              gap: 4,
              padding: "1px 7px 1px 5px",
              borderRadius: 10,
              backgroundColor: t.purpleSubtle,
              border: `1px solid ${t.purpleBorder}`,
            }}
          >
            <div style={{
              width: 4,
              height: 4,
              borderRadius: "50%",
              backgroundColor: t.purple,
              opacity: 0.3 + sim * 0.7,
              flexShrink: 0,
            }} />
            <span style={{ fontSize: 10, color: t.textMuted, fontWeight: 500 }}>
              {name}
            </span>
          </div>
        );
      })}
    </div>
  );
}

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
}

// ---------------------------------------------------------------------------
// MessageBubble -- Slack-style flat layout
// ---------------------------------------------------------------------------

export const MessageBubble = memo(function MessageBubble({ message, botName, isGrouped, onBotClick, fullTurnText, channelId, isLatestBotMessage }: Props) {
  const t = useThemeTokens();
  const [compact] = useToolResultCompact(channelId ?? "");
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
  const toolResults: ToolResultEnvelope[] | undefined = meta.tool_results as ToolResultEnvelope[] | undefined;
  const richEnvelope: ToolResultEnvelope | undefined = meta.envelope as ToolResultEnvelope | undefined;
  const msgToolCalls: ToolCall[] | undefined = message.tool_calls;
  const trigger = meta.trigger as string | undefined;
  const autoInjectedSkills = (meta.auto_injected_skills as AutoInjectedSkillMeta[]) || [];
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

  // Partition tool results: extract inline widget envelopes for WidgetCard rendering
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

    for (let i = 0; i < count; i++) {
      const env = results?.[i];
      const call = calls[i];
      const name = call ? normalizeToolCall(call).name : names[i];

      if (
        env &&
        env.display === "inline" &&
        env.content_type === "application/vnd.spindrel.components+json"
      ) {
        inlineWidgets.push({ envelope: env, toolName: name ?? "", recordId: env.record_id ?? undefined });
      } else {
        if (call) remainingToolCalls.push(call);
        else if (names[i]) remainingToolNames.push(names[i]);
        remainingToolResults.push(env);
      }
    }

    return { inlineWidgets, remainingToolNames, remainingToolCalls, remainingToolResults };
  }, [msgToolCalls, toolsUsed, toolResults]);

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

  const senderBotId = (meta.sender_bot_id as string) ?? undefined;

  const messageContent = (
    <>
      {richEnvelope ? (
        <RichToolResult envelope={richEnvelope} sessionId={message.session_id} channelId={channelId} botId={senderBotId} t={t} />
      ) : displayContent.length > 0 ? (
        <MarkdownContent text={displayContent} t={t} />
      ) : null}
      {message.attachments && message.attachments.length > 0 && (
        <AttachmentImages attachments={message.attachments} t={t} />
      )}
      {autoInjectedSkills.length > 0 && <SkillBadges skills={autoInjectedSkills} t={t} />}
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

  // Grouped message -- compact, no avatar or name header
  if (isGrouped) {
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
        {displayContent.length > 0 && <MessageActions text={displayContent} fullTurnText={fullTurnText} correlationId={message.correlation_id} t={t} />}
      </div>
    );
  }

  // Click handler for bot avatar/name — passes sender_bot_id from metadata when available
  const handleBotClick = !isUser && onBotClick
    ? () => onBotClick((meta.sender_bot_id as string) || null)
    : undefined;

  // Full message -- avatar + name header + content
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
      {/* Avatar */}
      <div style={{ paddingTop: 2 }}>
        <Avatar name={displayName} isUser={isUser} onClick={handleBotClick} />
      </div>

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
          <span style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase" as const, letterSpacing: 0.5 }}>
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

      {displayContent.length > 0 && <MessageActions text={displayContent} fullTurnText={fullTurnText} correlationId={message.correlation_id} t={t} />}
    </div>
  );
});
