/**
 * StepsJsonEditor — syntax-highlighted JSON editor for pipeline steps.
 *
 * Uses the transparent-textarea-over-highlighted-pre pattern (same as YamlEditor).
 * The global CSS forces `font-size: 16px !important` on textareas for iOS zoom
 * prevention, so we must use 16px as the shared font size for both layers.
 */
import { useRef, useCallback, useMemo, useState, useEffect } from "react";
import { AlertTriangle, CheckCircle2, Copy, Check } from "lucide-react";
import type { StepDef } from "@/src/api/hooks/useTasks";

// ---------------------------------------------------------------------------
// JSON syntax highlighting
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

const ALLOWED_STEP_TYPES = ["exec", "tool", "agent", "user_prompt", "foreach"] as const;

function validateStepArray(
  arr: any,
  path: string,
): string | null {
  if (!Array.isArray(arr)) return `${path}: must be an array`;
  for (let i = 0; i < arr.length; i++) {
    const s = arr[i];
    const loc = `${path}[${i + 1}]`;
    if (!s || typeof s !== "object") return `${loc}: must be an object`;
    if (!s.type || !ALLOWED_STEP_TYPES.includes(s.type)) {
      return `${loc}: type must be one of ${ALLOWED_STEP_TYPES.join(", ")}`;
    }
    if (!s.id || typeof s.id !== "string") {
      return `${loc}: id must be a string`;
    }
    if (s.type === "foreach" && s.do !== undefined) {
      const sub = validateStepArray(s.do, `${loc}.do`);
      if (sub) return sub;
    }
  }
  return null;
}

function validateSteps(text: string): { steps: StepDef[] | null; error: string | null } {
  if (!text.trim()) return { steps: [], error: null };
  try {
    const parsed = JSON.parse(text);
    const err = validateStepArray(parsed, "Step");
    if (err) return { steps: null, error: err };
    return { steps: parsed, error: null };
  } catch (e: any) {
    return { steps: null, error: e.message ?? "Invalid JSON" };
  }
}

// ---------------------------------------------------------------------------
// Shared font metrics — must match between pre and textarea.
// Global CSS forces textarea { font-size: 16px !important } for iOS zoom
// prevention, so we use 16px everywhere to stay aligned.
// ---------------------------------------------------------------------------

const FONT = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace";
const FONT_SIZE = 16;
const LINE_HEIGHT = "1.5";
const PADDING = "12px 16px 12px 12px";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface StepsJsonEditorProps {
  steps: StepDef[];
  onChange: (steps: StepDef[]) => void;
  readOnly?: boolean;
}

export function StepsJsonEditor({ steps, onChange, readOnly }: StepsJsonEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const lineNumRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  const canonical = useMemo(() => JSON.stringify(steps, null, 2), [steps]);
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

  const lineCount = text.split("\n").length;
  const highlighted = useMemo(() => highlightJson(text), [text]);

  const handleChange = useCallback((newText: string) => {
    setText(newText);
    const { steps: parsed, error } = validateSteps(newText);
    setParseError(error);
    if (parsed && !error) {
      lastCanonicalRef.current = JSON.stringify(parsed, null, 2);
      onChange(parsed);
    }
  }, [onChange]);

  const handleScroll = useCallback(() => {
    if (!textareaRef.current) return;
    const { scrollTop, scrollLeft } = textareaRef.current;
    if (preRef.current) { preRef.current.scrollTop = scrollTop; preRef.current.scrollLeft = scrollLeft; }
    if (lineNumRef.current) { lineNumRef.current.scrollTop = scrollTop; }
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

  const handleCopy = useCallback(() => {
    const el = document.createElement("textarea");
    el.value = text;
    el.style.position = "fixed";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    document.body.removeChild(el);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  const handleFormat = useCallback(() => {
    try {
      const parsed = JSON.parse(text);
      handleChange(JSON.stringify(parsed, null, 2));
    } catch { /* keep current text */ }
  }, [text, handleChange]);

  return (
    <div className="flex flex-col gap-2 flex-1 min-h-0">
      {/* Toolbar */}
      <div className="flex flex-row items-center gap-2 flex-wrap">
        <div className={`flex flex-row items-center gap-1.5 px-2 py-1 rounded-md text-xs ${
          parseError
            ? "bg-danger/10 text-danger"
            : "bg-success/10 text-success"
        }`}>
          {parseError ? (
            <>
              <AlertTriangle size={12} />
              <span className="font-mono truncate max-w-[300px]">{parseError}</span>
            </>
          ) : (
            <>
              <CheckCircle2 size={12} />
              <span>Valid</span>
              <span className="text-text-dim ml-1">{steps.length} step{steps.length !== 1 ? "s" : ""}</span>
            </>
          )}
        </div>
        <div className="flex-1" />
        {!readOnly && (
          <button
            onClick={handleFormat}
            className="px-2 py-1 text-[11px] text-text-dim bg-transparent border border-surface-border rounded-md cursor-pointer hover:text-text hover:border-accent/40 transition-colors"
          >
            Format
          </button>
        )}
        <button
          onClick={handleCopy}
          className="flex flex-row items-center gap-1 px-2 py-1 text-[11px] text-text-dim bg-transparent border border-surface-border rounded-md cursor-pointer hover:text-text hover:border-accent/40 transition-colors"
        >
          {copied ? <Check size={11} className="text-success" /> : <Copy size={11} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      {/* Editor */}
      <div
        style={{
          position: "relative",
          display: "flex",
          flexDirection: "row",
          minHeight: 300,
          maxHeight: 600,
          borderRadius: 8,
          border: `1px solid ${parseError ? "rgb(var(--color-danger) / 0.30)" : "rgb(var(--color-input-border))"}`,
          background: "rgb(var(--color-input-bg))",
          overflow: "hidden",
        }}
      >
        {/* Line numbers */}
        <div
          ref={lineNumRef}
          aria-hidden
          style={{
            width: 44,
            flexShrink: 0,
            padding: PADDING,
            paddingRight: 8,
            textAlign: "right",
            fontFamily: FONT,
            fontSize: FONT_SIZE,
            lineHeight: LINE_HEIGHT,
            color: "rgb(var(--color-text-dim) / 0.65)",
            userSelect: "none",
            pointerEvents: "none",
            overflow: "hidden",
            borderRight: "1px solid rgb(var(--color-surface-border) / 0.70)",
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
              color: TOKEN_COLORS.text,
              overflow: "auto",
              whiteSpace: "pre",
              wordWrap: "normal",
              pointerEvents: "none",
              tabSize: 2,
            }}
            dangerouslySetInnerHTML={{ __html: highlighted + "\n" }}
          />

          {/* Textarea (foreground — invisible text, handles input) */}
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
              caretColor: "rgb(var(--color-input-text))",
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
