/**
 * StepsJsonEditor — syntax-highlighted JSON editor for pipeline steps.
 *
 * Uses the same transparent-textarea-over-highlighted-pre pattern as YamlEditor,
 * but with JSON tokenization and Tailwind styling.
 */
import { useRef, useCallback, useMemo, useState, useEffect } from "react";
import { AlertTriangle, CheckCircle2, Copy, Check } from "lucide-react";
import type { StepDef } from "@/src/api/hooks/useTasks";

// ---------------------------------------------------------------------------
// JSON syntax highlighting
// ---------------------------------------------------------------------------

type TokenType = "key" | "string" | "number" | "boolean" | "null" | "punctuation" | "text";

const TOKEN_CLASSES: Record<TokenType, string> = {
  key: "text-rose-400",
  string: "text-emerald-400",
  number: "text-amber-400",
  boolean: "text-purple-400",
  null: "text-purple-400",
  punctuation: "text-cyan-400",
  text: "text-text",
};

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/**
 * Simple line-by-line JSON highlighter.
 * Not a full parser — works on the pretty-printed output of JSON.stringify.
 */
function highlightJson(text: string): string {
  return text.split("\n").map((line) => {
    let result = "";
    let i = 0;

    while (i < line.length) {
      const ch = line[i];

      // Whitespace
      if (ch === " " || ch === "\t") {
        let ws = "";
        while (i < line.length && (line[i] === " " || line[i] === "\t")) {
          ws += line[i];
          i++;
        }
        result += ws;
        continue;
      }

      // Punctuation: { } [ ] , :
      if ("{}[],:".includes(ch)) {
        result += `<span class="${TOKEN_CLASSES.punctuation}">${escapeHtml(ch)}</span>`;
        i++;
        continue;
      }

      // String (key or value)
      if (ch === '"') {
        let str = '"';
        i++;
        while (i < line.length) {
          if (line[i] === "\\") {
            str += line[i] + (line[i + 1] ?? "");
            i += 2;
          } else if (line[i] === '"') {
            str += '"';
            i++;
            break;
          } else {
            str += line[i];
            i++;
          }
        }
        // Check if this string is a key (followed by colon)
        const rest = line.slice(i).trimStart();
        const isKey = rest.startsWith(":");
        const cls = isKey ? TOKEN_CLASSES.key : TOKEN_CLASSES.string;
        result += `<span class="${cls}">${escapeHtml(str)}</span>`;
        continue;
      }

      // Number
      if (ch === "-" || (ch >= "0" && ch <= "9")) {
        let num = "";
        while (i < line.length && /[0-9eE.+-]/.test(line[i])) {
          num += line[i];
          i++;
        }
        result += `<span class="${TOKEN_CLASSES.number}">${escapeHtml(num)}</span>`;
        continue;
      }

      // Boolean / null
      const remaining = line.slice(i);
      const kwMatch = remaining.match(/^(true|false|null)\b/);
      if (kwMatch) {
        const cls = kwMatch[1] === "null" ? TOKEN_CLASSES.null : TOKEN_CLASSES.boolean;
        result += `<span class="${cls}">${kwMatch[1]}</span>`;
        i += kwMatch[1].length;
        continue;
      }

      // Fallback
      result += escapeHtml(ch);
      i++;
    }

    return result;
  }).join("\n");
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

function validateSteps(text: string): { steps: StepDef[] | null; error: string | null } {
  if (!text.trim()) return { steps: [], error: null };
  try {
    const parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) return { steps: null, error: "Root must be an array of steps" };
    // Basic structural validation
    for (let i = 0; i < parsed.length; i++) {
      const s = parsed[i];
      if (!s || typeof s !== "object") return { steps: null, error: `Step ${i + 1}: must be an object` };
      if (!s.type || !["exec", "tool", "agent"].includes(s.type)) {
        return { steps: null, error: `Step ${i + 1}: type must be "exec", "tool", or "agent"` };
      }
      if (!s.id || typeof s.id !== "string") {
        return { steps: null, error: `Step ${i + 1}: id must be a string` };
      }
    }
    return { steps: parsed, error: null };
  } catch (e: any) {
    // Extract useful position info from JSON parse errors
    const msg = e.message ?? "Invalid JSON";
    return { steps: null, error: msg };
  }
}

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

  // Local text state for editing — syncs from props on mount / external change
  const canonical = useMemo(() => JSON.stringify(steps, null, 2), [steps]);
  const [text, setText] = useState(canonical);
  const [parseError, setParseError] = useState<string | null>(null);

  // Sync from parent when steps change externally (e.g. visual editor changes)
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

  // Sync scroll
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

  // Tab indentation
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const newVal = text.substring(0, start) + "  " + text.substring(end);
      handleChange(newVal);
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + 2;
      });
    }
  }, [text, handleChange]);

  // Copy to clipboard (textarea fallback for non-HTTPS)
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

  // Format / pretty-print
  const handleFormat = useCallback(() => {
    try {
      const parsed = JSON.parse(text);
      const formatted = JSON.stringify(parsed, null, 2);
      handleChange(formatted);
    } catch { /* keep current text if invalid */ }
  }, [text, handleChange]);

  return (
    <div className="flex flex-col gap-2 flex-1 min-h-0">
      {/* Toolbar */}
      <div className="flex flex-row items-center gap-2">
        {/* Validation status */}
        <div className={`flex flex-row items-center gap-1.5 px-2 py-1 rounded-md text-xs ${
          parseError
            ? "bg-red-500/10 text-red-400 border border-red-500/20"
            : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
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

        {/* Actions */}
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
          {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      {/* Editor */}
      <div className={`relative flex flex-row rounded-lg border overflow-hidden min-h-[300px] max-h-[600px] ${
        parseError ? "border-red-500/30" : "border-surface-border"
      } bg-[#0d1117]`}>
        {/* Line numbers */}
        <div
          ref={lineNumRef}
          aria-hidden
          className="w-10 shrink-0 text-right text-text-dim/50 select-none pointer-events-none overflow-hidden border-r border-surface-border/30"
          style={{
            paddingTop: 16,
            paddingRight: 8,
            fontFamily: "monospace",
            fontSize: 13,
            lineHeight: "1.6",
          }}
        >
          {Array.from({ length: lineCount }, (_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>

        {/* Code area — pre and textarea MUST share identical font metrics */}
        <div className="relative flex-1 min-w-0">
          {/* Highlighted pre (background) */}
          <pre
            ref={preRef}
            aria-hidden
            className="absolute inset-0 m-0 overflow-auto pointer-events-none"
            style={{
              padding: "16px 16px 16px 12px",
              fontFamily: "monospace",
              fontSize: 13,
              lineHeight: "1.6",
              whiteSpace: "pre",
              wordWrap: "normal",
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
            className="absolute inset-0 w-full h-full m-0 bg-transparent border-none outline-none resize-none caret-text"
            style={{
              padding: "16px 16px 16px 12px",
              fontFamily: "monospace",
              fontSize: 13,
              lineHeight: "1.6",
              color: "transparent",
              WebkitTextFillColor: "transparent",
              whiteSpace: "pre",
              wordWrap: "normal",
              overflow: "auto",
              tabSize: 2,
            }}
          />
        </div>
      </div>
    </div>
  );
}
