import { useState, useRef, useCallback, useEffect } from "react";
import { useCompletions } from "../../api/hooks/useModels";
import type { CompletionItem } from "../../types/api";

interface Props {
  value: string;
  onChange: (text: string) => void;
  label?: string;
  placeholder?: string;
  rows?: number;
  helpText?: string;
}

const TAG_COLORS: Record<string, { bg: string; fg: string }> = {
  skill: { bg: "#1e1b4b", fg: "#a5b4fc" },
  tool: { bg: "#14532d", fg: "#86efac" },
  "tool-pack": { bg: "#14532d", fg: "#86efac" },
  knowledge: { bg: "#3b0764", fg: "#d8b4fe" },
};

const TAG_RE = /(?<![<\w@])@((?:skill|knowledge|tool-pack|tool):)?([A-Za-z_][\w\-.]*)/g;

function scoreMatch(value: string, label: string, query: string): number {
  const v = value.toLowerCase();
  const l = label.toLowerCase();
  const q = query.toLowerCase();
  const name = v.includes(":") ? v.split(":").slice(1).join(":") : v;
  if (v.startsWith(q)) return 4;
  if (name.startsWith(q)) return 3;
  if (v.includes(q) || l.includes(q)) return 2;
  let hi = 0;
  for (let i = 0; i < q.length; i++) {
    const idx = v.indexOf(q[i], hi);
    if (idx === -1) return 0;
    hi = idx + 1;
  }
  return 1;
}

function highlightTags(text: string): string {
  const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return escaped.replace(TAG_RE, (match: string, prefix?: string) => {
    const type = (prefix || "").replace(":", "");
    const c = TAG_COLORS[type] || { bg: "#374151", fg: "#d1d5db" };
    return `<span style="border-radius:3px;padding:0 2px;background:${c.bg};color:${c.fg}">${match}</span>`;
  }) + "\n";
}

export function LlmPrompt({
  value,
  onChange,
  label,
  placeholder = "Enter prompt...",
  rows = 5,
  helpText,
}: Props) {
  const { data: completions } = useCompletions();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [showMenu, setShowMenu] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 0 });
  const [atStart, setAtStart] = useState(-1);
  const [filtered, setFiltered] = useState<CompletionItem[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);

  // Sync mirror highlight
  useEffect(() => {
    if (mirrorRef.current) {
      mirrorRef.current.innerHTML = highlightTags(value);
    }
  }, [value]);

  const handleInput = useCallback(
    (text: string) => {
      onChange(text);
      const ta = textareaRef.current;
      if (!ta || !completions) return;

      const pos = ta.selectionStart;
      const before = text.substring(0, pos);
      const atIdx = before.lastIndexOf("@");

      if (atIdx === -1 || (atIdx > 0 && /\w/.test(before[atIdx - 1]))) {
        setShowMenu(false);
        return;
      }

      const query = before.substring(atIdx + 1);
      if (/\s/.test(query)) {
        setShowMenu(false);
        return;
      }

      setAtStart(atIdx);
      const scored = completions
        .map((c) => ({ c, s: scoreMatch(c.value, c.label, query) }))
        .filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s)
        .map((x) => x.c)
        .slice(0, 10);

      setActiveIdx(0);
      setFiltered(scored);

      if (scored.length > 0 && containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setMenuPos({ top: rect.bottom + 2, left: rect.left, width: rect.width });
        setShowMenu(true);
      } else {
        setShowMenu(false);
      }
    },
    [completions, onChange]
  );

  const selectItem = useCallback(
    (item: CompletionItem) => {
      const ta = textareaRef.current;
      if (!ta) return;
      const before = value.substring(0, atStart);
      const after = value.substring(ta.selectionStart);
      const newValue = before + "@" + item.value + " " + after;
      onChange(newValue);
      setShowMenu(false);
      requestAnimationFrame(() => {
        const cur = atStart + item.value.length + 2;
        ta.selectionStart = ta.selectionEnd = cur;
        ta.focus();
      });
    },
    [value, atStart, onChange]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!showMenu) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        if (filtered.length > 0) {
          e.preventDefault();
          selectItem(filtered[activeIdx]);
        }
      } else if (e.key === "Escape") {
        setShowMenu(false);
      }
    },
    [showMenu, filtered, activeIdx, selectItem]
  );

  // Portal dropdown for autocomplete
  const renderMenu = () => {
    if (!showMenu || filtered.length === 0 || typeof document === "undefined") return null;
    const ReactDOM = require("react-dom");
    return ReactDOM.createPortal(
      <>
        <div onClick={() => setShowMenu(false)} style={{ position: "fixed", inset: 0, zIndex: 9998 }} />
        <div
          style={{
            position: "fixed",
            top: menuPos.top,
            left: menuPos.left,
            width: menuPos.width,
            maxHeight: 200,
            zIndex: 9999,
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 8,
            boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
            overflowY: "auto",
          }}
        >
          {filtered.map((item, i) => (
            <div
              key={item.value}
              onMouseDown={(e) => { e.preventDefault(); selectItem(item); }}
              onMouseEnter={() => setActiveIdx(i)}
              style={{
                padding: "6px 12px",
                cursor: "pointer",
                display: "flex",
                alignItems: "baseline",
                gap: 8,
                background: i === activeIdx ? "#2a2a2a" : "transparent",
              }}
            >
              <span style={{ fontFamily: "monospace", fontSize: 12, color: "#818cf8" }}>
                @{item.value}
              </span>
              {item.label !== item.value && (
                <span style={{ fontSize: 11, color: "#666", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {item.label.slice(item.value.length)}
                </span>
              )}
            </div>
          ))}
        </div>
      </>,
      document.body
    );
  };

  const baseStyle: React.CSSProperties = {
    fontFamily: "monospace",
    fontSize: 13,
    lineHeight: "1.4em",
    padding: "8px 12px",
    borderRadius: 8,
  };

  return (
    <div>
      {label && (
        <div style={{ color: "#666", fontSize: 12, marginBottom: 4 }}>
          {label}{" "}
          <span style={{ color: "#555" }}>(type @ to insert tags)</span>
        </div>
      )}
      <div ref={containerRef} style={{ position: "relative" }}>
        {/* Mirror for syntax highlighting */}
        <div
          ref={mirrorRef}
          style={{
            ...baseStyle,
            position: "absolute",
            inset: 0,
            background: "#111",
            border: "1px solid #333",
            pointerEvents: "none",
            overflow: "hidden",
            whiteSpace: "pre-wrap",
            wordWrap: "break-word",
            color: "#e5e7eb",
            zIndex: 0,
          }}
        />
        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => handleInput(e.target.value)}
          onKeyDown={handleKeyDown as any}
          onBlur={() => setTimeout(() => setShowMenu(false), 200)}
          onScroll={() => {
            if (mirrorRef.current && textareaRef.current) {
              mirrorRef.current.scrollTop = textareaRef.current.scrollTop;
            }
          }}
          placeholder={placeholder}
          rows={rows}
          style={{
            ...baseStyle,
            width: "100%",
            border: "1px solid #333",
            background: "transparent",
            color: "transparent",
            caretColor: "#e5e7eb",
            position: "relative",
            zIndex: 1,
            resize: "vertical",
            outline: "none",
          }}
          onFocus={(e) => { (e.target as HTMLTextAreaElement).style.borderColor = "#3b82f6"; }}
        />
      </div>
      {helpText && (
        <div style={{ color: "#555", fontSize: 11, marginTop: 4 }}>{helpText}</div>
      )}
      {renderMenu()}
    </div>
  );
}
