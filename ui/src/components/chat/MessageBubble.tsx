import { View, Text, Platform } from "react-native";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { formatTimeShort } from "../../utils/time";
import type { Message, AttachmentBrief } from "../../types/api";

interface Props {
  message: Message;
  botName?: string;
  /** Whether this message is "grouped" with the previous (same author, close in time) */
  isGrouped?: boolean;
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

function renderInlineNodes(nodes: InlineNode[]) {
  return nodes.map((n, i) => {
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
              background: "rgba(255,255,255,0.06)",
              padding: "2px 6px",
              borderRadius: 4,
              color: "#e06c75",
              border: "1px solid rgba(255,255,255,0.06)",
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
            style={{ color: "#5b9bd5", textDecoration: "none" }}
            onMouseEnter={(e) => { (e.target as HTMLElement).style.textDecoration = "underline"; }}
            onMouseLeave={(e) => { (e.target as HTMLElement).style.textDecoration = "none"; }}
          >
            {n.content}
          </a>
        );
      default:
        return <span key={i}>{n.content}</span>;
    }
  });
}

function MarkdownContent({ text }: { text: string }) {
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
    <div style={{ fontSize: 15, lineHeight: "1.6", color: "#d1d5db" }}>
      {blocks.map((block, i) => {
        if (block.type === "code") {
          return (
            <pre
              key={i}
              style={{
                fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
                fontSize: 13,
                background: "#1a1a1e",
                padding: "12px 16px",
                borderRadius: 8,
                border: "1px solid rgba(255,255,255,0.06)",
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
        const nodes = parseInline(block.content);
        return (
          <span key={i}>{renderInlineNodes(nodes)}</span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Attachment rendering (web only)
// ---------------------------------------------------------------------------

function AttachmentImages({ attachments }: { attachments: AttachmentBrief[] }) {
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
      {files.map((f) => (
        <div
          key={f.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 13,
            color: "#999",
          }}
        >
          <span style={{ fontSize: 14 }}>📎</span>
          <span>{f.filename}</span>
          <span style={{ color: "#666" }}>
            ({(f.size_bytes / 1024).toFixed(1)} KB)
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble — Slack-style flat layout
// ---------------------------------------------------------------------------

export function MessageBubble({ message, botName, isGrouped }: Props) {
  const isUser = message.role === "user";
  const isWeb = Platform.OS === "web";
  const displayName = isUser ? "You" : (botName || "Bot");
  const timestamp = formatTimeShort(message.created_at);

  const messageContent = isWeb ? (
    <>
      {(message.content || "").length > 0 && (
        <MarkdownContent text={message.content || ""} />
      )}
      {message.attachments && message.attachments.length > 0 && (
        <AttachmentImages attachments={message.attachments} />
      )}
    </>
  ) : (
    <Text
      className="text-[15px] leading-relaxed"
      style={{ color: "#d1d5db" }}
      selectable
    >
      {message.content || ""}
    </Text>
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
        <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <Text
            style={{
              fontSize: 15,
              fontWeight: "700",
              color: isUser ? "#e5e5e5" : avatarColor(displayName),
            }}
          >
            {displayName}
          </Text>
          <Text style={{ fontSize: 12, color: "#555555" }}>
            {timestamp}
          </Text>
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
