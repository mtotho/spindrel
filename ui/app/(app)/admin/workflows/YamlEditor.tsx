/**
 * YAML editor with syntax highlighting and live validation.
 *
 * Uses a transparent textarea overlaid on a highlighted <pre> element.
 * Highlights YAML keys, strings, numbers, booleans, comments, and template variables.
 */
import { useRef, useCallback, useMemo } from "react";
import { type ThemeTokens } from "@/src/theme/tokens";
import { AlertTriangle, CheckCircle } from "lucide-react";

// Shared font metrics — pre and textarea MUST match or the cursor drifts.
// Global CSS forces textarea { font-size: 16px !important } for iOS zoom
// prevention, so both layers use 16px.
const FONT = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace";
const FONT_SIZE = 16;
const LINE_HEIGHT = "1.5";
const PADDING = "12px 16px 12px 12px";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface YamlEditorProps {
  value: string;
  onChange: (text: string) => void;
  parseError: string | null;
  t: ThemeTokens;
  /** Min height in px (default 400) */
  minHeight?: number;
}

/** Read-only syntax-highlighted YAML display (for export modal, previews, etc.) */
interface YamlViewerProps {
  value: string;
  t: ThemeTokens;
}

// ---------------------------------------------------------------------------
// YAML syntax colors (theme-aware)
// ---------------------------------------------------------------------------

function syntaxColors(t: ThemeTokens) {
  // Detect dark vs light by checking surface color
  const isDark = t.surface === "#111111";
  return {
    key: isDark ? "#e06c75" : "#c7254e",         // red — YAML keys
    string: isDark ? "#98c379" : "#50a14f",       // green — quoted strings
    number: isDark ? "#d19a66" : "#986801",       // orange — numbers
    boolean: isDark ? "#c678dd" : "#7c3aed",      // purple — true/false/null
    comment: isDark ? "#5c6370" : "#a0a1a7",      // gray — comments
    punctuation: isDark ? "#56b6c2" : "#0184bc",  // cyan — colons, dashes
    template: isDark ? "#e5c07b" : "#c18401",     // yellow — {{variables}}
    text: t.inputText,                            // default text
  };
}

// ---------------------------------------------------------------------------
// Tokenizer — line-by-line YAML highlighting
// ---------------------------------------------------------------------------

type TokenType = "key" | "string" | "number" | "boolean" | "comment" | "punctuation" | "template" | "text";

interface Token {
  type: TokenType;
  text: string;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function tokenizeLine(line: string): Token[] {
  const tokens: Token[] = [];
  let remaining = line;

  // Full-line comment
  if (/^\s*#/.test(remaining)) {
    return [{ type: "comment", text: remaining }];
  }

  // Leading whitespace
  const leadMatch = remaining.match(/^(\s+)/);
  if (leadMatch) {
    tokens.push({ type: "text", text: leadMatch[1] });
    remaining = remaining.slice(leadMatch[1].length);
  }

  // List dash prefix
  const dashMatch = remaining.match(/^(-\s)/);
  if (dashMatch) {
    tokens.push({ type: "punctuation", text: dashMatch[1] });
    remaining = remaining.slice(dashMatch[1].length);
  }

  // Key: value pair
  const keyMatch = remaining.match(/^([a-zA-Z_][\w.-]*)\s*(:)/);
  if (keyMatch) {
    tokens.push({ type: "key", text: keyMatch[1] });
    tokens.push({ type: "punctuation", text: keyMatch[2] });
    remaining = remaining.slice(keyMatch[0].length);
  }

  // Tokenize the rest of the line
  while (remaining.length > 0) {
    // Template variable {{...}}
    const tmplMatch = remaining.match(/^(\{\{[^}]*\}\})/);
    if (tmplMatch) {
      tokens.push({ type: "template", text: tmplMatch[1] });
      remaining = remaining.slice(tmplMatch[1].length);
      continue;
    }

    // Inline comment (only after whitespace to avoid # in strings)
    const commentMatch = remaining.match(/^(\s+#.*)$/);
    if (commentMatch) {
      tokens.push({ type: "comment", text: commentMatch[1] });
      remaining = "";
      continue;
    }

    // Double-quoted string
    const dqMatch = remaining.match(/^("(?:[^"\\]|\\.)*")/);
    if (dqMatch) {
      tokens.push({ type: "string", text: dqMatch[1] });
      remaining = remaining.slice(dqMatch[1].length);
      continue;
    }

    // Single-quoted string
    const sqMatch = remaining.match(/^('(?:[^'\\]|\\.)*')/);
    if (sqMatch) {
      tokens.push({ type: "string", text: sqMatch[1] });
      remaining = remaining.slice(sqMatch[1].length);
      continue;
    }

    // Boolean / null
    const boolMatch = remaining.match(/^(true|false|null|yes|no|on|off)\b/i);
    if (boolMatch) {
      tokens.push({ type: "boolean", text: boolMatch[1] });
      remaining = remaining.slice(boolMatch[1].length);
      continue;
    }

    // Number
    const numMatch = remaining.match(/^(-?\d+(?:\.\d+)?)\b/);
    if (numMatch) {
      tokens.push({ type: "number", text: numMatch[1] });
      remaining = remaining.slice(numMatch[1].length);
      continue;
    }

    // Block scalar indicators
    const blockMatch = remaining.match(/^(\s*[|>][-+]?\s*)$/);
    if (blockMatch) {
      tokens.push({ type: "punctuation", text: blockMatch[1] });
      remaining = "";
      continue;
    }

    // Plain text — consume as many non-special chars as possible in one batch
    const plainMatch = remaining.match(/^([^{'"#\d\s-][^{'"#]*)/) || remaining.match(/^(\s+)/) || remaining.match(/^(.)/);
    if (plainMatch) {
      tokens.push({ type: "text", text: plainMatch[1] });
      remaining = remaining.slice(plainMatch[1].length);
    }
  }

  return tokens;
}

function highlightYaml(text: string, colors: Record<TokenType, string>): string {
  return text.split("\n").map((line) => {
    const tokens = tokenizeLine(line);
    return tokens.map((tok) => {
      const escaped = escapeHtml(tok.text);
      if (tok.type === "text") return escaped;
      return `<span style="color:${colors[tok.type]}">${escaped}</span>`;
    }).join("");
  }).join("\n");
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function YamlSyntaxEditor({ value, onChange, parseError, t, minHeight = 400 }: YamlEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const lineNumRef = useRef<HTMLDivElement>(null);
  const colors = syntaxColors(t);
  const lineCount = (value || "").split("\n").length;
  const isEmpty = !(value || "").trim();

  const highlighted = useMemo(
    () => highlightYaml(value || "", colors),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [value, t.surface],
  );

  // Sync scroll between textarea, pre, and line numbers
  const handleScroll = useCallback(() => {
    if (textareaRef.current) {
      const { scrollTop, scrollLeft } = textareaRef.current;
      if (preRef.current) {
        preRef.current.scrollTop = scrollTop;
        preRef.current.scrollLeft = scrollLeft;
      }
      if (lineNumRef.current) {
        lineNumRef.current.scrollTop = scrollTop;
      }
    }
  }, []);

  // Handle tab key for indentation
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const newVal = value.substring(0, start) + "  " + value.substring(end);
      onChange(newVal);
      // Restore cursor after React re-render
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + 2;
      });
    }
  }, [value, onChange]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: 1, minHeight: 0 }}>
      {/* Status bar */}
      {!isEmpty && (
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
          padding: "4px 8px", borderRadius: 6,
          background: parseError ? t.dangerSubtle : t.successSubtle,
          border: `1px solid ${parseError ? t.dangerBorder : t.successBorder}`,
          flexShrink: 0,
        }}>
          {parseError ? (
            <>
              <AlertTriangle size={13} color={t.danger} />
              <span style={{ fontSize: 12, fontFamily: "monospace", color: t.danger, flex: 1 }}>
                {parseError}
              </span>
            </>
          ) : (
            <>
              <CheckCircle size={13} color={t.success} />
              <span style={{ fontSize: 12, color: t.success }}>Valid YAML</span>
              <span style={{ fontSize: 11, color: t.textDim, marginLeft: "auto" }}>
                {lineCount} lines
              </span>
            </>
          )}
        </div>
      )}

      {/* Editor container */}
      <div
        style={{
          position: "relative",
          flex: 1,
          minHeight,
          borderRadius: 8,
          border: `1px solid ${parseError ? t.dangerBorder : t.inputBorder}`,
          background: t.codeBg,
          overflow: "hidden",
          display: "flex", flexDirection: "row",
        }}
      >
        {/* Line numbers — scrolls with content */}
        <div
          ref={lineNumRef}
          aria-hidden
          style={{
            width: 44, flexShrink: 0,
            padding: PADDING,
            paddingRight: 8,
            textAlign: "right",
            fontFamily: FONT, fontSize: FONT_SIZE, lineHeight: LINE_HEIGHT,
            color: t.textDim, userSelect: "none", pointerEvents: "none",
            overflow: "hidden",
            borderRight: `1px solid ${t.surfaceBorder}`,
            background: t.codeBg,
          }}
        >
          {Array.from({ length: lineCount }, (_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>

        {/* Code area (pre + textarea layered) */}
        <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
          {/* Highlighted pre (background layer) */}
          <pre
            ref={preRef}
            aria-hidden
            style={{
              position: "absolute",
              top: 0, left: 0, right: 0, bottom: 0,
              margin: 0,
              padding: PADDING,
              fontFamily: FONT,
              fontSize: FONT_SIZE,
              lineHeight: LINE_HEIGHT,
              color: colors.text,
              overflow: "auto",
              whiteSpace: "pre",
              wordWrap: "normal",
              pointerEvents: "none",
              tabSize: 2,
            }}
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: highlighted + "\n" }}
          />

          {/* Textarea (foreground — invisible text, handles input) */}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onScroll={handleScroll}
            onKeyDown={handleKeyDown}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            style={{
              position: "absolute",
              top: 0, left: 0, right: 0, bottom: 0,
              width: "100%",
              height: "100%",
              margin: 0,
              padding: PADDING,
              fontFamily: FONT,
              fontSize: FONT_SIZE,
              lineHeight: LINE_HEIGHT,
              color: "transparent",
              caretColor: t.inputText,
              background: "transparent",
              border: "none",
              outline: "none",
              resize: "none",
              overflow: "auto",
              whiteSpace: "pre",
              wordWrap: "normal",
              WebkitTextFillColor: "transparent",
              tabSize: 2,
            }}
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Read-only viewer (for export modal, etc.)
// ---------------------------------------------------------------------------

export function YamlSyntaxViewer({ value, t }: YamlViewerProps) {
  const colors = syntaxColors(t);
  const highlighted = useMemo(
    () => highlightYaml(value || "", colors),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [value, t.surface],
  );
  const lineCount = (value || "").split("\n").length;

  return (
    <div style={{ display: "flex", flexDirection: "row", overflow: "auto" }}>
      {/* Line numbers */}
      <div
        aria-hidden
        style={{
          width: 36, flexShrink: 0,
          paddingTop: 0, paddingRight: 8,
          textAlign: "right",
          fontFamily: "monospace", fontSize: 12, lineHeight: "1.6",
          color: t.textDim, userSelect: "none",
          borderRight: `1px solid ${t.surfaceBorder}`,
        }}
      >
        {Array.from({ length: lineCount }, (_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      {/* Highlighted content */}
      <pre
        style={{
          margin: 0,
          padding: "0 12px",
          fontFamily: "monospace",
          fontSize: 12,
          lineHeight: "1.6",
          color: colors.text,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          flex: 1,
        }}
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: highlighted }}
      />
    </div>
  );
}
