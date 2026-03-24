import { View, Text, Platform } from "react-native";
import { useAuthStore } from "../../stores/auth";
import type { Message, AttachmentBrief } from "../../types/api";

interface Props {
  message: Message;
  botName?: string;
}

// Deterministic color from string hash
function avatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = [
    "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#06b6d4", "#ef4444", "#6366f1",
  ];
  return colors[Math.abs(hash) % colors.length];
}

function Avatar({ name, isUser }: { name: string; isUser: boolean }) {
  const bg = isUser ? "#4b5563" : avatarColor(name);
  const letter = isUser ? "U" : (name[0] || "B").toUpperCase();
  return (
    <View
      style={{
        width: 28,
        height: 28,
        borderRadius: 14,
        backgroundColor: bg,
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>
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
  // Order matters: bold (**) before Slack bold (*), inline code before others
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

function renderInlineNodes(nodes: InlineNode[], isUser: boolean) {
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
              fontFamily: "monospace",
              fontSize: "0.85em",
              background: isUser ? "rgba(255,255,255,0.15)" : "rgba(255,255,255,0.08)",
              padding: "1px 5px",
              borderRadius: 3,
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
            style={{ color: isUser ? "#bfdbfe" : "#60a5fa", textDecoration: "underline" }}
          >
            {n.content}
          </a>
        );
      default:
        return <span key={i}>{n.content}</span>;
    }
  });
}

function MarkdownContent({
  text,
  isUser,
}: {
  text: string;
  isUser: boolean;
}) {
  // Split into code blocks and paragraphs
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
    <div style={{ fontSize: 14, lineHeight: "1.5", color: isUser ? "#fff" : "#e5e5e5" }}>
      {blocks.map((block, i) => {
        if (block.type === "code") {
          return (
            <pre
              key={i}
              style={{
                fontFamily: "monospace",
                fontSize: 13,
                background: isUser ? "rgba(0,0,0,0.3)" : "rgba(255,255,255,0.06)",
                padding: "10px 12px",
                borderRadius: 6,
                overflowX: "auto",
                margin: "6px 0",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {block.content}
            </pre>
          );
        }
        const nodes = parseInline(block.content);
        return (
          <span key={i}>{renderInlineNodes(nodes, isUser)}</span>
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
  const apiKey = useAuthStore((s) => s.apiKey);
  const images = attachments.filter(
    (a) => a.type === "image" && a.has_file_data
  );
  const files = attachments.filter(
    (a) => a.type !== "image" || !a.has_file_data
  );

  if (images.length === 0 && files.length === 0) return null;

  return (
    <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
      {images.map((img) => (
        <a
          key={img.id}
          href={`${serverUrl}/api/v1/attachments/${img.id}/file${apiKey ? `?token=${apiKey}` : ""}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <img
            src={`${serverUrl}/api/v1/attachments/${img.id}/file${apiKey ? `?token=${apiKey}` : ""}`}
            alt={img.description || img.filename}
            style={{
              maxWidth: "100%",
              maxHeight: 300,
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
            gap: 6,
            fontSize: 12,
            color: "#999",
          }}
        >
          <span>📎</span>
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
// MessageBubble
// ---------------------------------------------------------------------------

export function MessageBubble({ message, botName }: Props) {
  const isUser = message.role === "user";
  const isWeb = Platform.OS === "web";

  return (
    <View
      className={`mb-3 ${isUser ? "self-end" : "self-start"}`}
      style={{
        maxWidth: "80%",
        flexDirection: "row",
        alignItems: "flex-end",
        gap: 8,
      }}
    >
      {/* Bot avatar (left) */}
      {!isUser && <Avatar name={botName || "Bot"} isUser={false} />}

      <View style={{ flex: 1, minWidth: 0 }}>
        <View
          className={`rounded-2xl px-4 py-3 ${
            isUser
              ? "bg-accent rounded-br-md"
              : "rounded-bl-md"
          }`}
          style={!isUser ? { backgroundColor: "#2a2a2f" } : undefined}
        >
          {isWeb ? (
            <>
              {(message.content || "").length > 0 && (
                <MarkdownContent text={message.content || ""} isUser={isUser} />
              )}
              {message.attachments && message.attachments.length > 0 && (
                <AttachmentImages attachments={message.attachments} />
              )}
            </>
          ) : (
            <Text
              className="text-sm leading-relaxed"
              style={{ color: isUser ? "#fff" : "#e5e5e5" }}
              selectable
            >
              {message.content || ""}
            </Text>
          )}
        </View>
        <Text
          className={`text-[10px] text-text-dim mt-1 ${
            isUser ? "text-right" : "text-left"
          }`}
        >
          {new Date(message.created_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </Text>
      </View>

      {/* User avatar (right) */}
      {isUser && <Avatar name="User" isUser={true} />}
    </View>
  );
}
