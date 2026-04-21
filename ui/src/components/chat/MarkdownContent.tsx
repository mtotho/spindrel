/**
 * Markdown rendering for chat messages (web only).
 *
 * Handles fenced code blocks, headings, lists, blockquotes, horizontal rules,
 * and inline formatting (bold, italic, strike, code, links).
 *
 * Extracted from MessageBubble.tsx.
 */

import type { ThemeTokens } from "../../theme/tokens";

// ---------------------------------------------------------------------------
// Inline markdown parsing
// ---------------------------------------------------------------------------

type InlineNode =
  | string
  | { tag: string; content: string; href?: string }
  | { tag: "mention"; prefix: string; name: string };

// Mirrors app/agent/tags.py::_TAG_RE: negative lookbehind skips Slack <@USERID>
// and email addresses; names start with letter/underscore and allow slashes.
// Only prefixed forms (`skill:` / `tool:` / `tool-pack:` / `bot:`) become
// chips — bare `@name` stays plain text because we can't classify it client-side.
const MENTION_RE =
  /(?<![<\w@])@(skill|tool-pack|tool|bot):([A-Za-z_][\w\-\.\/]*)/g;

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  const pattern =
    /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\_[^_]+\_)|(~[^~]+~)|(\[([^\]]+)\]\(([^)]+)\))|(<(https?:\/\/[^>]+)>)|((?<![<\w@])@(skill|tool-pack|tool|bot):([A-Za-z_][\w\-\.\/]*))/g;
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
    else if (m[11]) nodes.push({ tag: "mention", prefix: m[12], name: m[13] });
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

// Matches the composer badge palette in ui/src/components/shared/LlmPrompt.tsx.
const MENTION_COLORS: Record<string, { bg: string; fg: string }> = {
  skill: { bg: "#1e1b4b", fg: "#a5b4fc" },
  tool: { bg: "#14532d", fg: "#86efac" },
  "tool-pack": { bg: "#14532d", fg: "#86efac" },
  bot: { bg: "#1e3a5f", fg: "#7dd3fc" },
};

// Suppress unused-var warning for MENTION_RE (exported for tests).
export { MENTION_RE };

function InlineRenderer({ nodes, t }: { nodes: InlineNode[]; t: ThemeTokens }) {
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
                style={{ color: t.linkColor, textDecoration: "underline", textDecorationColor: `${t.linkColor}50`, textUnderlineOffset: 2 }}
                onMouseEnter={(e) => { (e.target as HTMLElement).style.textDecorationColor = t.linkColor; }}
                onMouseLeave={(e) => { (e.target as HTMLElement).style.textDecorationColor = `${t.linkColor}50`; }}
              >
                {"content" in n ? n.content : ""}
              </a>
            );
          case "mention": {
            if (!("prefix" in n)) return null;
            const colors = MENTION_COLORS[n.prefix] ?? { bg: "#374151", fg: t.contentText };
            return (
              <span
                key={i}
                data-type={n.prefix}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  fontSize: "0.9em",
                  fontWeight: 500,
                  padding: "1px 7px",
                  margin: "0 1px",
                  borderRadius: 4,
                  background: colors.bg,
                  color: colors.fg,
                  verticalAlign: "baseline",
                  whiteSpace: "nowrap",
                }}
              >
                @{n.prefix}:{n.name}
              </span>
            );
          }
          default:
            return <span key={i}>{"content" in n ? n.content : ""}</span>;
        }
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Block-level markdown rendering
// ---------------------------------------------------------------------------

/** Render a block of non-code text with block-level markdown (headings, lists, blockquotes, hr). */
function TextBlockRenderer({ text, t }: { text: string; t: ThemeTokens }) {
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

// ---------------------------------------------------------------------------
// Main MarkdownContent component
// ---------------------------------------------------------------------------

export function MarkdownContent({ text, t }: { text: string; t: ThemeTokens }) {
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
    <div style={{ fontSize: 15, lineHeight: "1.6", color: t.contentText, overflowWrap: "break-word", minWidth: 0 }}>
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
