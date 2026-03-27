import { useState, useRef, useCallback } from "react";
import { View, Text, TextInput, Pressable, Platform } from "react-native";
import { Send, Paperclip, X, Cpu } from "lucide-react";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useCompletions } from "../../api/hooks/useModels";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { AutocompleteMenu, scoreMatch } from "../shared/LlmPrompt";
import type { CompletionItem } from "../../types/api";

export interface PendingFile {
  file: File;
  preview?: string; // data URL for image preview
  base64: string; // raw base64 (no data: prefix)
}

interface Props {
  onSend: (message: string, files?: PendingFile[]) => void;
  disabled?: boolean;
  modelOverride?: string;
  onModelOverrideChange?: (m: string | undefined) => void;
  defaultModel?: string;
}

export function MessageInput({ onSend, disabled, modelOverride, onModelOverrideChange, defaultModel }: Props) {
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const insets = useSafeAreaInsets();
  const [text, setText] = useState("");
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const inputRef = useRef<TextInput>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);

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
    if ((!trimmed && pendingFiles.length === 0) || disabled) return;
    onSend(trimmed, pendingFiles.length > 0 ? pendingFiles : undefined);
    setText("");
    setPendingFiles([]);
    if (Platform.OS === "web") {
      textareaRef.current?.focus();
    } else {
      inputRef.current?.focus();
    }
  }, [text, pendingFiles, disabled, onSend]);

  // --- File handling ---
  const handleFileSelect = useCallback(async (files: FileList | null) => {
    if (!files) return;
    const newFiles: PendingFile[] = [];
    for (const file of Array.from(files)) {
      const base64 = await fileToBase64(file);
      const preview = file.type.startsWith("image/")
        ? URL.createObjectURL(file)
        : undefined;
      newFiles.push({ file, preview, base64 });
    }
    setPendingFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const removeFile = useCallback((idx: number) => {
    setPendingFiles((prev) => {
      const next = [...prev];
      if (next[idx]?.preview) URL.revokeObjectURL(next[idx].preview!);
      next.splice(idx, 1);
      return next;
    });
  }, []);

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
          top: rect.top - 4,
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
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [showMenu, filtered, activeIdx, selectItem, handleSend]
  );

  // Handle paste with images
  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const imageFiles: File[] = [];
      for (const item of Array.from(items)) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) imageFiles.push(file);
        }
      }
      if (imageFiles.length > 0) {
        e.preventDefault();
        const dt = new DataTransfer();
        imageFiles.forEach((f) => dt.items.add(f));
        handleFileSelect(dt.files);
      }
    },
    [handleFileSelect]
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

  const canSend = (text.trim() || pendingFiles.length > 0) && !disabled;

  // Web: use raw textarea for selectionStart access
  if (Platform.OS === "web") {
    return (
      <View style={{ flexShrink: 0, paddingBottom: insets.bottom, borderTopWidth: 1, borderTopColor: "rgba(255,255,255,0.06)", backgroundColor: "#111111" }}>
        {/* Pending file previews */}
        {pendingFiles.length > 0 && (
          <div
            style={{
              display: "flex",
              gap: 8,
              padding: "8px 20px 0",
              flexWrap: "wrap",
            }}
          >
            {pendingFiles.map((pf, i) => (
              <div
                key={i}
                style={{
                  position: "relative",
                  borderRadius: 8,
                  overflow: "hidden",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
              >
                {pf.preview ? (
                  <img
                    src={pf.preview}
                    alt={pf.file.name}
                    style={{
                      width: 64,
                      height: 64,
                      objectFit: "cover",
                      display: "block",
                    }}
                  />
                ) : (
                  <div
                    style={{
                      width: 64,
                      height: 64,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      background: "#1a1a1a",
                      fontSize: 10,
                      color: "#999",
                      padding: 4,
                      textAlign: "center",
                      wordBreak: "break-all",
                    }}
                  >
                    {pf.file.name.slice(0, 20)}
                  </div>
                )}
                <button
                  onClick={() => removeFile(i)}
                  style={{
                    position: "absolute",
                    top: 2,
                    right: 2,
                    width: 18,
                    height: 18,
                    borderRadius: 9,
                    background: "rgba(0,0,0,0.7)",
                    border: "none",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    cursor: "pointer",
                    padding: 0,
                  }}
                >
                  <X size={10} color="#fff" />
                </button>
              </div>
            ))}
          </div>
        )}

        <View className={`flex-row items-end ${isMobile ? "gap-2 px-3 py-2" : "gap-3 px-5 py-3"}`}>
          {/* Attach button */}
          <Pressable
            onPress={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="items-center justify-center rounded-lg hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 40, height: 40 }}
          >
            <Paperclip size={20} color="#555555" />
          </Pressable>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.pdf,.txt,.csv,.json,.md"
            style={{ display: "none" }}
            onChange={(e) => {
              handleFileSelect(e.target.files);
              e.target.value = "";
            }}
          />

          <div ref={containerRef} style={{ flex: 1, display: "flex" }}>
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => handleWebInput(e.target.value)}
              onKeyDown={handleWebKeyDown}
              onPaste={handlePaste}
              onBlur={() => setTimeout(() => setShowMenu(false), 200)}
              placeholder="Type a message..."
              disabled={disabled}
              autoFocus
              rows={1}
              style={{
                flex: 1,
                fontFamily: "inherit",
                fontSize: 15,
                lineHeight: "1.5",
                padding: "10px 16px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.1)",
                background: "#1a1a1e",
                color: "#e5e5e5",
                resize: "none",
                outline: "none",
                minHeight: 44,
                maxHeight: 140,
                overflow: "auto",
              }}
              onFocus={(e) => {
                e.target.style.borderColor = "rgba(255,255,255,0.18)";
              }}
              onBlurCapture={(e) => {
                e.target.style.borderColor = "rgba(255,255,255,0.1)";
              }}
            />
          </div>
          {/* Per-turn model picker */}
          {Platform.OS === "web" && onModelOverrideChange && (
            <div ref={modelPickerRef} style={{ position: "relative", display: "flex", alignItems: "center" }}>
              {modelOverride ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    background: "rgba(99,102,241,0.1)",
                    border: "1px solid rgba(99,102,241,0.25)",
                    borderRadius: 6,
                    padding: "4px 8px",
                    fontSize: 11,
                    color: "#8b5cf6",
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                    maxWidth: 180,
                  }}
                  onClick={() => setShowModelPicker(true)}
                  title={`Per-turn override: ${modelOverride}`}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                    {modelOverride.split("/").pop()}
                  </span>
                  <span style={{ fontSize: 9, opacity: 0.7 }}>1 msg</span>
                  <span
                    onClick={(e) => { e.stopPropagation(); onModelOverrideChange(undefined); }}
                    style={{ marginLeft: 2, cursor: "pointer", fontSize: 12, lineHeight: 1 }}
                  >
                    ✕
                  </span>
                </div>
              ) : (
                <Pressable
                  onPress={() => setShowModelPicker(true)}
                  className="items-center justify-center rounded-lg hover:bg-surface-overlay active:bg-surface-overlay"
                  style={{ width: 40, height: 40, opacity: 0.6 }}
                >
                  <Cpu size={16} color="#666666" />
                </Pressable>
              )}
              {showModelPicker && (() => {
                const { LlmModelDropdown } = require("../shared/LlmModelDropdown");
                const ReactDOM = require("react-dom");
                const rect = modelPickerRef.current?.getBoundingClientRect();
                const dropdownRight = rect ? window.innerWidth - rect.right : 16;
                const dropdownBottom = rect ? window.innerHeight - rect.top + 8 : 80;
                return ReactDOM.createPortal(
                  <>
                    <div
                      onClick={() => setShowModelPicker(false)}
                      style={{ position: "fixed", inset: 0, zIndex: 50000 }}
                    />
                    <div style={{ position: "fixed", bottom: dropdownBottom, right: dropdownRight, zIndex: 50001, width: 320 }}>
                      <LlmModelDropdown
                        value={modelOverride ?? ""}
                        onChange={(m: string) => {
                          onModelOverrideChange(m || undefined);
                          setShowModelPicker(false);
                        }}
                        placeholder={defaultModel ? `inherit (${defaultModel})` : "Select model..."}
                        allowClear
                        anchor="top"
                      />
                    </div>
                  </>,
                  document.body
                );
              })()}
            </div>
          )}
          <Pressable
            onPress={handleSend}
            disabled={!canSend}
            className="items-center justify-center rounded-lg"
            style={{
              width: 40,
              height: 40,
              backgroundColor: canSend ? "#4f46e5" : "transparent",
              opacity: canSend ? 1 : 0.4,
            }}
          >
            <Send size={18} color={canSend ? "white" : "#666666"} />
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
      </View>
    );
  }

  // Native: keep RN TextInput
  return (
    <View className="flex-row items-end gap-2 px-4 py-3" style={{ borderTopWidth: 1, borderTopColor: "rgba(255,255,255,0.06)", backgroundColor: "#111111" }}>
      <TextInput
        ref={inputRef}
        className="flex-1 bg-surface-raised rounded-xl px-4 py-3 text-text text-[15px] min-h-[44px] max-h-[140px]"
        style={{ borderWidth: 1, borderColor: "rgba(255,255,255,0.1)" }}
        placeholder="Type a message..."
        placeholderTextColor="#555555"
        value={text}
        onChangeText={setText}
        onKeyPress={handleKeyPress}
        multiline
        editable={!disabled}
      />
      <Pressable
        onPress={handleSend}
        disabled={!text.trim() || disabled}
        className="items-center justify-center rounded-lg"
        style={{
          width: 40,
          height: 40,
          backgroundColor: text.trim() && !disabled ? "#4f46e5" : "transparent",
          opacity: text.trim() && !disabled ? 1 : 0.4,
        }}
      >
        <Send
          size={18}
          color={text.trim() && !disabled ? "white" : "#666666"}
        />
      </Pressable>
    </View>
  );
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip data URL prefix: "data:...;base64,"
      const idx = result.indexOf(",");
      resolve(idx >= 0 ? result.slice(idx + 1) : result);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
