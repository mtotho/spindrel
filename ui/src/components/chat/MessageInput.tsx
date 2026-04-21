import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { Send, Square, X, Mic, Check } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useAudioRecorder } from "../../hooks/useAudioRecorder";
import { RecordingOverlay } from "./RecordingOverlay";
import { useThemeTokens } from "../../theme/tokens";
import { useDraftsStore, type DraftFile } from "../../stores/drafts";
import { TiptapChatInput, type TiptapChatInputHandle } from "./TiptapChatInput";
import { resolveSlashCommand } from "./slashCommands";
import { createPortal } from "react-dom";
import { LlmModelDropdownContent } from "../shared/LlmModelDropdown";
import { ComposerAddMenu } from "./ComposerAddMenu";
import type { SlashCommandId, SlashCommandSurface } from "../../types/api";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

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
  modelProviderIdOverride?: string | null;
  onModelOverrideChange?: (m: string | undefined, providerId?: string | null) => void;
  defaultModel?: string;
  /** Current channel's bot ID — excluded from @-mention completions (single-bot channels only) */
  currentBotId?: string;
  /** When true (multi-bot channel), primary bot is NOT excluded from @-mentions */
  isMultiBot?: boolean;
  /** Channel ID for persisting drafts across navigation */
  channelId?: string;
  /** Handler for slash commands typed in the input */
  onSlashCommand?: (id: string) => void;
  slashSurface?: SlashCommandSurface;
  availableSlashCommands?: SlashCommandId[];
  /** Whether a message is queued behind the current response */
  isQueued?: boolean;
  /** Cancel a queued message */
  onCancelQueue?: () => void;
  /** Interrupt current response and send immediately */
  onSendNow?: (message: string, files?: PendingFile[]) => void;
  /** Config overhead (0-1) — tools/skills/system prompt cost as fraction of context window */
  configOverhead?: number | null;
  /** Called when user clicks the config overhead indicator */
  onConfigOverheadClick?: () => void;
  /** Constrained-container mode. Tightens outer + editor padding and the
   *  card's corner radius so the composer fits naturally inside a narrow
   *  dock / drawer on desktop. Behavior unchanged. */
  compact?: boolean;
  chatMode?: "default" | "terminal";
}

/** Short non-blocking haptic buzz. No-op on iOS Safari (vibrate is
 *  gated behind a user gesture and unsupported there) and on desktop. */
function tapHaptic(pattern: number | number[] = 8) {
  try { (navigator as Navigator & { vibrate?: (p: number | number[]) => boolean }).vibrate?.(pattern); } catch { /* ignore */ }
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

export function MessageInput({ onSend, onSendAudio, disabled, isStreaming, onCancel, modelOverride, modelProviderIdOverride, onModelOverrideChange, defaultModel, currentBotId, isMultiBot, channelId, onSlashCommand, slashSurface = "channel", availableSlashCommands, isQueued, onCancelQueue, onSendNow, configOverhead, onConfigOverheadClick, compact: compactLayout = false, chatMode = "default" }: Props) {
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
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
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<TiptapChatInputHandle>(null);
  const editorWrapperRef = useRef<HTMLDivElement>(null);
  const [isFocused, setIsFocused] = useState(false);
  const collapsed = false;

  const handleSend = useCallback(() => {
    const message = (editorRef.current?.getMarkdown() ?? text).trim();
    if ((!message && pendingFiles.length === 0) || disabled) return;
    const slashCommand = resolveSlashCommand(message, slashSurface, availableSlashCommands);
    if (slashCommand && pendingFiles.length === 0) {
      onSlashCommand?.(slashCommand);
      if (channelId) clearDraft(channelId);
      else { setLocalText(""); setLocalFiles([]); }
      editorRef.current?.clear();
      editorRef.current?.focus();
      return;
    }
    tapHaptic(8);
    onSend(message, pendingFiles.length > 0 ? pendingFiles : undefined);
    if (channelId) clearDraft(channelId);
    else { setLocalText(""); setLocalFiles([]); }
    editorRef.current?.clear();
    editorRef.current?.focus();
  }, [
    text,
    pendingFiles,
    disabled,
    slashSurface,
    availableSlashCommands,
    onSlashCommand,
    onSend,
    channelId,
    clearDraft,
  ]);

  // --- Audio recording ---
  const handleMicToggle = useCallback(async () => {
    if (recorder.isRecording) {
      const result = await recorder.stopRecording();
      if (result && onSendAudio) {
        onSendAudio(result.base64, result.format, text.trim() || undefined);
        if (channelId) clearDraft(channelId);
        else { setLocalText(""); setLocalFiles([]); }
        editorRef.current?.clear();
        editorRef.current?.focus();
      }
    } else {
      await recorder.startRecording();
    }
  }, [recorder.isRecording, recorder.stopRecording, recorder.startRecording, onSendAudio, text, channelId, clearDraft]);

  // Global keyboard listener for recording mode (editor is hidden, so onKeyDown won't fire)
  useEffect(() => {
    if (!recorder.isRecording) return;
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

  // Handle image paste from Tiptap editor — images go to pendingFiles
  const handleImagePaste = useCallback(
    (files: File[]) => {
      const dt = new DataTransfer();
      files.forEach((f) => dt.items.add(f));
      handleFileSelect(dt.files);
    },
    [handleFileSelect]
  );

  const hasContent = !!(text.trim() || pendingFiles.length > 0);
  const canSend = hasContent && !disabled;
  // Show stop button when streaming and user hasn't typed anything
  const showStop = !!isStreaming && !hasContent;
  // Grace period: stop button is visible but disabled briefly after streaming starts
  // to prevent accidental taps (especially on mobile where send → stop is same position)
  const [stopArmed, setStopArmed] = useState(false);
  useEffect(() => {
    if (showStop) {
      const timer = setTimeout(() => setStopArmed(true), 800);
      return () => clearTimeout(timer);
    }
    setStopArmed(false);
  }, [showStop]);
  // Show mic icon when input is empty and onSendAudio is available
  const showMic = !hasContent && !!onSendAudio && !isStreaming;
  // Queue bar: visible when streaming and user has typed content, or when a message is already queued
  const showQueueBar = !!isStreaming && (hasContent || !!isQueued);
  const isTerminalMode = chatMode === "terminal";
  const terminalBorder = `${t.surfaceBorder}cc`;
  const addMenuVisible = !isTerminalMode || !collapsed;
  const modelPillVisible = onModelOverrideChange && !isTerminalMode;
  const terminalHint = text.trim().startsWith("/") ? "command" : "message";
  const hasOverride = !!modelOverride;
  const effectiveName = modelOverride
    ? modelOverride.split("/").pop()
    : defaultModel?.split("/").pop();
  const canRenderModelLabel = !!effectiveName;
  const terminalPlaceholder = compactLayout
    ? "Type / or enter a message..."
    : "Type / for commands or enter a message...";

  // "Send now" — cancel stream and send immediately (web only)
  const handleSendNowLocal = useCallback(() => {
    const message = (editorRef.current?.getMarkdown() ?? text).trim();
    if ((!message && pendingFiles.length === 0) || disabled) return;
    const slashCommand = resolveSlashCommand(message, slashSurface, availableSlashCommands);
    if (slashCommand && pendingFiles.length === 0) {
      onSlashCommand?.(slashCommand);
      if (channelId) clearDraft(channelId);
      else { setLocalText(""); setLocalFiles([]); }
      editorRef.current?.clear();
      editorRef.current?.focus();
      return;
    }
    tapHaptic([4, 30, 8]);
    onSendNow?.(message, pendingFiles.length > 0 ? pendingFiles : undefined);
    if (channelId) clearDraft(channelId);
    else { setLocalText(""); setLocalFiles([]); }
    editorRef.current?.clear();
    editorRef.current?.focus();
  }, [
    text,
    pendingFiles,
    disabled,
    slashSurface,
    availableSlashCommands,
    onSlashCommand,
    onSendNow,
    channelId,
    clearDraft,
  ]);

  const sendBtnBg = showStop ? "#ef4444"
      : recorder.isRecording ? "#ef4444"
      : canSend ? t.accent
      : "transparent";
    const sendBtnOpacity = canSend || showStop || showMic || recorder.isRecording ? 1 : 0.4;

    return (
      <div style={{ flexShrink: 0, marginTop: isTerminalMode ? 10 : 0 }}>
        {/* Audio recorder error */}
        {recorder.error && (
          <div style={{ padding: "4px 20px", background: "rgba(239,68,68,0.08)" }}>
            <span style={{ color: "#ef4444", fontSize: 12 }}>{recorder.error}</span>
          </div>
        )}
        {/* Pending file previews */}
        {pendingFiles.length > 0 && (
          <div
            style={{
              display: "flex", flexDirection: "row",
              gap: 8,
              padding: isTerminalMode ? "8px 12px 0" : "8px 20px 0",
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
                      display: "flex", flexDirection: "row",
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
                    display: "flex", flexDirection: "row",
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

        {/* Queue bar — shown when typing during a stream or when a message is queued */}
        {showQueueBar && (
          <div
            className="queue-bar"
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              padding: isTerminalMode ? "6px 12px" : isMobile ? "3px 8px" : "3px 20px",
              fontSize: 12,
              color: isTerminalMode ? t.textDim : t.textMuted,
              userSelect: "none",
              borderBottom: isTerminalMode ? `1px solid ${terminalBorder}` : undefined,
              backgroundColor: isTerminalMode ? `${t.overlayLight}22` : undefined,
            }}
          >
            {isQueued && !hasContent ? (
              <>
                <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
                  <Check size={12} color={t.success} />
                  <span>Message queued</span>
                </span>
                <button
                  onClick={onCancelQueue}
                  style={{
                    background: "none",
                    border: "none",
                    color: t.textDim,
                    fontSize: 12,
                    cursor: "pointer",
                    padding: "2px 6px",
                    borderRadius: 4,
                  }}
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
                  <span className="typing-dot" style={{ width: 4, height: 4, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
                  <span>Responding — message will be queued</span>
                </span>
                <button
                  onClick={handleSendNowLocal}
                  style={{
                    background: "none",
                    border: "none",
                    color: t.accent,
                    fontSize: 12,
                    cursor: "pointer",
                    padding: "2px 6px",
                    borderRadius: 4,
                    fontWeight: 500,
                  }}
                >
                  Send now
                </button>
              </>
            )}
          </div>
        )}

        <div
          style={{
            padding: isTerminalMode
              ? "0 0 3px"
              : (compactLayout ? "0 10px 10px" : isMobile ? "0 12px 12px" : "0 16px 14px"),
          }}
        >
          {/* One card. Editor on top (flat — no inner border/bg), actions on bottom.
              Constant 20px radius (no pill morph) + outer drop-shadow elevation
              so the composer reads as a lifted surface above the chat. */}
          <div
            ref={editorWrapperRef}
            onFocusCapture={() => setIsFocused(true)}
            onBlurCapture={() => {
              // Delay so focus bouncing through portals (mentions, + menu) doesn't
              // trigger a visible collapse flash on mobile.
              setTimeout(() => {
                if (editorWrapperRef.current && !editorWrapperRef.current.contains(document.activeElement)) {
                  setIsFocused(false);
                }
              }, 0);
            }}
            style={{
              display: "flex",
              flexDirection: "column",
              background: isTerminalMode ? `${t.surfaceRaised}` : `${t.surfaceRaised}d9`,
              backdropFilter: isTerminalMode ? undefined : "blur(14px)",
              WebkitBackdropFilter: isTerminalMode ? undefined : "blur(14px)",
              borderRadius: isTerminalMode ? 0 : compactLayout ? 14 : 20,
              border: isTerminalMode ? "none" : undefined,
              boxShadow: isTerminalMode
                ? "none"
                : isFocused
                  ? `inset 0 0 0 1px ${t.accentBorder}, inset 0 1px 0 ${t.overlayLight}, 0 0 0 3px ${t.accent}1a, 0 6px 24px -8px rgba(0,0,0,0.45), 0 2px 6px -2px rgba(0,0,0,0.3)`
                  : `inset 0 1px 0 ${t.overlayLight}, 0 6px 24px -8px rgba(0,0,0,0.45), 0 2px 6px -2px rgba(0,0,0,0.3)`,
              overflow: "hidden",
              transition: "box-shadow 0.15s, border-color 0.15s",
            }}
          >
            {/* Editor area — no own border/background; inherits the card.
                Mobile collapsed mode inlines a compact mic on the right so
                the single-row pill stays useful. */}
            <div
              style={{
                minHeight: compactLayout ? 44 : isMobile ? 45 : 60,
                maxHeight: 260,
                minWidth: 0,
                padding: collapsed ? "4px 6px 4px 14px" : isTerminalMode ? "6px 8px 0" : compactLayout ? "8px 12px 2px" : isMobile ? "6px 10px 2px" : "12px 16px 4px",
                overflow: "hidden",
                display: "flex",
                flexDirection: "row",
                alignItems: collapsed ? "center" : undefined,
                gap: collapsed ? 6 : 0,
              }}
            >
              {recorder.isRecording ? (
                <RecordingOverlay
                  durationMs={recorder.durationMs}
                  onCancel={recorder.cancelRecording}
                  isMobile={isMobile}
                />
              ) : (
                <TiptapChatInput
                  ref={editorRef}
                  key={channelId}
                  text={text}
                  onTextChange={setText}
                  onSubmit={handleSend}
                  onImagePaste={handleImagePaste}
                  onSlashCommand={onSlashCommand}
                  slashSurface={slashSurface}
                  availableSlashCommands={availableSlashCommands}
                  disabled={disabled}
                  autoFocus={!isMobile}
                  isMobile={isMobile}
                  currentBotId={currentBotId}
                  isMultiBot={isMultiBot}
                  placeholder={isTerminalMode ? terminalPlaceholder : undefined}
                  chatMode={chatMode}
                />
              )}
              {/* Collapsed mobile: inline compact mic so the one-row pill
                  still offers voice-input without opening the full card. */}
              {collapsed && (
                <button
                  type="button"
                  className="input-action-btn"
                  onClick={handleMicToggle}
                  style={{ width: 30, height: 30, flexShrink: 0, opacity: 0.8 }}
                  aria-label="Record audio"
                  title="Record audio"
                >
                  <Mic size={16} color={t.textDim} />
                </button>
              )}
            </div>

            {/* Action row — attached to the bottom of the card. Hidden on
                mobile when the card is idle (collapsed to a one-row pill). */}
            <div
              onClick={(e) => { if (e.target === e.currentTarget) editorRef.current?.focus(); }}
              style={{
                display: collapsed ? "none" : "flex",
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                minWidth: 0,
                padding: isTerminalMode ? "2px 8px 4px" : compactLayout ? "3px 6px 4px" : isMobile ? "2px 4px 3px" : "4px 8px 6px",
                cursor: "text",
                borderTop: isTerminalMode ? undefined : undefined,
                backgroundColor: isTerminalMode ? "transparent" : undefined,
              }}
            >
              {addMenuVisible ? (
                <ComposerAddMenu
                  channelId={channelId}
                  botId={currentBotId}
                  composerText={text}
                  onInsertSkillTag={(skillId) => {
                    editorRef.current?.insertMention(`skill:${skillId}`);
                  }}
                  onAttachFiles={(files) => handleFileSelect(files)}
                  disabled={disabled || recorder.isRecording}
                  isMobile={isMobile}
                />
              ) : (
                <div style={{ width: 32, flexShrink: 0 }} />
              )}

              {isTerminalMode && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "row",
                    alignItems: "center",
                  gap: 8,
                  fontSize: 11,
                  color: t.textDim,
                  fontFamily: TERMINAL_FONT_STACK,
                  whiteSpace: "nowrap",
                  minWidth: 0,
                  overflow: "hidden",
                }}
              >
                  <span style={{ flexShrink: 0 }}>{terminalHint}</span>
                  {pendingFiles.length > 0 && (
                    <span style={{ color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {pendingFiles.length} file{pendingFiles.length === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
              )}

              <div style={{ flex: 1 }} />

              {/* Config overhead indicator — desktop only. Tucks before the model pill. */}
              {!isTerminalMode && !isMobile && configOverhead != null && configOverhead >= 0.2 && (
                <button
                  onClick={onConfigOverheadClick}
                  title={`Config overhead: ${Math.round(configOverhead * 100)}% of context window used by tools, skills, and prompts`}
                  style={{
                    width: 4, height: 20, flexShrink: 0, borderRadius: 2,
                    border: "none", padding: 0, cursor: "pointer",
                    backgroundColor: configOverhead > 0.4 ? "#ef4444" : "#eab308",
                    opacity: 0.9,
                    transition: "background-color 0.3s, opacity 0.3s",
                  }}
                />
              )}

              {/* Inline model pill — desktop only. Always visible showing the current
                  effective model; clicking opens the LlmModelDropdown portal. Purple
                  accent only when a channel-level override is set. */}
              {modelPillVisible && (() => {
                const canRenderPill = !!effectiveName;
                return (
                  <div ref={modelPickerRef} style={{ position: "relative", display: "flex", flexDirection: "row", alignItems: "center" }}>
                    {canRenderPill ? (
                      <button
                        type="button"
                        onClick={() => setShowModelPicker(true)}
                        title={hasOverride ? `Channel model override: ${modelOverride}` : `Model: ${defaultModel ?? effectiveName}`}
                        style={{
                          display: "flex", flexDirection: "row",
                          alignItems: "center",
                          gap: 4,
                          background: hasOverride ? t.purpleSubtle : "transparent",
                          border: `1px solid ${hasOverride ? t.purpleBorder : "transparent"}`,
                          borderRadius: 8,
                          padding: "4px 8px",
                          fontSize: 11,
                          color: hasOverride ? t.purple : t.textMuted,
                          cursor: "pointer",
                          whiteSpace: "nowrap",
                          maxWidth: isMobile ? 120 : 200,
                        }}
                      >
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                          {effectiveName}
                        </span>
                        {hasOverride && (
                          <span
                            onClick={(e) => { e.stopPropagation(); onModelOverrideChange(undefined, null); }}
                            style={{ marginLeft: 2, cursor: "pointer", fontSize: 12, lineHeight: 1 }}
                          >
                            ✕
                          </span>
                        )}
                      </button>
                    ) : (
                      <button
                        className="input-action-btn"
                        onClick={() => setShowModelPicker(true)}
                        style={{ width: 32, height: 32, opacity: 0.6 }}
                        title="Select channel model"
                      >
                        <span style={{ fontSize: 11, color: t.textDim }}>model</span>
                      </button>
                    )}
                    {showModelPicker && (() => {
                      const rect = modelPickerRef.current?.getBoundingClientRect();
                      const dropdownRight = rect ? window.innerWidth - rect.right : 16;
                      const dropdownBottom = rect ? window.innerHeight - rect.top + 8 : 80;
                      return createPortal(
                        <>
                          <div
                            onClick={() => setShowModelPicker(false)}
                            style={{ position: "fixed", inset: 0, zIndex: 50000 }}
                          />
                          <div style={{ position: "fixed", bottom: dropdownBottom, right: dropdownRight, zIndex: 50001, width: 320 }}>
                            <LlmModelDropdownContent
                              value={modelOverride ?? ""}
                              selectedProviderId={modelProviderIdOverride}
                              onSelect={(m, pid) => {
                                onModelOverrideChange(m || undefined, pid);
                                setShowModelPicker(false);
                              }}
                            />
                            {hasOverride && (
                              <button
                                type="button"
                                onClick={() => {
                                  onModelOverrideChange(undefined, null);
                                  setShowModelPicker(false);
                                }}
                                style={{
                                  marginTop: 6,
                                  width: "100%",
                                  background: t.surfaceRaised,
                                  border: `1px solid ${t.surfaceBorder}`,
                                  borderRadius: 8,
                                  padding: "8px 12px",
                                  color: t.textMuted,
                                  fontSize: 12,
                                  cursor: "pointer",
                                  textAlign: "left",
                                }}
                              >
                                Clear override — inherit {defaultModel ?? "default"}
                              </button>
                            )}
                          </div>
                        </>,
                        document.body
                      );
                    })()}
                  </div>
                );
              })()}

              {/* Send / Stop / Mic button */}
              <button
                className="send-btn"
                onClick={
                  (showStop && stopArmed) ? () => { tapHaptic(12); onCancel?.(); }
                  : recorder.isRecording ? handleMicToggle
                  : showMic ? handleMicToggle
                  : showStop ? undefined
                  : handleSend
                }
                disabled={!canSend && !(showStop && stopArmed) && !showMic && !recorder.isRecording}
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 36,
                  height: 36,
                  flexShrink: 0,
                  borderRadius: isTerminalMode ? 0 : 10,
                  border: isTerminalMode ? "none" : "none",
                  padding: 0,
                  cursor: (!canSend && !(showStop && stopArmed) && !showMic && !recorder.isRecording) ? "default" : "pointer",
                  background: isTerminalMode ? undefined : (canSend && !showStop && !recorder.isRecording) ? `linear-gradient(135deg, ${t.accent}, ${t.purple})` : undefined,
                  backgroundColor: isTerminalMode
                    ? "transparent"
                    : (canSend && !showStop && !recorder.isRecording) ? undefined : sendBtnBg,
                  opacity: (showStop && !stopArmed) ? 0.4 : sendBtnOpacity,
                  transition: "background-color 0.15s, opacity 0.15s, border-color 0.15s",
                }}
              >
                {showStop ? (
                  <Square size={14} color={isTerminalMode ? t.accent : "white"} fill={isTerminalMode ? t.accent : "white"} />
                ) : recorder.isRecording ? (
                  <Send size={isMobile ? 14 : 16} color={isTerminalMode ? t.accent : "white"} />
                ) : showMic ? (
                  <Mic size={isMobile ? 14 : 16} color={t.textDim} />
                ) : (
                  <Send size={isMobile ? 14 : 16} color={canSend ? (isTerminalMode ? t.accent : "white") : t.textDim} />
                )}
              </button>
            </div>
          </div>
          {isTerminalMode && onModelOverrideChange && (
            <div
              ref={modelPickerRef}
              style={{
                padding: "8px 0 0 8px",
                display: "flex",
                flexDirection: "row",
                justifyContent: "flex-start",
                alignItems: "center",
                minHeight: 14,
                minWidth: 0,
              }}
            >
              <button
                type="button"
                onClick={() => setShowModelPicker(true)}
                title={hasOverride ? `Channel model override: ${modelOverride}` : `Model: ${defaultModel ?? effectiveName ?? "default"}`}
                style={{
                  background: "transparent",
                  border: "none",
                  padding: 0,
                  margin: 0,
                  color: hasOverride ? t.text : t.textDim,
                  fontFamily: TERMINAL_FONT_STACK,
                  fontSize: 11.5,
                  lineHeight: 1.2,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  maxWidth: "100%",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {canRenderModelLabel ? effectiveName : "select model"}
              </button>
              {showModelPicker && (() => {
                const rect = modelPickerRef.current?.getBoundingClientRect();
                const dropdownWidth = Math.min(320, Math.max(220, window.innerWidth - 24));
                const dropdownLeft = Math.max(12, Math.min(rect?.left ?? 16, window.innerWidth - dropdownWidth - 12));
                const dropdownBottom = rect ? window.innerHeight - rect.top + 8 : 80;
                return createPortal(
                  <>
                    <div
                      onClick={() => setShowModelPicker(false)}
                      style={{ position: "fixed", inset: 0, zIndex: 50000 }}
                    />
                    <div style={{ position: "fixed", bottom: dropdownBottom, left: dropdownLeft, zIndex: 50001, width: dropdownWidth }}>
                      <LlmModelDropdownContent
                        value={modelOverride ?? ""}
                        selectedProviderId={modelProviderIdOverride}
                        onSelect={(m, pid) => {
                          onModelOverrideChange(m || undefined, pid);
                          setShowModelPicker(false);
                        }}
                      />
                      {hasOverride && (
                        <button
                          type="button"
                          onClick={() => {
                            onModelOverrideChange(undefined, null);
                            setShowModelPicker(false);
                          }}
                          style={{
                            marginTop: 6,
                            width: "100%",
                            background: t.surfaceRaised,
                            border: `1px solid ${t.surfaceBorder}`,
                            borderRadius: 8,
                            padding: "8px 12px",
                            color: t.textMuted,
                            fontSize: 12,
                            cursor: "pointer",
                            textAlign: "left",
                          }}
                        >
                          Clear override - inherit {defaultModel ?? "default"}
                        </button>
                      )}
                    </div>
                  </>,
                  document.body
                );
              })()}
            </div>
          )}
        </div>
      </div>
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
