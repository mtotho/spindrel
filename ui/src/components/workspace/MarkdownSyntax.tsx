import type { ThemeTokens } from "../../theme/tokens";

/**
 * Syntax-highlights a single line of raw markdown.
 * Returns React nodes with inline styles for coloring.
 */
export function highlightMarkdownLine(
  line: string,
  t: ThemeTokens,
  inCodeBlock: boolean,
): React.ReactNode {
  // Inside a fenced code block — render as code text
  if (inCodeBlock) {
    return <span style={{ color: t.contentText }}>{line || " "}</span>;
  }

  // Fence opener/closer (```)
  if (/^```/.test(line)) {
    return <span style={{ color: t.textDim }}>{line}</span>;
  }

  // Heading
  const headingMatch = line.match(/^(#{1,6})\s+(.*)/);
  if (headingMatch) {
    const level = headingMatch[1].length;
    const sizes: Record<number, number> = { 1: 18, 2: 16, 3: 15, 4: 14, 5: 13, 6: 13 };
    return (
      <span style={{ fontWeight: 700, fontSize: sizes[level] ?? 13, color: t.accent }}>
        <span style={{ color: t.textDim }}>{headingMatch[1]} </span>
        {headingMatch[2]}
      </span>
    );
  }

  // Horizontal rule
  if (/^(---+|\*\*\*+|___+)\s*$/.test(line)) {
    return <span style={{ color: t.textDim }}>{line}</span>;
  }

  // Blockquote
  if (/^>\s?/.test(line)) {
    return (
      <span>
        <span style={{ color: t.accent, fontWeight: 600 }}>&gt; </span>
        <span style={{ color: t.textMuted, fontStyle: "italic" }}>
          {highlightInline(line.replace(/^>\s?/, ""), t)}
        </span>
      </span>
    );
  }

  // Unordered list item
  const ulMatch = line.match(/^(\s*)([-*])\s+(.*)/);
  if (ulMatch) {
    return (
      <span>
        {ulMatch[1]}
        <span style={{ color: t.accent, fontWeight: 600 }}>{ulMatch[2]} </span>
        {highlightInline(ulMatch[3], t)}
      </span>
    );
  }

  // Ordered list item
  const olMatch = line.match(/^(\s*)(\d+\.)\s+(.*)/);
  if (olMatch) {
    return (
      <span>
        {olMatch[1]}
        <span style={{ color: t.accent, fontWeight: 600 }}>{olMatch[2]} </span>
        {highlightInline(olMatch[3], t)}
      </span>
    );
  }

  // Table row (contains |)
  if (/^\|/.test(line.trim()) || /\|/.test(line)) {
    // Separator row (|---|---|)
    if (/^\|?\s*[-:]+[-| :]*$/.test(line)) {
      return <span style={{ color: t.textDim }}>{line}</span>;
    }
    // Header/data row — color the pipes
    return highlightTableRow(line, t);
  }

  // Regular line — apply inline highlighting
  return <span>{highlightInline(line, t)}</span>;
}

/** Track code block state across lines */
export function isCodeFence(line: string): boolean {
  return /^```/.test(line);
}

// ---------------------------------------------------------------------------
// Inline highlighting
// ---------------------------------------------------------------------------

function highlightInline(text: string, t: ThemeTokens): React.ReactNode[] {
  if (!text) return [" "];

  const nodes: React.ReactNode[] = [];
  // Order matters: images before links, bold before italic, etc.
  const pattern = /!\[([^\]]*)\]\(([^)]+)\)|(\[([^\]]+)\]\(([^)]+)\))|(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(__[^_]+__)|(_[^_]+_)/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    if (match[0].startsWith("![")) {
      // Image — show full syntax dimmed with alt text highlighted
      nodes.push(
        <span key={key++} style={{ color: t.linkColor }}>
          <span style={{ color: t.textDim }}>![</span>
          {match[1]}
          <span style={{ color: t.textDim }}>]({match[2]})</span>
        </span>
      );
    } else if (match[3]) {
      // Link
      nodes.push(
        <span key={key++} style={{ color: t.linkColor }}>
          <span style={{ color: t.textDim }}>[</span>
          <span style={{ textDecoration: "underline" }}>{match[4]}</span>
          <span style={{ color: t.textDim }}>]({match[5]})</span>
        </span>
      );
    } else if (match[6]) {
      // Inline code
      nodes.push(
        <span
          key={key++}
          style={{
            background: t.codeBg,
            color: t.codeText,
            borderRadius: 3,
            padding: "0 3px",
          }}
        >
          {match[6]}
        </span>
      );
    } else if (match[7]) {
      // Bold **text**
      nodes.push(
        <span key={key++}>
          <span style={{ color: t.textDim }}>**</span>
          <strong>{match[7].slice(2, -2)}</strong>
          <span style={{ color: t.textDim }}>**</span>
        </span>
      );
    } else if (match[8]) {
      // Italic *text*
      nodes.push(
        <span key={key++}>
          <span style={{ color: t.textDim }}>*</span>
          <em>{match[8].slice(1, -1)}</em>
          <span style={{ color: t.textDim }}>*</span>
        </span>
      );
    } else if (match[9]) {
      // Bold __text__
      nodes.push(
        <span key={key++}>
          <span style={{ color: t.textDim }}>__</span>
          <strong>{match[9].slice(2, -2)}</strong>
          <span style={{ color: t.textDim }}>__</span>
        </span>
      );
    } else if (match[10]) {
      // Italic _text_
      nodes.push(
        <span key={key++}>
          <span style={{ color: t.textDim }}>_</span>
          <em>{match[10].slice(1, -1)}</em>
          <span style={{ color: t.textDim }}>_</span>
        </span>
      );
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes.length > 0 ? nodes : [text || " "];
}

function highlightTableRow(line: string, t: ThemeTokens): React.ReactNode {
  // Split on | and color the pipes
  const parts = line.split("|");
  const nodes: React.ReactNode[] = [];
  for (let i = 0; i < parts.length; i++) {
    if (i > 0) {
      nodes.push(<span key={`p${i}`} style={{ color: t.textDim }}>|</span>);
    }
    if (parts[i]) {
      nodes.push(<span key={`t${i}`}>{highlightInline(parts[i], t)}</span>);
    }
  }
  return <span>{nodes}</span>;
}
