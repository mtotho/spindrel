import { useCallback, useMemo, useRef } from "react";
import type { CSSProperties, KeyboardEvent } from "react";
import { CheckCircle, AlertTriangle, Info } from "lucide-react";

import { useThemeTokens } from "@/src/theme/tokens";

export type SourceLanguage = "yaml" | "json" | "python" | "markdown" | "text";

export interface SourceTextStatus {
  variant: "success" | "danger" | "neutral";
  label: string;
}

interface SourceTextEditorProps {
  value: string;
  language?: SourceLanguage;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  minHeight?: number;
  maxHeight?: number;
  showLineNumbers?: boolean;
  status?: SourceTextStatus | null;
  searchQuery?: string;
  placeholder?: string;
  className?: string;
}

type TokenType =
  | "key"
  | "string"
  | "number"
  | "boolean"
  | "comment"
  | "punctuation"
  | "keyword"
  | "heading"
  | "list"
  | "blockquote"
  | "code"
  | "text";

interface Token {
  type: TokenType;
  text: string;
}

const FONT = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace";
const FONT_SIZE = 16;
const LINE_HEIGHT = 1.5;
const PADDING = "12px 16px 12px 12px";

export function inferSourceLanguage(path: string): SourceLanguage {
  const lower = path.toLowerCase();
  if (lower.endsWith(".yaml") || lower.endsWith(".yml") || lower.endsWith(".toml")) return "yaml";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".py")) return "python";
  if (lower.endsWith(".md") || lower.endsWith(".markdown") || lower.endsWith(".rst")) return "markdown";
  return "text";
}

function tokenizeYaml(line: string): Token[] {
  if (/^\s*#/.test(line)) return [{ type: "comment", text: line }];

  const tokens: Token[] = [];
  let remaining = line;
  const leading = remaining.match(/^(\s+)/);
  if (leading) {
    tokens.push({ type: "text", text: leading[1] });
    remaining = remaining.slice(leading[1].length);
  }

  const list = remaining.match(/^(-\s+)/);
  if (list) {
    tokens.push({ type: "punctuation", text: list[1] });
    remaining = remaining.slice(list[1].length);
  }

  const key = remaining.match(/^([a-zA-Z_][\w.-]*)(\s*:\s*)/);
  if (key) {
    tokens.push({ type: "key", text: key[1] });
    tokens.push({ type: "punctuation", text: key[2] });
    remaining = remaining.slice(key[0].length);
  }

  while (remaining.length > 0) {
    const template = remaining.match(/^(\{\{[^}]*\}\})/);
    if (template) {
      tokens.push({ type: "keyword", text: template[1] });
      remaining = remaining.slice(template[1].length);
      continue;
    }

    const inlineComment = remaining.match(/^(\s+#.*)$/);
    if (inlineComment) {
      tokens.push({ type: "comment", text: inlineComment[1] });
      break;
    }

    const quoted = remaining.match(/^("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/);
    if (quoted) {
      tokens.push({ type: "string", text: quoted[1] });
      remaining = remaining.slice(quoted[1].length);
      continue;
    }

    const bool = remaining.match(/^(true|false|null|yes|no|on|off)\b/i);
    if (bool) {
      tokens.push({ type: "boolean", text: bool[1] });
      remaining = remaining.slice(bool[1].length);
      continue;
    }

    const number = remaining.match(/^(-?\d+(?:\.\d+)?)\b/);
    if (number) {
      tokens.push({ type: "number", text: number[1] });
      remaining = remaining.slice(number[1].length);
      continue;
    }

    const block = remaining.match(/^(\s*[|>][-+]?\s*)$/);
    if (block) {
      tokens.push({ type: "punctuation", text: block[1] });
      break;
    }

    const plain = remaining.match(/^([^{'"#\d\s-][^{'"#]*)/) || remaining.match(/^(\s+)/) || remaining.match(/^(.)/);
    if (!plain) break;
    tokens.push({ type: "text", text: plain[1] });
    remaining = remaining.slice(plain[1].length);
  }

  return tokens.length ? tokens : [{ type: "text", text: line }];
}

function tokenizeJson(line: string): Token[] {
  const tokens: Token[] = [];
  const pattern = /("(?:[^"\\]|\\.)*")\s*(:)?|(-?\d+\.?\d*(?:[eE][+-]?\d+)?)|(\btrue\b|\bfalse\b|\bnull\b)|([{}[\],:])/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(line)) !== null) {
    if (match.index > lastIndex) tokens.push({ type: "text", text: line.slice(lastIndex, match.index) });
    if (match[1]) {
      tokens.push({ type: match[2] ? "key" : "string", text: match[1] });
      if (match[2]) tokens.push({ type: "punctuation", text: match[2] });
    } else if (match[3]) {
      tokens.push({ type: "number", text: match[3] });
    } else if (match[4]) {
      tokens.push({ type: "boolean", text: match[4] });
    } else if (match[5]) {
      tokens.push({ type: "punctuation", text: match[5] });
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < line.length) tokens.push({ type: "text", text: line.slice(lastIndex) });
  return tokens.length ? tokens : [{ type: "text", text: line }];
}

function tokenizePython(line: string): Token[] {
  if (/^\s*#/.test(line)) return [{ type: "comment", text: line }];

  const tokens: Token[] = [];
  const pattern = /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|\b(def|class|import|from|return|if|elif|else|for|while|try|except|finally|with|as|in|not|and|or|is|lambda|yield|raise|pass|break|continue|True|False|None|self|async|await)\b|(\b\d+\.?\d*\b)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(line)) !== null) {
    if (match.index > lastIndex) tokens.push({ type: "text", text: line.slice(lastIndex, match.index) });
    if (match[1]) tokens.push({ type: "string", text: match[1] });
    else if (match[2]) tokens.push({ type: "keyword", text: match[2] });
    else if (match[3]) tokens.push({ type: "number", text: match[3] });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < line.length) tokens.push({ type: "text", text: line.slice(lastIndex) });
  return tokens.length ? tokens : [{ type: "text", text: line }];
}

function tokenizeMarkdown(line: string): Token[] {
  const heading = line.match(/^(#{1,6}\s+)(.*)/);
  if (heading) return [{ type: "punctuation", text: heading[1] }, { type: "heading", text: heading[2] }];
  if (/^```/.test(line)) return [{ type: "code", text: line }];
  if (/^>\s?/.test(line)) return [{ type: "blockquote", text: line }];

  const list = line.match(/^(\s*)([-*]\s+|(\d+\.)\s+)(.*)/);
  if (list) {
    return [
      { type: "text", text: list[1] },
      { type: "list", text: list[2] },
      { type: "text", text: list[4] || "" },
    ];
  }

  return [{ type: "text", text: line }];
}

function tokenizeLine(line: string, language: SourceLanguage): Token[] {
  switch (language) {
    case "yaml":
      return tokenizeYaml(line);
    case "json":
      return tokenizeJson(line);
    case "python":
      return tokenizePython(line);
    case "markdown":
      return tokenizeMarkdown(line);
    default:
      return [{ type: "text", text: line }];
  }
}

function statusClasses(status: SourceTextStatus) {
  switch (status.variant) {
    case "success":
      return "border-success-border bg-success-subtle text-success";
    case "danger":
      return "border-danger-border bg-danger-subtle text-danger";
    default:
      return "border-surface-border bg-surface-overlay/35 text-text-muted";
  }
}

function tokenColor(type: TokenType, t: ReturnType<typeof useThemeTokens>): string {
  switch (type) {
    case "key":
      return t.dangerMuted;
    case "string":
      return t.success;
    case "number":
      return t.warningMuted;
    case "boolean":
    case "keyword":
      return t.purpleMuted;
    case "comment":
      return t.textDim;
    case "punctuation":
    case "list":
      return t.accent;
    case "heading":
      return t.text;
    case "blockquote":
      return t.textMuted;
    case "code":
      return t.warningMuted;
    default:
      return t.inputText;
  }
}

function splitSearch(text: string, query?: string) {
  const term = query?.trim();
  if (!term) return [{ text, match: false }];

  const lower = text.toLowerCase();
  const needle = term.toLowerCase();
  const parts: Array<{ text: string; match: boolean }> = [];
  let index = 0;

  while (index < text.length) {
    const found = lower.indexOf(needle, index);
    if (found < 0) {
      parts.push({ text: text.slice(index), match: false });
      break;
    }
    if (found > index) parts.push({ text: text.slice(index, found), match: false });
    parts.push({ text: text.slice(found, found + term.length), match: true });
    index = found + term.length;
  }

  return parts.length ? parts : [{ text, match: false }];
}

export function SourceTextEditor({
  value,
  language = "text",
  onChange,
  readOnly = false,
  minHeight = 360,
  maxHeight,
  showLineNumbers = true,
  status,
  searchQuery,
  placeholder,
  className = "",
}: SourceTextEditorProps) {
  const t = useThemeTokens();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const lineNumRef = useRef<HTMLDivElement>(null);
  const text = value || "";
  const lines = useMemo(() => text.split("\n"), [text]);
  const lineCount = lines.length;
  const canEdit = !readOnly && Boolean(onChange);

  const highlightedLines = useMemo(
    () => lines.map((line) => tokenizeLine(line, language)),
    [language, lines],
  );

  const handleScroll = useCallback(() => {
    if (!textareaRef.current) return;
    const { scrollTop, scrollLeft } = textareaRef.current;
    if (preRef.current) {
      preRef.current.scrollTop = scrollTop;
      preRef.current.scrollLeft = scrollLeft;
    }
    if (lineNumRef.current) {
      lineNumRef.current.scrollTop = scrollTop;
    }
  }, []);

  const handleReadOnlyScroll = useCallback(() => {
    if (!preRef.current || !lineNumRef.current) return;
    lineNumRef.current.scrollTop = preRef.current.scrollTop;
  }, []);

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Tab" || !onChange) return;
    event.preventDefault();
    const target = event.currentTarget;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const next = text.substring(0, start) + "  " + text.substring(end);
    onChange(next);
    requestAnimationFrame(() => {
      target.selectionStart = target.selectionEnd = start + 2;
    });
  }, [onChange, text]);

  const gutterWidth = showLineNumbers ? Math.max(44, String(lineCount).length * 9 + 24) : 0;
  const contentStyle: CSSProperties = {
    fontFamily: FONT,
    fontSize: FONT_SIZE,
    lineHeight: LINE_HEIGHT,
    tabSize: 2,
  };

  const statusIcon = status?.variant === "success"
    ? <CheckCircle size={13} />
    : status?.variant === "danger"
      ? <AlertTriangle size={13} />
      : <Info size={13} />;

  return (
    <div className={`flex min-h-0 flex-col gap-2 ${className}`}>
      {status && (
        <div className={`flex min-h-[28px] items-center gap-1.5 rounded-md border px-2 text-[12px] ${statusClasses(status)}`}>
          {statusIcon}
          <span className="min-w-0 truncate font-mono">{status.label}</span>
          <span className="ml-auto shrink-0 text-[11px] opacity-70">{lineCount} lines</span>
        </div>
      )}

      <div
        className="relative flex min-w-0 overflow-hidden rounded-md border bg-input focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/25"
        style={{
          minHeight,
          maxHeight,
          borderColor: status?.variant === "danger" ? t.dangerBorder : t.inputBorder,
          background: t.inputBg,
        }}
      >
        {showLineNumbers && (
          <div
            ref={lineNumRef}
            aria-hidden
            className="shrink-0 select-none overflow-hidden text-right"
            style={{
              width: gutterWidth,
              padding: PADDING,
              paddingRight: 8,
              ...contentStyle,
              color: t.textDim,
              borderRight: `1px solid ${t.surfaceBorder}`,
              background: t.inputBg,
            }}
          >
            {Array.from({ length: lineCount }, (_, index) => (
              <div key={index}>{index + 1}</div>
            ))}
          </div>
        )}

        <div className="relative min-w-0 flex-1">
          <pre
            ref={preRef}
            aria-hidden={canEdit}
            onScroll={canEdit ? undefined : handleReadOnlyScroll}
            className="absolute inset-0 m-0 overflow-auto whitespace-pre"
            style={{
              ...contentStyle,
              padding: PADDING,
              color: t.inputText,
              pointerEvents: canEdit ? "none" : "auto",
            }}
          >
            {text ? highlightedLines.map((tokens, lineIndex) => (
              <div key={lineIndex}>
                {tokens.map((token, tokenIndex) => (
                  <span key={tokenIndex} style={{ color: tokenColor(token.type, t) }}>
                    {splitSearch(token.text, searchQuery).map((part, partIndex) => (
                      part.match ? (
                        <mark
                          key={partIndex}
                          className="rounded bg-warning/30 text-text"
                        >
                          {part.text}
                        </mark>
                      ) : (
                        <span key={partIndex}>{part.text}</span>
                      )
                    ))}
                  </span>
                ))}
                {tokens.length === 0 ? " " : null}
              </div>
            )) : (
              <span style={{ color: t.textDim }}>{placeholder || ""}</span>
            )}
          </pre>

          {canEdit && (
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(event) => onChange?.(event.target.value)}
              onScroll={handleScroll}
              onKeyDown={handleKeyDown}
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              className="absolute inset-0 m-0 h-full w-full resize-none overflow-auto border-0 bg-transparent outline-none"
              style={{
                ...contentStyle,
                padding: PADDING,
                color: "transparent",
                caretColor: t.inputText,
                WebkitTextFillColor: "transparent",
                whiteSpace: "pre",
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
