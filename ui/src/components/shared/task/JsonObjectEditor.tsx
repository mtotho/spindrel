/**
 * JsonObjectEditor — compact syntax-highlighted JSON editor for a single object.
 *
 * Used for step fields like widget_template, widget_args, and response_schema
 * where the value is a dict (not an array of steps). Shares the transparent-
 * textarea-over-highlighted-pre pattern with StepsJsonEditor.
 */
import { useRef, useCallback, useMemo, useState, useEffect } from "react";
import { AlertTriangle, Copy, Check } from "lucide-react";

type TokenType = "key" | "string" | "number" | "boolean" | "null" | "punctuation" | "text";

const TOKEN_COLORS: Record<TokenType, string> = {
  key: "rgb(var(--color-danger-muted))",
  string: "rgb(var(--color-success))",
  number: "rgb(var(--color-warning-muted))",
  boolean: "rgb(var(--color-purple))",
  null: "rgb(var(--color-purple))",
  punctuation: "rgb(var(--color-accent))",
  text: "rgb(var(--color-input-text))",
};

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function highlightJson(text: string): string {
  return text.split("\n").map((line) => {
    let result = "";
    let i = 0;
    while (i < line.length) {
      const ch = line[i];
      if (ch === " " || ch === "\t") {
        let ws = "";
        while (i < line.length && (line[i] === " " || line[i] === "\t")) { ws += line[i]; i++; }
        result += ws;
        continue;
      }
      if ("{}[],:".includes(ch)) {
        result += `<span style="color:${TOKEN_COLORS.punctuation}">${escapeHtml(ch)}</span>`;
        i++;
        continue;
      }
      if (ch === '"') {
        let str = '"';
        i++;
        while (i < line.length) {
          if (line[i] === "\\") { str += line[i] + (line[i + 1] ?? ""); i += 2; }
          else if (line[i] === '"') { str += '"'; i++; break; }
          else { str += line[i]; i++; }
        }
        const rest = line.slice(i).trimStart();
        const isKey = rest.startsWith(":");
        const color = isKey ? TOKEN_COLORS.key : TOKEN_COLORS.string;
        result += `<span style="color:${color}">${escapeHtml(str)}</span>`;
        continue;
      }
      if (ch === "-" || (ch >= "0" && ch <= "9")) {
        let num = "";
        while (i < line.length && /[0-9eE.+-]/.test(line[i])) { num += line[i]; i++; }
        result += `<span style="color:${TOKEN_COLORS.number}">${escapeHtml(num)}</span>`;
        continue;
      }
      const remaining = line.slice(i);
      const kwMatch = remaining.match(/^(true|false|null)\b/);
      if (kwMatch) {
        const color = kwMatch[1] === "null" ? TOKEN_COLORS.null : TOKEN_COLORS.boolean;
        result += `<span style="color:${color}">${kwMatch[1]}</span>`;
        i += kwMatch[1].length;
        continue;
      }
      result += escapeHtml(ch);
      i++;
    }
    return result;
  }).join("\n");
}

const FONT = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace";
const FONT_SIZE = 16;
const LINE_HEIGHT = "1.5";
const PADDING = "10px 12px";

interface JsonObjectEditorProps {
  value: Record<string, any> | null | undefined;
  onChange: (next: Record<string, any> | null) => void;
  readOnly?: boolean;
  placeholder?: string;
  /** Label above the editor. */
  label?: string;
  /** Skeleton to insert when user clicks "Insert schema". */
  schemaSkeleton?: Record<string, any>;
  schemaLabel?: string;
  /** Help text shown under the label. */
  hint?: string;
  minHeight?: number;
  maxHeight?: number;
}

export function JsonObjectEditor({
  value,
  onChange,
  readOnly,
  placeholder,
  label,
  schemaSkeleton,
  schemaLabel = "Insert schema",
  hint,
  minHeight = 120,
  maxHeight = 320,
}: JsonObjectEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);

  const canonical = useMemo(
    () => (value && Object.keys(value).length > 0 ? JSON.stringify(value, null, 2) : ""),
    [value],
  );
  const [text, setText] = useState(canonical);
  const [parseError, setParseError] = useState<string | null>(null);

  const lastCanonicalRef = useRef(canonical);
  useEffect(() => {
    if (canonical !== lastCanonicalRef.current) {
      lastCanonicalRef.current = canonical;
      setText(canonical);
      setParseError(null);
    }
  }, [canonical]);

  const highlighted = useMemo(() => highlightJson(text || ""), [text]);

  const handleChange = useCallback((next: string) => {
    setText(next);
    if (!next.trim()) {
      setParseError(null);
      lastCanonicalRef.current = "";
      onChange(null);
      return;
    }
    try {
      const parsed = JSON.parse(next);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        setParseError("Must be a JSON object");
        return;
      }
      setParseError(null);
      lastCanonicalRef.current = JSON.stringify(parsed, null, 2);
      onChange(parsed);
    } catch (e: any) {
      setParseError(e.message ?? "Invalid JSON");
    }
  }, [onChange]);

  const handleScroll = useCallback(() => {
    if (!textareaRef.current || !preRef.current) return;
    preRef.current.scrollTop = textareaRef.current.scrollTop;
    preRef.current.scrollLeft = textareaRef.current.scrollLeft;
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const newVal = text.substring(0, start) + "  " + text.substring(end);
      handleChange(newVal);
      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = start + 2; });
    }
  }, [text, handleChange]);

  const insertSchema = useCallback(() => {
    if (!schemaSkeleton) return;
    handleChange(JSON.stringify(schemaSkeleton, null, 2));
  }, [schemaSkeleton, handleChange]);

  const handleCopy = useCallback(() => {
    if (!text) return;
    const el = document.createElement("textarea");
    el.value = text;
    el.style.position = "fixed";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    document.body.removeChild(el);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [text]);

  return (
    <div className="flex flex-col gap-1.5">
      {(label || schemaSkeleton || hint) && (
        <div className="flex flex-row items-center gap-2">
          {label && (
            <label className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">
              {label}
            </label>
          )}
          {hint && (
            <span className="text-[10px] text-text-dim opacity-70">{hint}</span>
          )}
          <div className="flex-1" />
          {!readOnly && schemaSkeleton && !text.trim() && (
            <button
              type="button"
              onClick={insertSchema}
              className="px-2 py-0.5 text-[10px] text-text-dim bg-transparent border border-surface-border rounded cursor-pointer hover:text-text hover:border-accent/40 transition-colors"
            >
              {schemaLabel}
            </button>
          )}
          {text.trim() && (
            <button
              type="button"
              onClick={handleCopy}
              className="flex flex-row items-center gap-1 px-2 py-0.5 text-[10px] text-text-dim bg-transparent border border-surface-border rounded cursor-pointer hover:text-text hover:border-accent/40 transition-colors"
            >
              {copied ? <Check size={10} className="text-success" /> : <Copy size={10} />}
              {copied ? "Copied" : "Copy"}
            </button>
          )}
        </div>
      )}

      <div
        style={{
          position: "relative",
          minHeight,
          maxHeight,
          borderRadius: 6,
          border: `1px solid ${parseError ? "rgb(var(--color-danger) / 0.35)" : "rgb(var(--color-input-border))"}`,
          background: "rgb(var(--color-input-bg))",
          overflow: "hidden",
        }}
      >
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
            color: TOKEN_COLORS.text,
            overflow: "auto",
            whiteSpace: "pre",
            wordWrap: "normal",
            pointerEvents: "none",
            tabSize: 2,
          }}
          dangerouslySetInnerHTML={{ __html: (highlighted || escapeHtml(placeholder ?? "")) + "\n" }}
        />
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => handleChange(e.target.value)}
          onScroll={handleScroll}
          onKeyDown={handleKeyDown}
          readOnly={readOnly}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          placeholder={placeholder}
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
            color: text ? "transparent" : "rgb(var(--color-text-dim) / 0.70)",
            caretColor: "rgb(var(--color-input-text))",
            background: "transparent",
            border: "none",
            outline: "none",
            resize: "none",
            overflow: "auto",
            whiteSpace: "pre",
            wordWrap: "normal",
            WebkitTextFillColor: text ? "transparent" : undefined,
            tabSize: 2,
          }}
        />
      </div>

      {parseError && (
        <div className="flex flex-row items-center gap-1 text-[10px] text-danger">
          <AlertTriangle size={11} />
          <span className="font-mono">{parseError}</span>
        </div>
      )}
    </div>
  );
}
