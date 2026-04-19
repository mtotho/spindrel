import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { Send, Square, Paperclip, X, Cpu, Mic, Check } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useAudioRecorder } from "../../hooks/useAudioRecorder";
import { RecordingOverlay } from "./RecordingOverlay";
import { useThemeTokens } from "../../theme/tokens";
import { useDraftsStore, type DraftFile } from "../../stores/drafts";
import { TiptapChatInput, type TiptapChatInputHandle } from "./TiptapChatInput";
import { createPortal } from "react-dom";
import { LlmModelDropdown } from "../shared/LlmModelDropdown";
import { ContextChip } from "./ContextChip";

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

export function MessageInput({ onSend, onSendAudio, disabled, isStreaming, onCancel, modelOverride, modelProviderIdOverride, onModelOverrideChange, defaultModel, currentBotId, isMultiBot, channelId, onSlashCommand, isQueued, onCancelQueue, onSendNow, configOverhead, onConfigOverheadClick }: Props) {
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<TiptapChatInputHandle>(null);
  const editorWrapperRef = useRef<HTMLDivElement>(null);

  const handleSend = useCallback(() => {
    const message = (editorRef.current?.getMarkdown() ?? text).trim();
    if ((!message && pendingFiles.length === 0) || disabled) return;
    onSend(message, pendingFiles.length > 0 ? pendingFiles : undefined);
    if (channelId) clearDraft(channelId);
    else { setLocalText(""); setLocalFiles([]); }
    editorRef.current?.clear();
    editorRef.current?.focus();
  }, [text, pendingFiles, disabled, onSend, channelId, clearDraft]);

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

  // "Send now" — cancel stream and send immediately (web only)
  const handleSendNowLocal = useCallback(() => {
    const message = (editorRef.current?.getMarkdown() ?? text).trim();
    if ((!message && pendingFiles.length === 0) || disabled) return;
    onSendNow?.(message, pendingFiles.length > 0 ? pendingFiles : undefined);
    if (channelId) clearDraft(channelId);
    else { setLocalText(""); setLocalFiles([]); }
    editorRef.current?.clear();
    editorRef.current?.focus();
  }, [text, pendingFiles, disabled, onSendNow, channelId, clearDraft]);

  const sendBtnBg = showStop ? "#ef4444"
      : recorder.isRecording ? "#ef4444"
      : canSend ? t.accent
      : "transparent";
    const sendBtnOpacity = canSend || showStop || showMic || recorder.isRecording ? 1 : 0.4;

    return (
      <div style={{ flexShrink: 0, boxShadow: "0 -1px 8px rgba(0,0,0,0.06)", backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)", backgroundColor: `${t.surface}e6` }}>
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
              padding: isMobile ? "3px 8px" : "3px 20px",
              fontSize: 12,
              color: t.textMuted,
              userSelect: "none",
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
            display: "flex",
            flexDirection: "row",
            alignItems: "flex-end",
            gap: isMobile ? 6 : 12,
            padding: isMobile ? "8px 8px" : "12px 20px",
          }}
        >
          {/* Attach button */}
          <button
            className="input-action-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || recorder.isRecording}
            style={{
              width: isMobile ? 36 : 44,
              height: isMobile ? 36 : 44,
              flexShrink: 0,
              opacity: recorder.isRecording ? 0.3 : 1,
            }}
            title="Attach file"
          >
            <Paperclip size={isMobile ? 18 : 20} color={t.textDim} />
          </button>
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

          {/* Editor wrapper */}
          <div
            ref={editorWrapperRef}
            onFocusCapture={() => { if (editorWrapperRef.current) editorWrapperRef.current.style.boxShadow = `inset 0 0 0 1px ${t.overlayBorder}`; }}
            onBlurCapture={() => { if (editorWrapperRef.current) editorWrapperRef.current.style.boxShadow = `inset 0 0 0 1px ${t.overlayLight}`; }}
            style={{
              flex: 1,
              minWidth: 0,
              minHeight: isMobile ? 36 : 44,
              maxHeight: 280,
              background: t.surfaceRaised,
              borderRadius: 16,
              border: "none",
              boxShadow: `inset 0 0 0 1px ${t.overlayLight}`,
              overflow: "hidden",
              display: "flex", flexDirection: "row",
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
                disabled={disabled}
                autoFocus={!isMobile}
                isMobile={isMobile}
                currentBotId={currentBotId}
                isMultiBot={isMultiBot}
              />
            )}
          </div>

          {/* Skills-in-context chip — on mobile, hides the button when empty to save toolbar space. */}
          {channelId && (
            <ContextChip
              channelId={channelId}
              composerText={text}
              botId={currentBotId}
              onInsertSkillTag={(skillId) => {
                editorRef.current?.insertText(`@skill:${skillId} `);
              }}
              size={isMobile ? 32 : 36}
              hideWhenEmpty={isMobile}
              compact={isMobile}
            />
          )}

          {/* Per-turn model picker — hidden on mobile to save space */}
          {onModelOverrideChange && !isMobile && (
            <div ref={modelPickerRef} style={{ position: "relative", display: "flex", flexDirection: "row", alignItems: "center" }}>
              {modelOverride ? (
                <div
                  style={{
                    display: "flex", flexDirection: "row",
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
                    onClick={(e) => { e.stopPropagation(); onModelOverrideChange(undefined, null); }}
                    style={{ marginLeft: 2, cursor: "pointer", fontSize: 12, lineHeight: 1 }}
                  >
                    ✕
                  </span>
                </div>
              ) : (
                <button
                  className="input-action-btn"
                  onClick={() => setShowModelPicker(true)}
                  style={{ width: 44, height: 44, opacity: 0.6 }}
                  title="Select model for this message"
                >
                  <Cpu size={16} color={t.textDim} />
                </button>
              )}
              {showModelPicker && (() => {                const rect = modelPickerRef.current?.getBoundingClientRect();
                const dropdownRight = rect ? window.innerWidth - rect.right : 16;
                const dropdownBottom = rect ? window.innerHeight - rect.top + 8 : 80;
                return createPortal(
                  <>
                    <div
                      onClick={() => setShowModelPicker(false)}
                      style={{ position: "fixed", inset: 0, zIndex: 50000 }}
                    />
                    <div style={{ position: "fixed", bottom: dropdownBottom, right: dropdownRight, zIndex: 50001, width: 320 }}>
                      <LlmModelDropdown
                        value={modelOverride ?? ""}
                        selectedProviderId={modelProviderIdOverride}
                        onChange={(m: string, pid?: string | null) => {
                          onModelOverrideChange(m || undefined, pid);
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
          {/* Config overhead indicator — desktop only, visible only when overhead is meaningful.
              Below 20% the bar was rendering as a phantom hairline between the model picker
              and mic, so the threshold matches the band where the color/opacity actually changes. */}
          {!isMobile && configOverhead != null && configOverhead >= 0.2 && (
            <button
              onClick={onConfigOverheadClick}
              title={`Config overhead: ${Math.round(configOverhead * 100)}% of context window used by tools, skills, and prompts`}
              style={{
                width: 4, height: 24, flexShrink: 0, borderRadius: 2,
                border: "none", padding: 0, cursor: "pointer",
                backgroundColor: configOverhead > 0.4 ? "#ef4444" : "#eab308",
                opacity: 0.9,
                transition: "background-color 0.3s, opacity 0.3s",
              }}
            />
          )}
          {/* Send / Stop / Mic button */}
          <button
            className="send-btn"
            onClick={
              (showStop && stopArmed) ? onCancel
              : recorder.isRecording ? handleMicToggle
              : showMic ? handleMicToggle
              : showStop ? undefined  // visible but not armed yet
              : handleSend
            }
            disabled={!canSend && !(showStop && stopArmed) && !showMic && !recorder.isRecording}
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              width: isMobile ? 36 : 44,
              height: isMobile ? 36 : 44,
              flexShrink: 0,
              borderRadius: 12,
              border: "none",
              padding: 0,
              cursor: (!canSend && !(showStop && stopArmed) && !showMic && !recorder.isRecording) ? "default" : "pointer",
              background: (canSend && !showStop && !recorder.isRecording) ? `linear-gradient(135deg, ${t.accent}, ${t.purple})` : undefined,
              backgroundColor: (canSend && !showStop && !recorder.isRecording) ? undefined : sendBtnBg,
              opacity: (showStop && !stopArmed) ? 0.4 : sendBtnOpacity,
              transition: "background-color 0.15s, opacity 0.15s",
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
          </button>
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
