import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { View, Text, TextInput, Pressable, Platform } from "react-native";
import { Send, Square, Paperclip, X, Cpu, Mic } from "lucide-react";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useCompletions } from "../../api/hooks/useModels";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useAudioRecorder } from "../../hooks/useAudioRecorder";
import { AutocompleteMenu, scoreMatch } from "../shared/LlmPrompt";
import { RecordingOverlay } from "./RecordingOverlay";
import { useThemeTokens } from "../../theme/tokens";
import { useDraftsStore, type DraftFile } from "../../stores/drafts";
import type { CompletionItem } from "../../types/api";

export interface PendingFile {
  file: File;
  preview?: string; // data URL for image preview
  base64: string; // raw base64 (no data: prefix)
}

interface Props {
  onSend: (message: string, files?: PendingFile[]) => void;
  onSendAudio?: (audioBase64: string, audioFormat: string, message?: string) => void;
  disabled?: boolean;
  isStreaming?: boolean;
  onCancel?: () => void;
  modelOverride?: string;
  onModelOverrideChange?: (m: string | undefined) => void;
  defaultModel?: string;
  /** Current channel's bot ID — excluded from @-mention completions */
  currentBotId?: string;
  /** Channel ID for persisting drafts across navigation */
  channelId?: string;
}

/** Rebuild PendingFile objects from serialized DraftFiles (restores File + preview). */
function draftFilesToPending(draftFiles: DraftFile[]): PendingFile[] {
  return draftFiles.map((df) => {
    const byteString = atob(df.base64);
    const bytes = new Uint8Array(byteString.length);
    for (let i = 0; i < byteString.length; i++) bytes[i] = byteString.charCodeAt(i);
    const file = new File([bytes], df.name, { type: df.type });
    const preview = df.type.startsWith("image/") ? `data:${df.type};base64,${df.base64}` : undefined;
    return { file, base64: df.base64, preview };
  });
}

export function MessageInput({ onSend, onSendAudio, disabled, isStreaming, onCancel, modelOverride, onModelOverrideChange, defaultModel, currentBotId, channelId }: Props) {
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const insets = useSafeAreaInsets();
  const t = useThemeTokens();
  const recorder = useAudioRecorder();

  // Persisted draft state (per-channel)
  const draft = useDraftsStore((s) => channelId ? s.getDraft(channelId) : null);
  const setDraftText = useDraftsStore((s) => s.setDraftText);
  const setDraftFiles = useDraftsStore((s) => s.setDraftFiles);
  const clearDraft = useDraftsStore((s) => s.clearDraft);

  // Fallback to local state when no channelId (shouldn't happen in practice)
  const [localText, setLocalText] = useState("");
  const [localFiles, setLocalFiles] = useState<PendingFile[]>([]);

  const text = draft?.text ?? localText;
  const setText = useCallback((t: string) => {
    if (channelId) setDraftText(channelId, t);
    else setLocalText(t);
  }, [channelId, setDraftText]);

  // Rebuild PendingFile objects from persisted draft files
  const pendingFiles = useMemo(
    () => draft?.files.length ? draftFilesToPending(draft.files) : localFiles,
    [draft?.files, localFiles],
  );
  const setPendingFiles = useCallback((updater: PendingFile[] | ((prev: PendingFile[]) => PendingFile[])) => {
    // Resolve the new files array
    const newFiles = typeof updater === "function" ? updater(pendingFiles) : updater;
    if (channelId) {
      setDraftFiles(channelId, newFiles.map((pf) => ({
        name: pf.file.name,
        type: pf.file.type,
        size: pf.file.size,
        base64: pf.base64,
      })));
    } else {
      setLocalFiles(newFiles);
    }
  }, [channelId, pendingFiles, setDraftFiles]);
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

  const autoResize = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 140) + "px";
  }, []);

  // Auto-resize textarea when draft text is restored on mount/channel switch
  useEffect(() => {
    if (text && Platform.OS === "web") requestAnimationFrame(autoResize);
  }, [channelId]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if ((!trimmed && pendingFiles.length === 0) || disabled) return;
    onSend(trimmed, pendingFiles.length > 0 ? pendingFiles : undefined);
    if (channelId) clearDraft(channelId);
    else { setLocalText(""); setLocalFiles([]); }
    if (Platform.OS === "web") {
      const ta = textareaRef.current;
      if (ta) {
        ta.style.height = "auto";
        ta.focus();
      }
    } else {
      inputRef.current?.focus();
    }
  }, [text, pendingFiles, disabled, onSend, channelId, clearDraft]);

  // --- Audio recording ---
  const handleMicToggle = useCallback(async () => {
    if (recorder.isRecording) {
      const result = await recorder.stopRecording();
      if (result && onSendAudio) {
        onSendAudio(result.base64, result.format, text.trim() || undefined);
        if (channelId) clearDraft(channelId);
        else { setLocalText(""); setLocalFiles([]); }
        if (Platform.OS === "web") {
          const ta = textareaRef.current;
          if (ta) { ta.style.height = "auto"; ta.focus(); }
        }
      }
    } else {
      await recorder.startRecording();
    }
  }, [recorder.isRecording, recorder.stopRecording, recorder.startRecording, onSendAudio, text, channelId, clearDraft]);

  // Global keyboard listener for recording mode (textarea is hidden, so onKeyDown won't fire)
  useEffect(() => {
    if (!recorder.isRecording || Platform.OS !== "web") return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        recorder.cancelRecording();
      } else if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleMicToggle();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [recorder.isRecording, recorder.cancelRecording, handleMicToggle]);

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
      requestAnimationFrame(autoResize);
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
      const excludeValue = currentBotId ? `bot:${currentBotId}` : "";
      const scored = completions
        .filter((c) => c.value !== excludeValue)
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
    [completions, currentBotId]
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

  const hasContent = !!(text.trim() || pendingFiles.length > 0);
  const canSend = hasContent && !disabled;
  // Show stop button when streaming and user hasn't typed anything
  const showStop = !!isStreaming && !hasContent;
  // Show mic icon when input is empty and onSendAudio is available
  const showMic = !hasContent && !!onSendAudio && !isStreaming && Platform.OS === "web";

  // Web: use raw textarea for selectionStart access
  if (Platform.OS === "web") {
    return (
      <View style={{ flexShrink: 0, paddingBottom: insets.bottom, borderTopWidth: 1, borderTopColor: t.overlayLight, backgroundColor: t.surface }}>
        {/* Audio recorder error */}
        {recorder.error && (
          <div style={{ padding: "4px 20px", background: "rgba(239,68,68,0.08)" }}>
            <Text style={{ color: "#ef4444", fontSize: 12 }}>{recorder.error}</Text>
          </div>
        )}
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
                  border: `1px solid ${t.overlayBorder}`,
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
                      background: t.surfaceRaised,
                      fontSize: 10,
                      color: t.textMuted,
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

        <View className={`flex-row items-end ${isMobile ? "gap-1.5 px-2 py-2" : "gap-3 px-5 py-3"}`}>
          {/* Attach button */}
          <Pressable
            onPress={() => fileInputRef.current?.click()}
            disabled={disabled || recorder.isRecording}
            className="items-center justify-center rounded-lg hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: isMobile ? 36 : 44, height: isMobile ? 36 : 44, flexShrink: 0, opacity: recorder.isRecording ? 0.3 : 1 }}
          >
            <Paperclip size={isMobile ? 18 : 20} color={t.textDim} />
          </Pressable>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.pdf,.txt,.csv,.json,.md,.yaml,.yml,.xml,.html,.log,.py,.js,.ts,.sh,.doc,.docx,.xlsx,.xls,.pptx"
            style={{ display: "none" }}
            onChange={(e) => {
              handleFileSelect(e.target.files);
              e.target.value = "";
            }}
          />

          <div ref={containerRef} style={{ flex: 1, minWidth: 0, display: "flex" }}>
            {recorder.isRecording ? (
              <RecordingOverlay
                durationMs={recorder.durationMs}
                onCancel={recorder.cancelRecording}
                isMobile={isMobile}
              />
            ) : (
              <textarea
                ref={textareaRef}
                value={text}
                onChange={(e) => handleWebInput(e.target.value)}
                onKeyDown={handleWebKeyDown}
                onPaste={handlePaste}
                onBlur={() => setTimeout(() => setShowMenu(false), 200)}
                placeholder="Type a message..."
                autoFocus={!isMobile}
                rows={1}
                style={{
                  flex: 1,
                  fontFamily: "inherit",
                  fontSize: 15,
                  lineHeight: "1.5",
                  padding: isMobile ? "8px 12px" : "10px 16px",
                  borderRadius: 10,
                  border: `1px solid ${t.overlayLight}`,
                  background: t.surfaceRaised,
                  color: t.text,
                  resize: "none",
                  outline: "none",
                  minHeight: isMobile ? 36 : 44,
                  maxHeight: 140,
                  overflow: "auto",
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = t.overlayBorder;
                }}
                onBlurCapture={(e) => {
                  e.target.style.borderColor = t.overlayLight;
                }}
              />
            )}
          </div>
          {/* Per-turn model picker — hidden on mobile to save space */}
          {Platform.OS === "web" && onModelOverrideChange && !isMobile && (
            <div ref={modelPickerRef} style={{ position: "relative", display: "flex", alignItems: "center" }}>
              {modelOverride ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    background: t.purpleSubtle,
                    border: `1px solid ${t.purpleBorder}`,
                    borderRadius: 6,
                    padding: "4px 8px",
                    fontSize: 11,
                    color: t.purple,
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
                  style={{ width: 44, height: 44, opacity: 0.6 }}
                >
                  <Cpu size={16} color={t.textDim} />
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
            onPress={
              showStop ? onCancel
              : recorder.isRecording ? handleMicToggle
              : showMic ? handleMicToggle
              : handleSend
            }
            disabled={!canSend && !showStop && !showMic && !recorder.isRecording}
            className="items-center justify-center rounded-lg"
            style={{
              width: isMobile ? 36 : 44,
              height: isMobile ? 36 : 44,
              flexShrink: 0,
              backgroundColor: showStop ? "#ef4444"
                : recorder.isRecording ? "#ef4444"
                : canSend ? t.accent
                : showMic ? "transparent"
                : "transparent",
              opacity: canSend || showStop || showMic || recorder.isRecording ? 1 : 0.4,
            }}
          >
            {showStop ? (
              <Square size={16} color="white" fill="white" />
            ) : recorder.isRecording ? (
              <Send size={isMobile ? 16 : 18} color="white" />
            ) : showMic ? (
              <Mic size={isMobile ? 16 : 18} color={t.textDim} />
            ) : (
              <Send size={isMobile ? 16 : 18} color={canSend ? "white" : t.textDim} />
            )}
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
    <View className="flex-row items-end gap-2 px-4 py-3" style={{ borderTopWidth: 1, borderTopColor: t.overlayLight, backgroundColor: t.surface }}>
      <TextInput
        ref={inputRef}
        className="flex-1 bg-surface-raised rounded-xl px-4 py-3 text-text text-[15px] min-h-[44px] max-h-[140px]"
        style={{ borderWidth: 1, borderColor: t.overlayLight }}
        placeholder="Type a message..."
        placeholderTextColor={t.textDim}
        value={text}
        onChangeText={setText}
        onKeyPress={handleKeyPress}
        multiline
        editable={!disabled}
      />
      <Pressable
        onPress={showStop ? onCancel : handleSend}
        disabled={!(text.trim() && !disabled) && !showStop}
        className="items-center justify-center rounded-lg"
        style={{
          width: 44,
          height: 44,
          backgroundColor: showStop ? "#ef4444" : text.trim() && !disabled ? t.accent : "transparent",
          opacity: (text.trim() && !disabled) || showStop ? 1 : 0.4,
        }}
      >
        {showStop ? (
          <Square size={16} color="white" fill="white" />
        ) : (
          <Send size={18} color={text.trim() && !disabled ? "white" : t.textDim} />
        )}
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
