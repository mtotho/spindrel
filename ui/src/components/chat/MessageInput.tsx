import { useState, useRef, useCallback } from "react";
import { View, TextInput, Pressable, Platform } from "react-native";
import { Send } from "lucide-react";
import { useCompletions } from "../../api/hooks/useModels";
import { AutocompleteMenu, scoreMatch } from "../shared/LlmPrompt";
import type { CompletionItem } from "../../types/api";

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function MessageInput({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const inputRef = useRef<TextInput>(null);

  // Autocomplete state (web only)
  const { data: completions } = useCompletions();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [showMenu, setShowMenu] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 0 });
  const [atStart, setAtStart] = useState(-1);
  const [filtered, setFiltered] = useState<CompletionItem[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    if (Platform.OS === "web") {
      textareaRef.current?.focus();
    } else {
      inputRef.current?.focus();
    }
  }, [text, disabled, onSend]);

  // --- Web autocomplete logic ---
  const handleWebInput = useCallback(
    (newText: string) => {
      setText(newText);
      const ta = textareaRef.current;
      if (!ta || !completions) return;
      const pos = ta.selectionStart;
      const before = newText.substring(0, pos);
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
        setMenuPos({
          top: rect.top - 4, // anchor to top of input (menu renders upward)
          left: rect.left,
          width: Math.min(rect.width, 500),
        });
        setShowMenu(true);
      } else {
        setShowMenu(false);
      }
    },
    [completions]
  );

  const selectItem = useCallback(
    (item: CompletionItem) => {
      const ta = textareaRef.current;
      if (!ta) return;
      const before = text.substring(0, atStart);
      const after = text.substring(ta.selectionStart);
      const newText = before + "@" + item.value + " " + after;
      setText(newText);
      setShowMenu(false);
      requestAnimationFrame(() => {
        const cur = atStart + item.value.length + 2;
        ta.selectionStart = ta.selectionEnd = cur;
        ta.focus();
      });
    },
    [text, atStart]
  );

  const handleWebKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (showMenu) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setActiveIdx((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          if (filtered.length > 0) {
            e.preventDefault();
            selectItem(filtered[activeIdx]);
          }
          return;
        }
        if (e.key === "Escape") {
          setShowMenu(false);
          return;
        }
      }
      // Enter without shift → send
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [showMenu, filtered, activeIdx, selectItem, handleSend]
  );

  // --- Native key handler ---
  const handleKeyPress = (e: any) => {
    if (
      Platform.OS === "web" &&
      e.nativeEvent?.key === "Enter" &&
      !e.nativeEvent?.shiftKey
    ) {
      e.preventDefault();
      handleSend();
    }
  };

  // Web: use raw textarea for selectionStart access
  if (Platform.OS === "web") {
    return (
      <View className="flex-row items-end gap-2 p-4 border-t border-surface-border bg-surface">
        <div ref={containerRef} style={{ flex: 1, display: "flex" }}>
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => handleWebInput(e.target.value)}
            onKeyDown={handleWebKeyDown}
            onBlur={() => setTimeout(() => setShowMenu(false), 200)}
            placeholder="Type a message..."
            disabled={disabled}
            autoFocus
            rows={1}
            style={{
              flex: 1,
              fontFamily: "inherit",
              fontSize: 14,
              lineHeight: "1.4",
              padding: "10px 16px",
              borderRadius: 12,
              border: "1px solid var(--color-surface-border, #333)",
              background: "var(--color-surface-raised, #1a1a1a)",
              color: "var(--color-text, #e5e5e5)",
              resize: "none",
              outline: "none",
              minHeight: 44,
              maxHeight: 120,
              overflow: "auto",
            }}
            onFocus={(e) => {
              e.target.style.borderColor = "#3b82f6";
            }}
            onBlurCapture={(e) => {
              e.target.style.borderColor = "";
            }}
          />
        </div>
        <Pressable
          onPress={handleSend}
          disabled={!text.trim() || disabled}
          className={`w-11 h-11 rounded-xl items-center justify-center ${
            text.trim() && !disabled ? "bg-accent" : "bg-surface-raised"
          }`}
        >
          <Send
            size={18}
            color={text.trim() && !disabled ? "white" : "#666666"}
          />
        </Pressable>
        <AutocompleteMenu
          show={showMenu}
          items={filtered}
          activeIdx={activeIdx}
          menuPos={{
            top: menuPos.top,
            left: menuPos.left,
            width: menuPos.width,
          }}
          onSelect={selectItem}
          onHover={setActiveIdx}
          onClose={() => setShowMenu(false)}
          anchor="bottom"
        />
      </View>
    );
  }

  // Native: keep RN TextInput
  return (
    <View className="flex-row items-end gap-2 p-4 border-t border-surface-border bg-surface">
      <TextInput
        ref={inputRef}
        className="flex-1 bg-surface-raised border border-surface-border rounded-xl px-4 py-3 text-text text-sm min-h-[44px] max-h-[120px]"
        placeholder="Type a message..."
        placeholderTextColor="#666666"
        value={text}
        onChangeText={setText}
        onKeyPress={handleKeyPress}
        multiline
        editable={!disabled}
      />
      <Pressable
        onPress={handleSend}
        disabled={!text.trim() || disabled}
        className={`w-11 h-11 rounded-xl items-center justify-center ${
          text.trim() && !disabled ? "bg-accent" : "bg-surface-raised"
        }`}
      >
        <Send
          size={18}
          color={text.trim() && !disabled ? "white" : "#666666"}
        />
      </Pressable>
    </View>
  );
}
