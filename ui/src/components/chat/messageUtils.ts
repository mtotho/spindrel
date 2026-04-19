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
// Legacy ingest-prefix stripping (historic rows only — remove after 2026-Q3)
// ---------------------------------------------------------------------------
// Current integrations emit clean content per the ingest contract
// (docs/integrations/message-ingest-contract.md). Rows written before the
// refactor may still carry `[Slack channel:... user:...]`, `[Discord
// channel:... user:...]`, or `[Name]:` prefixes — this helper peels them off
// for display so historic rows don't look corrupt next to fresh ones.
const LEGACY_SLACK_PREFIX_RE = /^\[Slack channel:\S+ user:[^\]]+\]\s*/;
const LEGACY_DISCORD_PREFIX_RE = /^\[Discord channel:\S+ user:[^\]]+\]\s*/;
const LEGACY_NAME_PREFIX_RE = /^\[[^\]]+\]:\s*/;

/**
 * Strip a legacy integration-source prefix from persisted content.
 * TODO: remove after 2026-Q3 once prefixed rows have aged out.
 */
export function stripLegacyIngestPrefix(content: string, source: string | undefined | null): string {
  if (!content) return content;
  if (source === "slack") return content.replace(LEGACY_SLACK_PREFIX_RE, "");
  if (source === "discord") return content.replace(LEGACY_DISCORD_PREFIX_RE, "");
  if (source === "bluebubbles") return content.replace(LEGACY_NAME_PREFIX_RE, "");
  return content;
}

// ---------------------------------------------------------------------------
// Metadata-aware display name resolution
// ---------------------------------------------------------------------------

export interface DisplayInfo {
  name: string;
  isCurrentUser: boolean;
  isMemberBot: boolean;
  sourceLabel: string | null;
}

/** Pretty-print an integration source for the "via X" label. */
function formatSourceLabel(source: string): string {
  return `via ${source.charAt(0).toUpperCase()}${source.slice(1)}`;
}

export function resolveDisplay(message: Message, botName?: string): DisplayInfo {
  const meta = message.metadata || {};
  const base = { isMemberBot: false };

  // --- Assistant messages ---
  if (message.role === "assistant") {
    const isMemberBot = !!(meta.sender_display_name && botName && meta.sender_display_name !== botName);
    return { ...base, name: meta.sender_display_name || botName || "Bot", isCurrentUser: false, isMemberBot, sourceLabel: null };
  }

  // --- User messages from bots (cross-channel relay, etc.) ---
  if (meta.sender_type === "bot") {
    return { ...base, name: meta.sender_display_name || "Bot", isCurrentUser: false, sourceLabel: null };
  }

  // --- Integration messages (any source with metadata) ---
  // BlueBubbles "is_from_me" means the local user sent via iMessage
  if (meta.is_from_me === true) {
    return { ...base, name: "You", isCurrentUser: true, sourceLabel: meta.source ? formatSourceLabel(meta.source) : null };
  }

  // Any non-web integration with a source label: show sender name + "via Source"
  if (meta.source && meta.source !== "web") {
    const name = meta.sender_display_name || meta.source.charAt(0).toUpperCase() + meta.source.slice(1);
    return { ...base, name, isCurrentUser: false, sourceLabel: formatSourceLabel(meta.source) };
  }

  // Web with explicit sender name (e.g. authenticated user)
  if (meta.source === "web" && meta.sender_display_name) {
    return { ...base, name: meta.sender_display_name, isCurrentUser: true, sourceLabel: null };
  }

  return { ...base, name: "You", isCurrentUser: true, sourceLabel: null };
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
