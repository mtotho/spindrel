import { View, Text, Pressable, ScrollView } from "react-native";
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

function scoreMatch(value: string, label: string, query: string): number {
  const v = value.toLowerCase();
  const l = label.toLowerCase();
  const q = query.toLowerCase();
  const name = v.includes(":") ? v.split(":").slice(1).join(":") : v;
  if (v.startsWith(q)) return 4;
  if (name.startsWith(q)) return 3;
  if (v.includes(q) || l.includes(q)) return 2;
  // Fuzzy
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
  const mirrorRef = useRef<HTMLDivElement>(null);

  const [showMenu, setShowMenu] = useState(false);
  const [atStart, setAtStart] = useState(-1);
  const [filtered, setFiltered] = useState<CompletionItem[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);

  const TAG_RE = /(?<![<\w@])@((?:skill|knowledge|tool-pack|tool):)?([A-Za-z_][\w\-.]*)/g;

  const updateHighlight = useCallback(() => {
    if (!mirrorRef.current || !textareaRef.current) return;
    const escaped = value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    mirrorRef.current.innerHTML =
      escaped.replace(TAG_RE, (match: string, prefix?: string) => {
        const type = (prefix || "").replace(":", "");
        const colors = TAG_COLORS[type] || { bg: "#374151", fg: "#d1d5db" };
        return `<span style="border-radius:3px;padding:0 2px;background:${colors.bg};color:${colors.fg}">${match}</span>`;
      }) + "\n";
    mirrorRef.current.scrollTop = textareaRef.current.scrollTop;
  }, [value]);

  useEffect(() => {
    updateHighlight();
  }, [value, updateHighlight]);

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
      const ql = query.toLowerCase();
      const scored = completions
        .map((c) => ({ c, s: scoreMatch(c.value, c.label, ql) }))
        .filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s)
        .map((x) => x.c)
        .slice(0, 10);

      setActiveIdx(0);
      setFiltered(scored);
      setShowMenu(scored.length > 0);
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

      // Move cursor
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

  return (
    <View>
      {label && (
        <Text className="text-text-dim text-xs mb-1">
          {label}{" "}
          <Text className="text-text-dim/50">
            (type @ to insert skill/tool tags)
          </Text>
        </Text>
      )}
      <View className="relative">
        {/* Mirror for syntax highlighting */}
        <div
          ref={mirrorRef}
          style={{
            position: "absolute",
            inset: 0,
            padding: "8px 12px",
            fontSize: 13,
            fontFamily: "monospace",
            background: "#111111",
            borderRadius: 8,
            pointerEvents: "none",
            overflow: "hidden",
            whiteSpace: "pre-wrap",
            wordWrap: "break-word",
            color: "#e5e7eb",
            lineHeight: "1.25rem",
            zIndex: 0,
          }}
        />
        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => handleInput(e.target.value)}
          onKeyDown={handleKeyDown as any}
          onBlur={() => setTimeout(() => setShowMenu(false), 150)}
          onScroll={() => {
            if (mirrorRef.current && textareaRef.current) {
              mirrorRef.current.scrollTop = textareaRef.current.scrollTop;
            }
          }}
          placeholder={placeholder}
          rows={rows}
          style={{
            width: "100%",
            fontFamily: "monospace",
            fontSize: 13,
            border: "1px solid #333333",
            borderRadius: 8,
            padding: "8px 12px",
            background: "transparent",
            color: "transparent",
            caretColor: "#e5e7eb",
            position: "relative",
            zIndex: 1,
            resize: "vertical",
            outline: "none",
            lineHeight: "1.25rem",
          }}
        />
        {/* Autocomplete dropdown */}
        {showMenu && filtered.length > 0 && (
          <View
            className="absolute z-50 left-0 right-0 bg-surface-raised border border-surface-border rounded-lg shadow-lg overflow-hidden"
            style={{ top: "100%", marginTop: 2, maxHeight: 180 }}
          >
            <ScrollView>
              {filtered.map((item, i) => (
                <Pressable
                  key={item.value}
                  onPress={() => selectItem(item)}
                  className={`flex-row items-baseline gap-2 px-3 py-1.5 ${
                    i === activeIdx ? "bg-surface-overlay" : "hover:bg-surface-overlay/50"
                  }`}
                >
                  <Text className="text-accent text-xs font-mono">
                    @{item.value}
                  </Text>
                  {item.label !== item.value && (
                    <Text className="text-text-dim text-xs" numberOfLines={1}>
                      {item.label.slice(item.value.length)}
                    </Text>
                  )}
                </Pressable>
              ))}
            </ScrollView>
          </View>
        )}
      </View>
      {helpText && (
        <Text className="text-text-dim text-[10px] mt-1">{helpText}</Text>
      )}
    </View>
  );
}
