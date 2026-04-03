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

export function resolveDisplay(
  message: Message,
  botName?: string,
  contentSlackUserId?: string | null,
): { name: string; isCurrentUser: boolean; isSlack: boolean } {
  const meta = message.metadata || {};
  if (message.role === "assistant") {
    return { name: meta.sender_display_name || botName || "Bot", isCurrentUser: false, isSlack: false };
  }
  // User messages with metadata
  if (meta.sender_type === "bot") {
    return { name: meta.sender_display_name || "Bot", isCurrentUser: false, isSlack: false };
  }
  if (meta.source === "slack") {
    const slackId = (meta.sender_id || "").replace("slack:", "");
    return { name: meta.sender_display_name || `Slack:${slackId}`, isCurrentUser: false, isSlack: true };
  }
  if (meta.source === "web" && meta.sender_display_name) {
    return { name: meta.sender_display_name, isCurrentUser: true, isSlack: false };
  }
  // Legacy fallback: detect Slack prefix in content
  if (contentSlackUserId) {
    return { name: meta.sender_display_name || `Slack:${contentSlackUserId}`, isCurrentUser: false, isSlack: true };
  }
  return { name: "You", isCurrentUser: true, isSlack: false };
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
