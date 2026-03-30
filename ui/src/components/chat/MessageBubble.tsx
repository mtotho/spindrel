import { useState } from "react";
import { View, Text, Platform } from "react-native";
import { Wrench, ChevronRight, ChevronDown } from "lucide-react";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { useThemeTokens } from "../../theme/tokens";
import { formatTimeShort } from "../../utils/time";
import { formatToolArgs } from "./toolCallUtils";
import { DelegationCard } from "./DelegationCard";
import type { Message, AttachmentBrief, ToolCall } from "../../types/api";
import { normalizeToolCall } from "../../types/api";

interface Props {
  message: Message;
  botName?: string;
  /** Whether this message is "grouped" with the previous (same author, close in time) */
  isGrouped?: boolean;
}

// ---------------------------------------------------------------------------
// Content extraction — handles JSON-array content blocks
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
      // Skip thinking, tool_use, image_url blocks — not user-facing in message list
    }
    return textParts.join("\n\n");
  } catch {
    return content; // Not valid JSON — render as-is
  }
}

// ---------------------------------------------------------------------------
// Metadata-aware display name resolution
// ---------------------------------------------------------------------------

const SLACK_PREFIX_RE = /^\[Slack channel:\S+ user:(\S+)\]\s*/;

/** Extract Slack user ID from content prefix (for legacy messages without metadata). */
function parseSlackPrefix(content: string): { slackUserId: string | null; cleaned: string } {
  const m = SLACK_PREFIX_RE.exec(content);
  if (m) {
    return { slackUserId: m[1], cleaned: content.replace(SLACK_PREFIX_RE, "") };
  }
  return { slackUserId: null, cleaned: content };
}

function resolveDisplay(
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
function avatarColor(name: string): string {
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

function Avatar({ name, isUser }: { name: string; isUser: boolean }) {
  const bg = isUser ? "#4b5563" : avatarColor(name);
  const letter = isUser ? "U" : (name[0] || "B").toUpperCase();
  return (
    <View
      style={{
        width: 36,
        height: 36,
        borderRadius: 6,
        backgroundColor: bg,
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <Text style={{ color: "#fff", fontSize: 14, fontWeight: "700" }}>
        {letter}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Markdown renderer (web only, returns React elements)
// ---------------------------------------------------------------------------

type InlineNode = string | { tag: string; content: string; href?: string };

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  const pattern =
    /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\_[^_]+\_)|(~[^~]+~)|(\[([^\]]+)\]\(([^)]+)\))|(<(https?:\/\/[^>]+)>)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[1]) nodes.push({ tag: "code", content: m[1].slice(1, -1) });
    else if (m[2]) nodes.push({ tag: "bold", content: m[2].slice(2, -2) });
    else if (m[3]) nodes.push({ tag: "bold", content: m[3].slice(1, -1) });
    else if (m[4]) nodes.push({ tag: "italic", content: m[4].slice(1, -1) });
    else if (m[5]) nodes.push({ tag: "strike", content: m[5].slice(1, -1) });
    else if (m[6]) nodes.push({ tag: "link", content: m[7], href: m[8] });
    else if (m[9]) nodes.push({ tag: "link", content: m[10], href: m[10] });
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function InlineRenderer({ nodes, t }: { nodes: InlineNode[]; t: ReturnType<typeof useThemeTokens> }) {
  return (
    <>
      {nodes.map((n, i) => {
        if (typeof n === "string") {
          const parts = n.split("\n");
          return parts.map((p, j) => (
            <span key={`${i}-${j}`}>
              {p}
              {j < parts.length - 1 && <br />}
            </span>
          ));
        }
        switch (n.tag) {
          case "code":
            return (
              <code
                key={i}
                style={{
                  fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
                  fontSize: "0.85em",
                  background: t.codeBg,
                  padding: "2px 6px",
                  borderRadius: 4,
                  color: t.codeText,
                  border: `1px solid ${t.codeBorder}`,
                }}
              >
                {n.content}
              </code>
            );
          case "bold":
            return <strong key={i}>{n.content}</strong>;
          case "italic":
            return <em key={i}>{n.content}</em>;
          case "strike":
            return <s key={i}>{n.content}</s>;
          case "link":
            return (
              <a
                key={i}
                href={n.href}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: t.linkColor, textDecoration: "none" }}
                onMouseEnter={(e) => { (e.target as HTMLElement).style.textDecoration = "underline"; }}
                onMouseLeave={(e) => { (e.target as HTMLElement).style.textDecoration = "none"; }}
              >
                {n.content}
              </a>
            );
          default:
            return <span key={i}>{n.content}</span>;
        }
      })}
    </>
  );
}

/** Render a block of non-code text with block-level markdown (headings, lists, blockquotes, hr). */
function TextBlockRenderer({ text, t }: { text: string; t: ReturnType<typeof useThemeTokens> }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Horizontal rule
    if (/^(---+|\*\*\*+|___+)\s*$/.test(line.trim())) {
      elements.push(
        <hr key={key++} style={{ border: "none", borderTop: `1px solid ${t.surfaceBorder}`, margin: "12px 0" }} />
      );
      i++;
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,6})\s+(.+)/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const sizes = [22, 19, 17, 15, 14, 13];
      const weights = ["700", "700", "600", "600", "600", "600"];
      elements.push(
        <div key={key++} style={{ fontSize: sizes[level - 1], fontWeight: weights[level - 1] as any, color: t.text, margin: `${level <= 2 ? 12 : 8}px 0 4px` }}>
          <InlineRenderer nodes={parseInline(headingMatch[2])} t={t} />
        </div>
      );
      i++;
      continue;
    }

    // Blockquote (collect consecutive > lines)
    if (/^>\s?/.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      elements.push(
        <div
          key={key++}
          style={{
            borderLeft: `3px solid ${t.surfaceBorder}`,
            paddingLeft: 12,
            margin: "6px 0",
            color: t.textMuted,
            fontStyle: "italic",
          }}
        >
          <InlineRenderer nodes={parseInline(quoteLines.join("\n"))} t={t} />
        </div>
      );
      continue;
    }

    // Unordered list (collect consecutive - or * lines)
    if (/^[\-\*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[\-\*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[\-\*]\s+/, ""));
        i++;
      }
      elements.push(
        <ul key={key++} style={{ margin: "4px 0", paddingLeft: 24, listStyleType: "disc" }}>
          {items.map((item, j) => (
            <li key={j} style={{ marginBottom: 2 }}>
              <InlineRenderer nodes={parseInline(item)} t={t} />
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Ordered list (collect consecutive numbered lines)
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ""));
        i++;
      }
      elements.push(
        <ol key={key++} style={{ margin: "4px 0", paddingLeft: 24 }}>
          {items.map((item, j) => (
            <li key={j} style={{ marginBottom: 2 }}>
              <InlineRenderer nodes={parseInline(item)} t={t} />
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // Regular text line (or empty line)
    if (line.trim() === "") {
      elements.push(<div key={key++} style={{ height: 8 }} />);
    } else {
      const nodes = parseInline(line);
      elements.push(
        <div key={key++}>
          <InlineRenderer nodes={nodes} t={t} />
        </div>
      );
    }
    i++;
  }

  return <>{elements}</>;
}

export function MarkdownContent({ text, t }: { text: string; t: ReturnType<typeof useThemeTokens> }) {
  // Split on fenced code blocks first, then render each segment
  const blocks: { type: "code" | "text"; content: string; lang?: string }[] = [];
  const codeBlockRe = /```(\w*)\n?([\s\S]*?)```/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = codeBlockRe.exec(text)) !== null) {
    if (m.index > last) {
      blocks.push({ type: "text", content: text.slice(last, m.index) });
    }
    blocks.push({ type: "code", content: m[2], lang: m[1] || undefined });
    last = m.index + m[0].length;
  }
  if (last < text.length) blocks.push({ type: "text", content: text.slice(last) });

  return (
    <div style={{ fontSize: 15, lineHeight: "1.6", color: t.contentText }}>
      {blocks.map((block, i) => {
        if (block.type === "code") {
          return (
            <pre
              key={i}
              style={{
                fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
                fontSize: 13,
                background: t.codeBg,
                padding: "12px 16px",
                borderRadius: 8,
                border: `1px solid ${t.codeBorder}`,
                overflowX: "auto",
                margin: "8px 0",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                lineHeight: "1.5",
              }}
            >
              {block.content}
            </pre>
          );
        }
        return <TextBlockRenderer key={i} text={block.content} t={t} />;
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Attachment rendering (web only)
// ---------------------------------------------------------------------------

function AttachmentImages({ attachments, t }: { attachments: AttachmentBrief[]; t: ReturnType<typeof useThemeTokens> }) {
  const serverUrl = useAuthStore((s) => s.serverUrl);
  const token = getAuthToken();
  const images = attachments.filter(
    (a) => a.type === "image" && a.has_file_data
  );
  const files = attachments.filter(
    (a) => a.type !== "image" || !a.has_file_data
  );

  if (images.length === 0 && files.length === 0) return null;

  return (
    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
      {images.map((img) => (
        <a
          key={img.id}
          href={`${serverUrl}/api/v1/attachments/${img.id}/file${token ? `?token=${token}` : ""}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <img
            src={`${serverUrl}/api/v1/attachments/${img.id}/file${token ? `?token=${token}` : ""}`}
            alt={img.description || img.filename}
            style={{
              maxWidth: "100%",
              maxHeight: 360,
              borderRadius: 8,
              display: "block",
            }}
          />
        </a>
      ))}
      {files.map((f) => {
        // Always generate a download link — let the server return 404 if data was purged
        const href = `${serverUrl}/api/v1/attachments/${f.id}/file${token ? `?token=${token}` : ""}`;
        return (
          <a
            key={f.id}
            href={href}
            download={f.filename}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
              color: t.accent,
              textDecoration: "none",
              cursor: "pointer",
            }}
          >
            <span style={{ fontSize: 14 }}>📎</span>
            <span style={{ textDecoration: "underline" }}>{f.filename}</span>
            <span style={{ color: t.textDim }}>
              ({(f.size_bytes / 1024).toFixed(1)} KB)
            </span>
          </a>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tool badges — shows tools used on persisted messages, click to expand args
// ---------------------------------------------------------------------------

function ToolBadges({
  toolNames,
  toolCalls,
  t,
}: {
  toolNames: string[];
  toolCalls?: ToolCall[];
  t: ReturnType<typeof useThemeTokens>;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  if (toolNames.length === 0) return null;

  // Build display list: if we have full tool_calls, use them (preserves order + args).
  // Otherwise fall back to toolNames with dedup/count.
  const items: { name: string; count: number; args?: string }[] = [];
  if (toolCalls && toolCalls.length > 0) {
    for (const tc of toolCalls) {
      const norm = normalizeToolCall(tc);
      items.push({ name: norm.name, count: 1, args: norm.arguments });
    }
  } else {
    const counts = new Map<string, number>();
    for (const name of toolNames) {
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    for (const [name, count] of counts) {
      items.push({ name, count });
    }
  }

  const isWeb = Platform.OS === "web";

  if (isWeb) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {items.map((item, idx) => {
            const hasArgs = !!item.args;
            const isExpanded = expandedIdx === idx;
            return (
              <div key={idx} style={{ display: "flex", flexDirection: "column" }}>
                <div
                  onClick={hasArgs ? () => setExpandedIdx(isExpanded ? null : idx) : undefined}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    paddingLeft: 6,
                    paddingRight: 8,
                    paddingTop: 3,
                    paddingBottom: 3,
                    borderRadius: 4,
                    backgroundColor: isExpanded ? t.surfaceBorder : t.overlayLight,
                    border: `1px solid ${t.overlayBorder}`,
                    cursor: hasArgs ? "pointer" : "default",
                    transition: "background-color 0.15s",
                  }}
                >
                  <Wrench size={10} color={t.textDim} />
                  <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "'Menlo', monospace" }}>
                    {item.name}{item.count > 1 ? ` x${item.count}` : ""}
                  </span>
                  {hasArgs && (
                    isExpanded
                      ? <ChevronDown size={10} color={t.textDim} />
                      : <ChevronRight size={10} color={t.textDim} />
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {expandedIdx !== null && items[expandedIdx]?.args && (() => {
          const formatted = formatToolArgs(items[expandedIdx].args);
          if (!formatted) return null;
          return (
            <div
              style={{
                borderRadius: 6,
                backgroundColor: t.overlayLight,
                border: `1px solid ${t.overlayBorder}`,
                padding: "6px 10px",
                maxHeight: 300,
                overflowY: "auto",
              }}
            >
              <pre
                style={{
                  margin: 0,
                  fontSize: 11,
                  fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
                  color: t.textMuted,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  lineHeight: "1.4",
                }}
              >
                {formatted}
              </pre>
            </div>
          );
        })()}
      </div>
    );
  }

  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
      {items.map((item, idx) => (
        <View
          key={idx}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            paddingHorizontal: 6,
            paddingVertical: 3,
            borderRadius: 4,
            backgroundColor: t.overlayLight,
            borderWidth: 1,
            borderColor: t.overlayBorder,
          }}
        >
          <Text style={{ fontSize: 11, color: t.textMuted }}>
            {item.name}{item.count > 1 ? ` x${item.count}` : ""}
          </Text>
        </View>
      ))}
    </View>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble — Slack-style flat layout
// ---------------------------------------------------------------------------

export function MessageBubble({ message, botName, isGrouped }: Props) {
  const isWeb = Platform.OS === "web";
  const t = useThemeTokens();
  const meta = message.metadata || {};
  const [heartbeatExpanded, setHeartbeatExpanded] = useState(false);
  // Extract text from content (handles JSON-array content blocks) then strip Slack prefix
  const rawText = extractDisplayText(message.content);
  const { slackUserId, cleaned: displayContent } = parseSlackPrefix(rawText);
  const { name: displayName, isCurrentUser, isSlack } = resolveDisplay(message, botName, slackUserId);
  const isUser = isCurrentUser;
  const timestamp = formatTimeShort(message.created_at);
  const sourceLabel = isSlack ? "via Slack" : null;
  const toolsUsed: string[] = (meta.tools_used as string[]) || [];
  const msgToolCalls: ToolCall[] | undefined = message.tool_calls;
  const trigger = meta.trigger as string | undefined;
  const delegations = (meta.delegations as any[]) || [];
  const delegatedByDisplay = meta.delegated_by_display as string | undefined;
  const triggerBadge = trigger === "heartbeat"
    ? { label: "heartbeat", icon: "💓", color: "#ec4899" }
    : trigger === "scheduled_task"
      ? { label: meta.task_title || "scheduled", icon: "🔁", color: "#8b5cf6" }
      : trigger === "harness_callback"
        ? { label: meta.harness_name || "harness", icon: "⚡", color: "#06b6d4" }
        : trigger === "delegation_callback"
          ? { label: meta.delegation_child_display || "delegation", icon: "↩", color: "#8b5cf6" }
          : trigger === "callback"
            ? { label: "callback", icon: "↩", color: "#8b5cf6" }
            : meta.is_heartbeat
              ? { label: "heartbeat", icon: "💓", color: "#ec4899" }
              : null;

  // Collapsed non-dispatched heartbeat messages
  const isNonDispatchedHeartbeat = (trigger === "heartbeat" || meta.is_heartbeat) && meta.dispatched === false;
  if (isNonDispatchedHeartbeat && isWeb) {
    return (
      <div
        style={{
          paddingLeft: 20,
          paddingRight: 20,
          paddingTop: 2,
          paddingBottom: 2,
        }}
      >
        <div
          onClick={() => setHeartbeatExpanded((v) => !v)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            cursor: "pointer",
            padding: "4px 8px",
            borderRadius: 4,
            fontSize: 12,
            color: t.textDim,
          }}
        >
          {heartbeatExpanded
            ? <ChevronDown size={11} color={t.textDim} />
            : <ChevronRight size={11} color={t.textDim} />
          }
          <span>💓</span>
          <span>Heartbeat ran</span>
          <span style={{ fontSize: 11, color: t.textDim, opacity: 0.7 }}>
            {timestamp}
          </span>
        </div>
        {heartbeatExpanded && (
          <div style={{ paddingLeft: 30, paddingTop: 4, paddingBottom: 4 }}>
            <div style={{ fontSize: 14, lineHeight: "1.5", color: t.textMuted, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {displayContent}
            </div>
            {toolsUsed.length > 0 && <ToolBadges toolNames={toolsUsed} toolCalls={msgToolCalls} t={t} />}
          </div>
        )}
      </div>
    );
  }
  if (isNonDispatchedHeartbeat && !isWeb) {
    return (
      <View style={{ paddingHorizontal: 20, paddingVertical: 2 }}>
        <Text style={{ fontSize: 12, color: t.textDim }}>
          💓 Heartbeat ran — {timestamp}
        </Text>
      </View>
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

  // Grouped message — compact, no avatar or name header
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

  // Full message — avatar + name header + content
  const inner = (
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
          {triggerBadge && isWeb && (
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
          {triggerBadge && !isWeb && (
            <Text style={{ fontSize: 10, color: triggerBadge.color, fontWeight: "600" }}>
              {triggerBadge.icon} {triggerBadge.label}
            </Text>
          )}
        </View>

        {/* Message content */}
        {messageContent}
      </View>
    </>
  );

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
        {inner}
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
      {inner}
    </View>
  );
}
