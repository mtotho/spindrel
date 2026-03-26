import { useState, useRef, useCallback } from "react";
import { useCompletions } from "../../api/hooks/useModels";
import { useGeneratePrompt } from "../../api/hooks/usePrompts";
import type { CompletionItem } from "../../types/api";

interface Props {
  value: string;
  onChange: (text: string) => void;
  label?: string;
  placeholder?: string;
  rows?: number;
  helpText?: string;
  generateContext?: string;
}

export function scoreMatch(value: string, label: string, query: string): number {
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

const TAG_COLORS: Record<string, { bg: string; fg: string }> = {
  skill: { bg: "#1e1b4b", fg: "#a5b4fc" },
  tool: { bg: "#14532d", fg: "#86efac" },
  "tool-pack": { bg: "#14532d", fg: "#86efac" },
  knowledge: { bg: "#3b0764", fg: "#d8b4fe" },
};

// ---------------------------------------------------------------------------
// Generate button (shared between inline + fullscreen)
// ---------------------------------------------------------------------------
function GenerateButton({
  generateContext,
  value,
  onChange,
  size = "small",
}: {
  generateContext: string;
  value: string;
  onChange: (text: string) => void;
  size?: "small" | "normal";
}) {
  const gen = useGeneratePrompt();
  const [flash, setFlash] = useState<"success" | "error" | null>(null);

  const handleGenerate = useCallback(() => {
    gen.mutate(
      { context: generateContext, user_input: value },
      {
        onSuccess: (data) => {
          onChange(data.prompt);
          setFlash("success");
          setTimeout(() => setFlash(null), 1200);
        },
        onError: () => {
          setFlash("error");
          setTimeout(() => setFlash(null), 1500);
        },
      }
    );
  }, [gen, generateContext, value, onChange]);

  const isSmall = size === "small";
  const baseStyle: React.CSSProperties = isSmall
    ? {
        background: "none", border: "1px solid #333", borderRadius: 4,
        color: "#666", fontSize: 11, padding: "2px 8px", cursor: "pointer",
        transition: "all 0.15s", whiteSpace: "nowrap",
      }
    : {
        background: "none", border: "1px solid #444", borderRadius: 6,
        color: "#999", fontSize: 13, padding: "6px 16px", cursor: "pointer",
        transition: "all 0.15s", fontWeight: 600, whiteSpace: "nowrap",
      };

  const flashColor = flash === "success" ? "#22c55e" : flash === "error" ? "#ef4444" : undefined;

  return (
    <button
      onClick={handleGenerate}
      disabled={gen.isPending}
      style={{
        ...baseStyle,
        ...(flash ? { borderColor: flashColor, color: flashColor } : {}),
        ...(gen.isPending ? { opacity: 0.6, cursor: "wait" } : {}),
      }}
      onMouseEnter={(e) => { if (!gen.isPending && !flash) { e.currentTarget.style.borderColor = "#555"; e.currentTarget.style.color = "#999"; } }}
      onMouseLeave={(e) => { if (!gen.isPending && !flash) { e.currentTarget.style.borderColor = isSmall ? "#333" : "#444"; e.currentTarget.style.color = isSmall ? "#666" : "#999"; } }}
    >
      {gen.isPending ? "Generating..." : flash === "success" ? "Done!" : flash === "error" ? "Failed" : "Generate"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Autocomplete dropdown (portal-based)
// ---------------------------------------------------------------------------
export function AutocompleteMenu({
  show,
  items,
  activeIdx,
  menuPos,
  onSelect,
  onHover,
  onClose,
  anchor,
}: {
  show: boolean;
  items: CompletionItem[];
  activeIdx: number;
  menuPos: { top: number; left: number; width: number };
  onSelect: (item: CompletionItem) => void;
  onHover: (i: number) => void;
  onClose: () => void;
  anchor?: "top" | "bottom";
}) {
  if (!show || items.length === 0 || typeof document === "undefined") return null;
  const ReactDOM = require("react-dom");
  const posStyle: React.CSSProperties =
    anchor === "bottom"
      ? { bottom: window.innerHeight - menuPos.top }
      : { top: menuPos.top };
  return ReactDOM.createPortal(
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 10010 }} />
      <div
        style={{
          position: "fixed",
          ...posStyle,
          left: menuPos.left,
          width: menuPos.width,
          maxHeight: 200,
          zIndex: 10011,
          background: "#1a1a1a",
          border: "1px solid #333",
          borderRadius: 8,
          boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
          overflowY: "auto",
        }}
      >
        {items.map((item, i) => {
          const prefix = item.value.includes(":") ? item.value.split(":")[0] : "";
          const colors = TAG_COLORS[prefix] || { bg: "#374151", fg: "#d1d5db" };
          return (
            <div
              key={item.value}
              onMouseDown={(e) => { e.preventDefault(); onSelect(item); }}
              onMouseEnter={() => onHover(i)}
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
                  fontSize: 9, fontWeight: 600, padding: "1px 5px", borderRadius: 3,
                  background: colors.bg, color: colors.fg,
                  textTransform: "uppercase", letterSpacing: "0.05em",
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
}

// ---------------------------------------------------------------------------
// Fullscreen modal editor
// ---------------------------------------------------------------------------
function FullscreenEditor({
  value,
  onChange,
  label,
  placeholder,
  generateContext,
  onClose,
}: {
  value: string;
  onChange: (text: string) => void;
  label?: string;
  placeholder?: string;
  generateContext?: string;
  onClose: () => void;
}) {
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
      if (atIdx === -1 || (atIdx > 0 && /\w/.test(before[atIdx - 1]))) { setShowMenu(false); return; }
      const query = before.substring(atIdx + 1);
      if (/\s/.test(query)) { setShowMenu(false); return; }
      setAtStart(atIdx);
      const scored = completions.map((c) => ({ c, s: scoreMatch(c.value, c.label, query) }))
        .filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.c).slice(0, 10);
      setActiveIdx(0);
      setFiltered(scored);
      if (scored.length > 0 && containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setMenuPos({ top: rect.bottom + 2, left: rect.left, width: Math.min(rect.width, 500) });
        setShowMenu(true);
      } else { setShowMenu(false); }
    },
    [completions, onChange]
  );

  const selectItem = useCallback(
    (item: CompletionItem) => {
      const ta = textareaRef.current;
      if (!ta) return;
      const before = value.substring(0, atStart);
      const after = value.substring(ta.selectionStart);
      onChange(before + "@" + item.value + " " + after);
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
      if (e.key === "Escape" && !showMenu) { onClose(); return; }
      if (!showMenu) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(i + 1, filtered.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, 0)); }
      else if (e.key === "Enter" || e.key === "Tab") { if (filtered.length > 0) { e.preventDefault(); selectItem(filtered[activeIdx]); } }
      else if (e.key === "Escape") { setShowMenu(false); }
    },
    [showMenu, filtered, activeIdx, selectItem, onClose]
  );

  if (typeof document === "undefined") return null;
  const ReactDOM = require("react-dom");

  return ReactDOM.createPortal(
    <div style={{
      position: "fixed", inset: 0, zIndex: 10000,
      background: "rgba(0,0,0,0.8)", display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "12px 20px", borderBottom: "1px solid #333",
      }}>
        <div style={{ color: "#e5e5e5", fontSize: 14, fontWeight: 600 }}>
          {label || "Edit Prompt"}
          <span style={{ color: "#555", fontWeight: 400, fontSize: 12, marginLeft: 8 }}>(type @ to insert tags, Esc to close)</span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {generateContext && (
            <GenerateButton generateContext={generateContext} value={value} onChange={onChange} size="normal" />
          )}
          <button
            onClick={onClose}
            style={{
              background: "#3b82f6", color: "#fff", border: "none", borderRadius: 6,
              padding: "6px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}
          >
            Done
          </button>
        </div>
      </div>

      {/* Editor */}
      <div ref={containerRef} style={{ flex: 1, padding: 20, display: "flex", flexDirection: "column" }}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => handleInput(e.target.value)}
          onKeyDown={handleKeyDown as any}
          onBlur={() => setTimeout(() => setShowMenu(false), 200)}
          placeholder={placeholder}
          autoFocus
          style={{
            flex: 1, width: "100%",
            fontFamily: "monospace", fontSize: 16, lineHeight: "1.6",
            padding: "16px 20px", borderRadius: 10,
            border: "1px solid #333", background: "#0a0a0a", color: "#e5e7eb",
            resize: "none", outline: "none",
          }}
          onFocus={(e) => { e.target.style.borderColor = "#3b82f6"; }}
          onBlurCapture={(e) => { e.target.style.borderColor = "#333"; }}
        />
      </div>

      <AutocompleteMenu
        show={showMenu}
        items={filtered}
        activeIdx={activeIdx}
        menuPos={menuPos}
        onSelect={selectItem}
        onHover={setActiveIdx}
        onClose={() => setShowMenu(false)}
      />
    </div>,
    document.body
  );
}

// ---------------------------------------------------------------------------
// Main LlmPrompt component
// ---------------------------------------------------------------------------
export function LlmPrompt({
  value,
  onChange,
  label,
  placeholder = "Enter prompt...",
  rows = 5,
  helpText,
  generateContext,
}: Props) {
  const { data: completions } = useCompletions();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [showMenu, setShowMenu] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 0 });
  const [atStart, setAtStart] = useState(-1);
  const [filtered, setFiltered] = useState<CompletionItem[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [expanded, setExpanded] = useState(false);

  const handleInput = useCallback(
    (text: string) => {
      onChange(text);
      const ta = textareaRef.current;
      if (!ta || !completions) return;
      const pos = ta.selectionStart;
      const before = text.substring(0, pos);
      const atIdx = before.lastIndexOf("@");
      if (atIdx === -1 || (atIdx > 0 && /\w/.test(before[atIdx - 1]))) { setShowMenu(false); return; }
      const query = before.substring(atIdx + 1);
      if (/\s/.test(query)) { setShowMenu(false); return; }
      setAtStart(atIdx);
      const scored = completions.map((c) => ({ c, s: scoreMatch(c.value, c.label, query) }))
        .filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.c).slice(0, 10);
      setActiveIdx(0);
      setFiltered(scored);
      if (scored.length > 0 && containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setMenuPos({ top: rect.bottom + 2, left: rect.left, width: rect.width });
        setShowMenu(true);
      } else { setShowMenu(false); }
    },
    [completions, onChange]
  );

  const selectItem = useCallback(
    (item: CompletionItem) => {
      const ta = textareaRef.current;
      if (!ta) return;
      const before = value.substring(0, atStart);
      const after = value.substring(ta.selectionStart);
      onChange(before + "@" + item.value + " " + after);
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
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(i + 1, filtered.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, 0)); }
      else if (e.key === "Enter" || e.key === "Tab") { if (filtered.length > 0) { e.preventDefault(); selectItem(filtered[activeIdx]); } }
      else if (e.key === "Escape") { setShowMenu(false); }
    },
    [showMenu, filtered, activeIdx, selectItem]
  );

  return (
    <div>
      {label && (
        <div style={{ color: "#999", fontSize: 12, marginBottom: 4, fontWeight: 500, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>
            {label}{" "}
            <span style={{ color: "#555", fontWeight: 400 }}>(type @ to insert tags)</span>
          </span>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {generateContext && (
              <GenerateButton generateContext={generateContext} value={value} onChange={onChange} />
            )}
            <button
              onClick={() => setExpanded(true)}
              style={{
                background: "none", border: "1px solid #333", borderRadius: 4,
                color: "#666", fontSize: 11, padding: "2px 8px", cursor: "pointer",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = "#555"; e.currentTarget.style.color = "#999"; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = "#333"; e.currentTarget.style.color = "#666"; }}
            >
              Expand
            </button>
          </div>
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
            fontFamily: "monospace", fontSize: 16, lineHeight: "1.5",
            padding: "8px 12px", borderRadius: 8, width: "100%",
            border: "1px solid #333", background: "#111", color: "#e5e7eb",
            resize: "vertical", outline: "none", transition: "border-color 0.15s",
          }}
          onFocus={(e) => { e.target.style.borderColor = "#3b82f6"; }}
          onBlurCapture={(e) => { e.target.style.borderColor = "#333"; }}
        />
      </div>
      {helpText && (
        <div style={{ color: "#555", fontSize: 11, marginTop: 4 }}>{helpText}</div>
      )}

      <AutocompleteMenu
        show={showMenu}
        items={filtered}
        activeIdx={activeIdx}
        menuPos={menuPos}
        onSelect={selectItem}
        onHover={setActiveIdx}
        onClose={() => setShowMenu(false)}
      />

      {expanded && (
        <FullscreenEditor
          value={value}
          onChange={onChange}
          label={label}
          placeholder={placeholder}
          generateContext={generateContext}
          onClose={() => setExpanded(false)}
        />
      )}
    </div>
  );
}
