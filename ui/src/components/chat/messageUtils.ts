/**
 * Utility functions for message display: content extraction, display name
 * resolution, avatar color generation, and Slack prefix parsing.
 *
 * Extracted from MessageBubble.tsx to keep the main component focused on layout.
 */

import type { Message } from "../../types/api";

// ---------------------------------------------------------------------------
// Content extraction -- handles JSON-array content blocks
// ---------------------------------------------------------------------------

/**
 * Extract displayable text from message content.
 * Content may be a plain string or a JSON-serialized array of content blocks
 * (e.g. [{type:"text",text:"..."}, {type:"thinking",...}, {type:"tool_use",...}]).
 */
export function extractDisplayText(content: string | null | undefined): string {
  if (!content) return "";
  const trimmed = content.trim();
  if (!trimmed.startsWith("[")) return content;
  try {
    const blocks = JSON.parse(trimmed);
    if (!Array.isArray(blocks)) return content;
    const textParts: string[] = [];
    for (const block of blocks) {
      if (typeof block === "string") {
        textParts.push(block);
      } else if (block?.type === "text" && typeof block.text === "string") {
        textParts.push(block.text);
      }
      // Skip thinking, tool_use, image_url blocks -- not user-facing in message list
    }
    return textParts.join("\n\n");
  } catch {
    return content; // Not valid JSON -- render as-is
  }
}

// ---------------------------------------------------------------------------
// Metadata-aware display name resolution
// ---------------------------------------------------------------------------

const SLACK_PREFIX_RE = /^\[Slack channel:\S+ user:(\S+)\]\s*/;

/** Extract Slack user ID from content prefix (for legacy messages without metadata). */
export function parseSlackPrefix(content: string): { slackUserId: string | null; cleaned: string } {
  const m = SLACK_PREFIX_RE.exec(content);
  if (m) {
    return { slackUserId: m[1], cleaned: content.replace(SLACK_PREFIX_RE, "") };
  }
  return { slackUserId: null, cleaned: content };
}

const BB_PREFIX_RE = /^\[([^\]]+)\]:\s*/;

/** Strip BlueBubbles sender prefix from content when metadata provides sender info. */
export function stripBBPrefix(content: string): string {
  return content.replace(BB_PREFIX_RE, "");
}

export interface DisplayInfo {
  name: string;
  isCurrentUser: boolean;
  isSlack: boolean;
  isMemberBot: boolean;
  sourceLabel: string | null;
}

export function resolveDisplay(
  message: Message,
  botName?: string,
  contentSlackUserId?: string | null,
): DisplayInfo {
  const meta = message.metadata || {};
  if (message.role === "assistant") {
    // Detect member bot: has sender_display_name that differs from primary botName
    const isMemberBot = !!(meta.sender_display_name && botName && meta.sender_display_name !== botName);
    return { name: meta.sender_display_name || botName || "Bot", isCurrentUser: false, isSlack: false, isMemberBot, sourceLabel: null };
  }
  // User messages with metadata
  if (meta.sender_type === "bot") {
    return { name: meta.sender_display_name || "Bot", isCurrentUser: false, isSlack: false, isMemberBot: false, sourceLabel: null };
  }
  if (meta.source === "slack") {
    const slackId = (meta.sender_id || "").replace("slack:", "");
    return { name: meta.sender_display_name || `Slack:${slackId}`, isCurrentUser: false, isSlack: true, isMemberBot: false, sourceLabel: "via Slack" };
  }
  if (meta.source === "bluebubbles" && typeof meta.is_from_me === "boolean") {
    // Only enter BB display branch when new metadata format is present.
    // Legacy messages (without is_from_me) fall through to default "You".
    // Sender name comes from binding display_name (user-chosen) or handle contact info.
    // Source label just says "via BlueBubbles" since the sender name already identifies the chat.
    if (meta.is_from_me) {
      return { name: "You", isCurrentUser: true, isSlack: false, isMemberBot: false, sourceLabel: "via BlueBubbles" };
    }
    const senderName = meta.sender_display_name as string | undefined;
    return { name: senderName || "Unknown", isCurrentUser: false, isSlack: false, isMemberBot: false, sourceLabel: "via BlueBubbles" };
  }
  if (meta.source === "github") {
    return { name: meta.sender_display_name || "GitHub", isCurrentUser: false, isSlack: false, isMemberBot: false, sourceLabel: "via GitHub" };
  }
  if (meta.source === "web" && meta.sender_display_name) {
    return { name: meta.sender_display_name, isCurrentUser: true, isSlack: false, isMemberBot: false, sourceLabel: null };
  }
  // Legacy fallback: detect Slack prefix in content
  if (contentSlackUserId) {
    return { name: meta.sender_display_name || `Slack:${contentSlackUserId}`, isCurrentUser: false, isSlack: true, isMemberBot: false, sourceLabel: "via Slack" };
  }
  return { name: "You", isCurrentUser: true, isSlack: false, isMemberBot: false, sourceLabel: null };
}

// Deterministic color from string hash
export function avatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#06b6d4", "#ef4444", "#e879f9",
  ];
  return colors[Math.abs(hash) % colors.length];
}
