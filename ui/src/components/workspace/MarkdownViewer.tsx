import { useMemo } from "react";
import { useThemeTokens, type ThemeTokens } from "../../theme/tokens";

interface MarkdownViewerProps {
  content: string;
}

export function MarkdownViewer({ content }: MarkdownViewerProps) {
  const t = useThemeTokens();
  const blocks = useMemo(() => parseBlocks(content), [content]);

  return (
    <div style={{ padding: "16px 24px", maxWidth: 800, lineHeight: 1.6 }}>
      {blocks.map((block, i) => renderBlock(block, i, t))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Block-level parsing
// ---------------------------------------------------------------------------

type Block =
  | { type: "heading"; level: number; text: string }
  | { type: "code"; lang: string; text: string }
  | { type: "blockquote"; text: string }
  | { type: "hr" }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "paragraph"; text: string }
  | { type: "table"; headers: string[]; rows: string[][] };

function parseBlocks(src: string): Block[] {
  const blocks: Block[] = [];
  const lines = src.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    const fenceMatch = line.match(/^```(\w*)/);
    if (fenceMatch) {
      const lang = fenceMatch[1];
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", lang, text: codeLines.join("\n") });
      continue;
    }

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(---+|\*\*\*+|___+)\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,6})\s+(.+)/);
    if (headingMatch) {
      blocks.push({ type: "heading", level: headingMatch[1].length, text: headingMatch[2] });
      i++;
      continue;
    }

    // Blockquote (collect consecutive > lines)
    if (line.startsWith("> ") || line === ">") {
      const quoteLines: string[] = [];
      while (i < lines.length && (lines[i].startsWith("> ") || lines[i] === ">")) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ type: "blockquote", text: quoteLines.join("\n") });
      continue;
    }

    // Unordered list
    if (/^[\-\*]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[\-\*]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[\-\*]\s+/, ""));
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ""));
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // Table (| header | header |)
    if (line.includes("|") && i + 1 < lines.length && /^\|?\s*[-:]+[-| :]*$/.test(lines[i + 1])) {
      const parseRow = (row: string) =>
        row.split("|").map((c) => c.trim()).filter((c) => c !== "");
      const headers = parseRow(line);
      i += 2; // skip header + separator
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(parseRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    // Paragraph (collect consecutive non-empty, non-special lines)
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].match(/^(#{1,6})\s/) &&
      !lines[i].startsWith("```") &&
      !lines[i].startsWith("> ") &&
      !/^[\-\*]\s/.test(lines[i]) &&
      !/^\d+\.\s/.test(lines[i]) &&
      !/^(---+|\*\*\*+|___+)\s*$/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: "paragraph", text: paraLines.join("\n") });
    }
  }

  return blocks;
}

// ---------------------------------------------------------------------------
// Inline parsing
// ---------------------------------------------------------------------------

function renderInline(text: string, t: ThemeTokens): React.ReactNode[] {
  // Process inline patterns: images, links, bold, italic, inline code
  const nodes: React.ReactNode[] = [];
  // Regex matches inline elements in order of priority
  const pattern = /!\[([^\]]*)\]\(([^)]+)\)|(\[([^\]]+)\]\(([^)]+)\))|(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(__[^_]+__)|(_[^_]+_)/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    // Add text before match
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    if (match[0].startsWith("![")) {
      // Image
      const alt = match[1];
      const src = match[2];
      nodes.push(
        <img
          key={match.index}
          src={src}
          alt={alt}
          style={{ maxWidth: "100%", borderRadius: 4 }}
        />
      );
    } else if (match[3]) {
      // Link
      const linkText = match[4];
      const href = match[5];
      nodes.push(
        <a
          key={match.index}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: t.linkColor, textDecoration: "underline" }}
        >
          {linkText}
        </a>
      );
    } else if (match[6]) {
      // Inline code
      const code = match[6].slice(1, -1);
      nodes.push(
        <code
          key={match.index}
          style={{
            background: t.codeBg,
            border: `1px solid ${t.codeBorder}`,
            color: t.codeText,
            borderRadius: 3,
            padding: "1px 4px",
            fontSize: "0.9em",
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          }}
        >
          {code}
        </code>
      );
    } else if (match[7]) {
      // Bold **text**
      nodes.push(<strong key={match.index}>{match[7].slice(2, -2)}</strong>);
    } else if (match[8]) {
      // Italic *text*
      nodes.push(<em key={match.index}>{match[8].slice(1, -1)}</em>);
    } else if (match[9]) {
      // Bold __text__
      nodes.push(<strong key={match.index}>{match[9].slice(2, -2)}</strong>);
    } else if (match[10]) {
      // Italic _text_
      nodes.push(<em key={match.index}>{match[10].slice(1, -1)}</em>);
    }

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes.length > 0 ? nodes : [text];
}

// ---------------------------------------------------------------------------
// Block rendering
// ---------------------------------------------------------------------------

function renderBlock(block: Block, key: number, t: ThemeTokens): React.ReactNode {
  switch (block.type) {
    case "heading": {
      const sizes: Record<number, number> = { 1: 24, 2: 20, 3: 17, 4: 15, 5: 14, 6: 13 };
      const bottomBorder = block.level <= 2;
      return (
        <div
          key={key}
          style={{
            fontSize: sizes[block.level] ?? 14,
            fontWeight: 600,
            color: t.text,
            marginTop: block.level <= 2 ? 24 : 16,
            marginBottom: 8,
            paddingBottom: bottomBorder ? 6 : 0,
            borderBottom: bottomBorder ? `1px solid ${t.surfaceBorder}` : "none",
          }}
        >
          {renderInline(block.text, t)}
        </div>
      );
    }
    case "code":
      return (
        <pre
          key={key}
          style={{
            background: t.codeBg,
            border: `1px solid ${t.codeBorder}`,
            borderRadius: 6,
            padding: "12px 16px",
            margin: "12px 0",
            overflow: "auto",
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            fontSize: 13,
            lineHeight: "20px",
            color: t.contentText,
          }}
        >
          {block.text}
        </pre>
      );
    case "blockquote":
      return (
        <blockquote
          key={key}
          style={{
            borderLeft: `3px solid ${t.accent}`,
            paddingLeft: 16,
            margin: "12px 0",
            color: t.textMuted,
            fontStyle: "italic",
          }}
        >
          {renderInline(block.text, t)}
        </blockquote>
      );
    case "hr":
      return (
        <hr
          key={key}
          style={{
            border: "none",
            borderTop: `1px solid ${t.surfaceBorder}`,
            margin: "20px 0",
          }}
        />
      );
    case "ul":
      return (
        <ul key={key} style={{ margin: "8px 0", paddingLeft: 24, color: t.contentText }}>
          {block.items.map((item, j) => (
            <li key={j} style={{ marginBottom: 4 }}>{renderInline(item, t)}</li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol key={key} style={{ margin: "8px 0", paddingLeft: 24, color: t.contentText }}>
          {block.items.map((item, j) => (
            <li key={j} style={{ marginBottom: 4 }}>{renderInline(item, t)}</li>
          ))}
        </ol>
      );
    case "table":
      return (
        <div key={key} style={{ overflowX: "auto", margin: "12px 0" }}>
          <table
            style={{
              borderCollapse: "collapse",
              width: "100%",
              fontSize: 13,
              color: t.contentText,
            }}
          >
            <thead>
              <tr>
                {block.headers.map((h, j) => (
                  <th
                    key={j}
                    style={{
                      borderBottom: `2px solid ${t.surfaceBorder}`,
                      padding: "6px 12px",
                      textAlign: "left",
                      fontWeight: 600,
                      color: t.text,
                    }}
                  >
                    {renderInline(h, t)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      style={{
                        borderBottom: `1px solid ${t.surfaceBorder}`,
                        padding: "6px 12px",
                      }}
                    >
                      {renderInline(cell, t)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "paragraph":
      return (
        <p key={key} style={{ margin: "8px 0", color: t.contentText, fontSize: 14 }}>
          {renderInline(block.text, t)}
        </p>
      );
  }
}
