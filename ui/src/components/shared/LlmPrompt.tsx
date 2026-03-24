import { useState, useRef, useCallback } from "react";
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
  const containerRef = useRef<HTMLDivElement>(null);

  const [showMenu, setShowMenu] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 0 });
  const [atStart, setAtStart] = useState(-1);
  const [filtered, setFiltered] = useState<CompletionItem[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);

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

  const TAG_COLORS: Record<string, { bg: string; fg: string }> = {
    skill: { bg: "#1e1b4b", fg: "#a5b4fc" },
    tool: { bg: "#14532d", fg: "#86efac" },
    "tool-pack": { bg: "#14532d", fg: "#86efac" },
    knowledge: { bg: "#3b0764", fg: "#d8b4fe" },
  };

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
          {filtered.map((item, i) => {
            const prefix = item.value.includes(":") ? item.value.split(":")[0] : "";
            const colors = TAG_COLORS[prefix] || { bg: "#374151", fg: "#d1d5db" };
            return (
              <div
                key={item.value}
                onMouseDown={(e) => { e.preventDefault(); selectItem(item); }}
                onMouseEnter={() => setActiveIdx(i)}
                style={{
                  padding: "6px 12px",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  background: i === activeIdx ? "#2a2a2a" : "transparent",
                }}
              >
                {prefix && (
                  <span style={{
                    fontSize: 9,
                    fontWeight: 600,
                    padding: "1px 5px",
                    borderRadius: 3,
                    background: colors.bg,
                    color: colors.fg,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                  }}>
                    {prefix}
                  </span>
                )}
                <span style={{ fontFamily: "monospace", fontSize: 12, color: "#e5e5e5" }}>
                  {item.value.includes(":") ? item.value.split(":").slice(1).join(":") : item.value}
                </span>
                {item.label !== item.value && (
                  <span style={{ fontSize: 11, color: "#666", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {item.label}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </>,
      document.body
    );
  };

  return (
    <div>
      {label && (
        <div style={{ color: "#999", fontSize: 12, marginBottom: 4, fontWeight: 500 }}>
          {label}{" "}
          <span style={{ color: "#555", fontWeight: 400 }}>(type @ to insert tags)</span>
        </div>
      )}
      <div ref={containerRef}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => handleInput(e.target.value)}
          onKeyDown={handleKeyDown as any}
          onBlur={() => setTimeout(() => setShowMenu(false), 200)}
          placeholder={placeholder}
          rows={rows}
          style={{
            fontFamily: "monospace",
            fontSize: 13,
            lineHeight: "1.5",
            padding: "8px 12px",
            borderRadius: 8,
            width: "100%",
            border: "1px solid #333",
            background: "#111",
            color: "#e5e7eb",
            resize: "vertical",
            outline: "none",
            transition: "border-color 0.15s",
          }}
          onFocus={(e) => { e.target.style.borderColor = "#3b82f6"; }}
          onBlurCapture={(e) => { e.target.style.borderColor = "#333"; }}
        />
      </div>
      {helpText && (
        <div style={{ color: "#555", fontSize: 11, marginTop: 4 }}>{helpText}</div>
      )}
      {renderMenu()}
    </div>
  );
}
