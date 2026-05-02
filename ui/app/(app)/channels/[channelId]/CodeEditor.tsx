/**
 * VS Code-style code editor with line numbers and syntax highlighting.
 * Supports read/edit mode with a dual-layer approach:
 * - Highlighted `<pre>` layer for visual syntax coloring
 * - Transparent `<textarea>` on top for editing
 */
import { useRef, useCallback, useEffect, useState, useMemo } from "react";
import type { ThemeTokens } from "@/src/theme/tokens";

// Global CSS forces textarea { font-size: 16px !important } to prevent iOS
// focus zoom. Keep every visual layer on the same metrics so the transparent
// textarea caret stays aligned with the highlighted text behind it.
const EDITOR_FONT = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, 'Liberation Mono', monospace";
const EDITOR_FONT_SIZE = 16;
const EDITOR_LINE_HEIGHT_PX = 24;
const EDITOR_LINE_HEIGHT = `${EDITOR_LINE_HEIGHT_PX}px`;
const EDITOR_PADDING = "8px 12px";

// ---------------------------------------------------------------------------
// Token-level syntax highlighting (simple regex-based)
// ---------------------------------------------------------------------------

type TokenType = "keyword" | "string" | "comment" | "number" | "key" | "punctuation" | "heading" | "bold" | "italic" | "link" | "code" | "list" | "blockquote" | "dim";

interface Token {
  text: string;
  type?: TokenType;
}

function tokenColors(type: TokenType | undefined, t: ThemeTokens): string {
  switch (type) {
    case "keyword": return "#c586c0";
    case "string": return "#ce9178";
    case "comment": return t.textDim;
    case "number": return "#b5cea8";
    case "key": return "#9cdcfe";
    case "punctuation": return t.textDim;
    case "heading": return t.accent;
    case "bold": return t.text;
    case "italic": return t.textMuted;
    case "link": return "#4fc1ff";
    case "code": return "#ce9178";
    case "list": return t.accent;
    case "blockquote": return t.textMuted;
    case "dim": return t.textDim;
    default: return t.text;
  }
}

// Language-specific tokenizers
function tokenizeLine(line: string, lang: string, _inBlock: boolean): Token[] {
  switch (lang) {
    case "yaml": return tokenizeYaml(line);
    case "json": return tokenizeJson(line);
    case "py": return tokenizePython(line);
    case "md": return tokenizeMarkdown(line);
    default: return [{ text: line }];
  }
}

function tokenizeYaml(line: string): Token[] {
  // Comment
  if (/^\s*#/.test(line)) return [{ text: line, type: "comment" }];
  // Key: value
  const kvMatch = line.match(/^(\s*)([\w.-]+)(\s*:\s*)(.*)/);
  if (kvMatch) {
    const tokens: Token[] = [];
    if (kvMatch[1]) tokens.push({ text: kvMatch[1] });
    tokens.push({ text: kvMatch[2], type: "key" });
    tokens.push({ text: kvMatch[3], type: "punctuation" });
    const val = kvMatch[4];
    if (/^["']/.test(val)) tokens.push({ text: val, type: "string" });
    else if (/^(true|false|null|yes|no)$/i.test(val)) tokens.push({ text: val, type: "keyword" });
    else if (/^-?\d/.test(val)) tokens.push({ text: val, type: "number" });
    else tokens.push({ text: val });
    return tokens;
  }
  // List item
  const listMatch = line.match(/^(\s*)(- )(.*)/);
  if (listMatch) {
    return [
      { text: listMatch[1] },
      { text: listMatch[2], type: "punctuation" },
      { text: listMatch[3] },
    ];
  }
  return [{ text: line }];
}

function tokenizeJson(line: string): Token[] {
  const tokens: Token[] = [];
  const pattern = /("(?:[^"\\]|\\.)*")\s*(:)?|(-?\d+\.?\d*(?:[eE][+-]?\d+)?)|(\btrue\b|\bfalse\b|\bnull\b)|([{}[\],])/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(line)) !== null) {
    if (match.index > lastIndex) tokens.push({ text: line.slice(lastIndex, match.index) });
    if (match[1]) {
      if (match[2]) {
        tokens.push({ text: match[1], type: "key" });
        tokens.push({ text: match[2], type: "punctuation" });
      } else {
        tokens.push({ text: match[1], type: "string" });
      }
    } else if (match[3]) {
      tokens.push({ text: match[3], type: "number" });
    } else if (match[4]) {
      tokens.push({ text: match[4], type: "keyword" });
    } else if (match[5]) {
      tokens.push({ text: match[5], type: "punctuation" });
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < line.length) tokens.push({ text: line.slice(lastIndex) });
  return tokens.length ? tokens : [{ text: line }];
}

function tokenizePython(line: string): Token[] {
  // Comment
  if (/^\s*#/.test(line)) return [{ text: line, type: "comment" }];
  const tokens: Token[] = [];
  const keywords = /\b(def|class|import|from|return|if|elif|else|for|while|try|except|finally|with|as|in|not|and|or|is|lambda|yield|raise|pass|break|continue|True|False|None|self|async|await)\b/g;
  const strings = /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g;
  const numbers = /\b(\d+\.?\d*)\b/g;
  // Simple approach: highlight strings first, then keywords in non-string parts
  const stringParts: { start: number; end: number; text: string }[] = [];
  let sm: RegExpExecArray | null;
  while ((sm = strings.exec(line)) !== null) {
    stringParts.push({ start: sm.index, end: sm.index + sm[0].length, text: sm[0] });
  }
  let pos = 0;
  for (const sp of stringParts) {
    if (sp.start > pos) {
      tokens.push(...tokenizePythonCode(line.slice(pos, sp.start)));
    }
    tokens.push({ text: sp.text, type: "string" });
    pos = sp.end;
  }
  if (pos < line.length) tokens.push(...tokenizePythonCode(line.slice(pos)));
  return tokens.length ? tokens : [{ text: line }];
}

function tokenizePythonCode(code: string): Token[] {
  const tokens: Token[] = [];
  const pattern = /\b(def|class|import|from|return|if|elif|else|for|while|try|except|finally|with|as|in|not|and|or|is|lambda|yield|raise|pass|break|continue|True|False|None|self|async|await)\b|(\b\d+\.?\d*\b)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(code)) !== null) {
    if (match.index > lastIndex) tokens.push({ text: code.slice(lastIndex, match.index) });
    if (match[1]) tokens.push({ text: match[1], type: "keyword" });
    else if (match[2]) tokens.push({ text: match[2], type: "number" });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < code.length) tokens.push({ text: code.slice(lastIndex) });
  return tokens;
}

function tokenizeMarkdown(line: string): Token[] {
  // Heading
  const headingMatch = line.match(/^(#{1,6}\s+)(.*)/);
  if (headingMatch) {
    return [
      { text: headingMatch[1], type: "dim" },
      { text: headingMatch[2], type: "heading" },
    ];
  }
  // Code fence
  if (/^```/.test(line)) return [{ text: line, type: "dim" }];
  // Blockquote
  if (/^>\s?/.test(line)) return [{ text: line, type: "blockquote" }];
  // List
  const listMatch = line.match(/^(\s*)([-*]\s+|(\d+\.)\s+)(.*)/);
  if (listMatch) {
    return [
      { text: listMatch[1] },
      { text: listMatch[2], type: "list" },
      { text: listMatch[4] || "" },
    ];
  }
  // HR
  if (/^(---+|\*\*\*+|___+)\s*$/.test(line)) return [{ text: line, type: "dim" }];
  return [{ text: line }];
}

function getLang(filePath: string): string {
  const ext = filePath.includes(".") ? filePath.substring(filePath.lastIndexOf(".") + 1).toLowerCase() : "";
  switch (ext) {
    case "md": case "txt": case "rst": return "md";
    case "yaml": case "yml": case "toml": return "yaml";
    case "json": return "json";
    case "py": return "py";
    default: return "";
  }
}

// ---------------------------------------------------------------------------
// Editor component
// ---------------------------------------------------------------------------

interface CodeEditorProps {
  content: string;
  onChange: (content: string) => void;
  filePath: string;
  t: ThemeTokens;
}

export function CodeEditor({ content, onChange, filePath, t }: CodeEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const highlightRef = useRef<HTMLPreElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);

  const lang = getLang(filePath);
  const lines = useMemo(() => content.split("\n"), [content]);
  const lineCount = lines.length;

  // Sync scroll between textarea and highlight/gutter layers
  const handleScroll = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    setScrollTop(ta.scrollTop);
    setScrollLeft(ta.scrollLeft);
  }, []);

  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollTop = scrollTop;
      highlightRef.current.scrollLeft = scrollLeft;
    }
    if (gutterRef.current) {
      gutterRef.current.scrollTop = scrollTop;
    }
  }, [scrollTop, scrollLeft]);

  // Highlighted lines
  const highlightedLines = useMemo(() => {
    if (!lang) return null;
    return lines.map((line, i) => {
      const tokens = tokenizeLine(line, lang, false);
      return (
        <div key={i} style={{ height: EDITOR_LINE_HEIGHT_PX, lineHeight: EDITOR_LINE_HEIGHT, whiteSpace: "pre" }}>
          {tokens.map((tok, j) => (
            <span key={j} style={{ color: tok.type ? tokenColors(tok.type, t) : undefined }}>
              {tok.text}
            </span>
          ))}
          {line === "" && " "}
        </div>
      );
    });
  }, [lines, lang, t]);

  // Gutter width based on line count
  const gutterWidth = Math.max(44, String(lineCount).length * 10 + 24);

  return (
    <div
      style={{
        flex: 1,
        display: "flex", flexDirection: "row",
        overflow: "hidden",
        backgroundColor: t.surfaceRaised,
        position: "relative",
      }}
    >
      {/* Line number gutter */}
      <div
        ref={gutterRef}
        style={{
          width: gutterWidth,
          flexShrink: 0,
          overflow: "hidden",
          backgroundColor: t.surfaceRaised,
          borderRight: `1px solid ${t.surfaceBorder}`,
          paddingTop: 8,
          userSelect: "none",
        }}
      >
        {lines.map((_, i) => (
          <div
            key={i}
            style={{
              height: EDITOR_LINE_HEIGHT_PX,
              lineHeight: EDITOR_LINE_HEIGHT,
              textAlign: "right",
              paddingRight: 10,
              fontSize: EDITOR_FONT_SIZE,
              fontFamily: EDITOR_FONT,
              color: t.textDim,
            }}
          >
            {i + 1}
          </div>
        ))}
      </div>

      {/* Editor area with highlight + textarea */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        {/* Syntax highlight layer (behind textarea) */}
        {highlightedLines && (
          <pre
            ref={highlightRef}
            aria-hidden
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              margin: 0,
              padding: EDITOR_PADDING,
              fontSize: EDITOR_FONT_SIZE,
              lineHeight: EDITOR_LINE_HEIGHT,
              fontFamily: EDITOR_FONT,
              color: t.text,
              overflow: "auto",
              pointerEvents: "none",
              whiteSpace: "pre",
              wordWrap: "normal",
              tabSize: 2,
            }}
          >
            {highlightedLines}
          </pre>
        )}

        {/* Textarea (transparent text when highlighting is active) */}
        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => onChange(e.target.value)}
          onScroll={handleScroll}
          wrap="off"
          spellCheck={false}
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            padding: EDITOR_PADDING,
            backgroundColor: "transparent",
            color: highlightedLines ? "transparent" : t.text,
            caretColor: t.text,
            fontSize: EDITOR_FONT_SIZE,
            lineHeight: EDITOR_LINE_HEIGHT,
            fontFamily: EDITOR_FONT,
            border: "none",
            outline: "none",
            resize: "none",
            tabSize: 2,
            overflow: "auto",
            whiteSpace: "pre",
            wordWrap: "normal",
            WebkitTextFillColor: highlightedLines ? "transparent" : undefined,
            zIndex: 1,
          }}
        />
      </div>
    </div>
  );
}
