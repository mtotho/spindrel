import { useState, useRef, useCallback, useEffect, type DragEvent } from "react";
import { AlertCircle, Check, FileText, Image as ImageIcon, Loader2, Mic, Send, Square, UploadCloud, X } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useAudioRecorder } from "../../hooks/useAudioRecorder";
import { RecordingOverlay } from "./RecordingOverlay";
import { useThemeTokens } from "../../theme/tokens";
import { TiptapChatInput, type TiptapChatInputHandle } from "./TiptapChatInput";
import { toast } from "../../stores/toast";
import { useSlashCommandList } from "@/src/api/hooks/useSlashCommands";
import { ComposerAddMenu } from "./ComposerAddMenu";
import { resolveComposerSubmitIntent, type ComposerSubmitIntent } from "./composerSubmit";
import { ComposerApprovalModeControl } from "./ComposerApprovalModeControl";
import { ComposerModelControl } from "./ComposerModelControl";
import { ComposerPlanControl } from "./ComposerPlanControl";
import type { HarnessApprovalMode } from "./harnessApprovalModeControl";
import { shouldShowComposerPlanControl, type PlanModeControlVisibility } from "./planControlVisibility";
import { useComposerDraftFiles, type PendingFile } from "./useComposerDraftFiles";
import { formatFileSize } from "./attachmentRouting";
import type { SlashCommandId, SlashCommandSurface } from "../../types/api";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

export type { PendingFile } from "./useComposerDraftFiles";

interface Props {
  onSend: (message: string, files?: PendingFile[]) => void;
  onSendAudio?: (audioBase64: string, audioFormat: string, message?: string) => void;
  disabled?: boolean;
  sendDisabledReason?: string | null;
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
  /** Channel/session key for persisting drafts across navigation */
  channelId?: string;
  /** Parent channel used to resolve contextual tools/skills in session views. */
  toolContextChannelId?: string;
  /** Handler for slash commands typed in the input */
  onSlashCommand?: (id: string, args?: string[], argsText?: string) => void;
  slashSurface?: SlashCommandSurface;
  availableSlashCommands?: SlashCommandId[];
  /** Whether a message is queued behind the current response */
  isQueued?: boolean;
  queuedMessageText?: string | null;
  /** Cancel a queued message */
  onCancelQueue?: () => void;
  /** Recall a queued message into the editor for changes */
  onEditQueue?: () => { text: string; files?: PendingFile[] } | null | void;
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
  planMode?: "chat" | "planning" | "executing" | "blocked" | "done" | null;
  hasPlan?: boolean;
  planBusy?: boolean;
  canTogglePlanMode?: boolean;
  planModeControl?: PlanModeControlVisibility | null;
  onTogglePlanMode?: () => void;
  onApprovePlan?: () => void;
  /** Hide the inline model-override pill. Used for non-harness scratch
   *  surfaces that intentionally suppress channel-level overrides. */
  hideModelOverride?: boolean;
  /** Cumulative cost (USD) for the current harness session, computed by
   *  the caller from per-message metadata. Renders as a small pill in the
   *  composer's status row when present. */
  harnessCostTotal?: number | null;
  /** When set, the composer is hosting a harness bot. The model pill swaps
   *  to show the harness session's per-session model and opens a picker
   *  that writes through to ``POST /sessions/{id}/harness-settings``
   *  instead of the channel model_override path. */
  harnessRuntime?: string | null;
  /** Curated list of harness model ids to show in the picker. Comes from
   *  the runtime adapter via ``GET /runtimes/{name}/capabilities``. */
  harnessAvailableModels?: string[];
  harnessEffortValues?: string[];
  /** Current per-session harness model (or null = runtime default). */
  harnessCurrentModel?: string | null;
  harnessCurrentEffort?: string | null;
  /** Current per-session harness approval mode. Rendered in the composer
   *  footer so it stays visually tied to the harness state/action surface. */
  harnessApprovalMode?: HarnessApprovalMode | string | null;
  /** Persist the user's pick to ``harness_settings.model``. ``null`` clears. */
  onHarnessModelChange?: (model: string | null) => void;
  onHarnessEffortChange?: (effort: string | null) => void;
  onHarnessApprovalModeCycle?: () => void;
  /** Whether harness-side model writes are in flight (disables the picker). */
  harnessModelMutating?: boolean;
  harnessApprovalModeMutating?: boolean;
}

/** Short non-blocking haptic buzz. No-op on iOS Safari (vibrate is
 *  gated behind a user gesture and unsupported there) and on desktop. */
function tapHaptic(pattern: number | number[] = 8) {
  try { (navigator as Navigator & { vibrate?: (p: number | number[]) => boolean }).vibrate?.(pattern); } catch { /* ignore */ }
}

export function MessageInput({ onSend, onSendAudio, disabled, sendDisabledReason = null, isStreaming, onCancel, modelOverride, modelProviderIdOverride, onModelOverrideChange, defaultModel, currentBotId, isMultiBot, channelId, toolContextChannelId, onSlashCommand, slashSurface = "channel", availableSlashCommands, isQueued, queuedMessageText, onCancelQueue, onEditQueue, onSendNow, configOverhead, onConfigOverheadClick, compact: compactLayout = false, chatMode = "default", planMode = null, hasPlan = false, planBusy = false, canTogglePlanMode = false, planModeControl = "auto", onTogglePlanMode, onApprovePlan, hideModelOverride = false, harnessCostTotal = null, harnessRuntime = null, harnessAvailableModels, harnessEffortValues = [], harnessCurrentModel = null, harnessCurrentEffort = null, harnessApprovalMode = null, onHarnessModelChange, onHarnessEffortChange, onHarnessApprovalModeCycle, harnessModelMutating = false, harnessApprovalModeMutating = false }: Props) {
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const t = useThemeTokens();
  const recorder = useAudioRecorder();
  // Phase 4: scope slash catalog by bot id so harness sessions get the
  // runtime-allowlisted set automatically (picker + /help share one source).
  const slashCatalog = useSlashCommandList(currentBotId);
  const toolChannelId = toolContextChannelId ?? channelId;

  const {
    text,
    setText,
    pendingFiles,
    setPendingFiles,
    clear: clearDraftState,
    handleFileSelect,
    removeFile,
    handleImagePaste,
  } = useComposerDraftFiles(channelId);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [showPlanMenu, setShowPlanMenu] = useState(false);
  const editorRef = useRef<TiptapChatInputHandle>(null);
  const editorWrapperRef = useRef<HTMLDivElement>(null);
  const dragCounterRef = useRef(0);
  const [isFocused, setIsFocused] = useState(false);
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const collapsed = false;
  const attachmentBlockReason = pendingFiles.some((pf) => pf.status === "uploading")
    ? "File upload is still running"
    : pendingFiles.some((pf) => pf.status === "error")
      ? "Remove failed uploads before sending"
      : pendingFiles.some((pf) => pf.status === "rejected")
        ? "Remove files that are too large before sending"
        : null;
  const effectiveSendDisabledReason = sendDisabledReason ?? attachmentBlockReason;

  const resolveCurrentSubmitIntent = useCallback(() => resolveComposerSubmitIntent({
    rawMessage: editorRef.current?.getMarkdown() ?? text,
    pendingFiles,
    disabled,
    sendDisabledReason: effectiveSendDisabledReason,
    slashSurface,
    slashCatalog,
    availableSlashCommands,
  }), [
    text,
    pendingFiles,
    disabled,
    effectiveSendDisabledReason,
    slashSurface,
    slashCatalog,
    availableSlashCommands,
  ]);

  const applySubmitIntent = useCallback((
    intent: ComposerSubmitIntent<PendingFile>,
    sendMessage: (message: string, files?: PendingFile[]) => void,
    hapticPattern: number | number[],
  ) => {
    if (intent.kind === "idle") return;
    if (intent.kind === "blocked") {
      toast({ kind: "info", message: intent.reason });
      editorRef.current?.focus();
      return;
    }
    if (intent.kind === "slash") {
      onSlashCommand?.(intent.id, intent.args, intent.argsText);
      clearDraftState();
      editorRef.current?.clear();
      editorRef.current?.focus();
      return;
    }
    if (intent.kind === "missing_slash_args") {
      toast({
        kind: "info",
        message: `/${intent.id} needs: ${intent.missing.join(", ")}`,
      });
      editorRef.current?.focus();
      return;
    }

    tapHaptic(hapticPattern);
    sendMessage(intent.message, intent.files);
    clearDraftState({ preserveFilePreviews: true });
    editorRef.current?.clear();
    editorRef.current?.focus();
  }, [
    onSlashCommand,
    clearDraftState,
  ]);

  const handleSend = useCallback(() => {
    applySubmitIntent(resolveCurrentSubmitIntent(), onSend, 8);
  }, [applySubmitIntent, onSend, resolveCurrentSubmitIntent]);

  const handleRecallQueued = useCallback(() => {
    const recalled = onEditQueue?.();
    if (!recalled) return false;
    setText(recalled.text);
    editorRef.current?.setMarkdown(recalled.text);
    setPendingFiles(recalled.files ?? []);
    editorRef.current?.focus();
    return true;
  }, [onEditQueue, setText, setPendingFiles]);

  const handleEscapeEmpty = useCallback(() => {
    if (showModelPicker || showPlanMenu) {
      setShowModelPicker(false);
      setShowPlanMenu(false);
      return true;
    }
    if (isQueued) {
      onCancelQueue?.();
      return true;
    }
    if (pendingFiles.length > 0) {
      setPendingFiles([]);
      return true;
    }
    if (isStreaming) {
      onCancel?.();
      return true;
    }
    return false;
  }, [showModelPicker, showPlanMenu, isQueued, onCancelQueue, pendingFiles.length, setPendingFiles, isStreaming, onCancel]);

  // --- Audio recording ---
  const handleMicToggle = useCallback(async () => {
    if (recorder.isRecording) {
      const result = await recorder.stopRecording();
      if (result && onSendAudio) {
        onSendAudio(result.base64, result.format, text.trim() || undefined);
        clearDraftState();
        editorRef.current?.clear();
        editorRef.current?.focus();
      }
    } else {
      await recorder.startRecording();
    }
  }, [recorder.isRecording, recorder.stopRecording, recorder.startRecording, onSendAudio, text, clearDraftState]);

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

  useEffect(() => {
    const handlePlanFill = (event: Event) => {
      const detail = (event as CustomEvent<{ text?: string }>).detail;
      const incoming = (detail?.text ?? "").trim();
      if (!incoming) return;
      const current = (editorRef.current?.getMarkdown() ?? text).trim();
      const next = current ? `${current}\n\n${incoming}` : incoming;
      setText(next);
      editorRef.current?.focus();
    };
    window.addEventListener("spindrel:plan-question-fill", handlePlanFill as EventListener);
    return () => window.removeEventListener("spindrel:plan-question-fill", handlePlanFill as EventListener);
  }, [setText, text]);

  const hasContent = !!(text.trim() || pendingFiles.length > 0);
  const sendBlocked = !!effectiveSendDisabledReason;
  const canAttemptSend = hasContent && !disabled;
  const canSend = canAttemptSend && !sendBlocked;
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
  const isHarness = !!harnessRuntime;
  const terminalHint = text.trim().startsWith("/") ? "command" : "message";
  const terminalPlaceholder = compactLayout
    ? "Type / or enter a message..."
    : "Type / for commands or enter a message...";
  // Plan mode and harness permission mode are separate controls: plan mode
  // mirrors/initiates the runtime's native planning state, while the harness
  // footer text controls approval/sandbox posture.
  const canShowPlanControl = !!onTogglePlanMode && shouldShowComposerPlanControl({
    canTogglePlanMode,
    planMode,
    planModeControl,
    harnessRuntime,
  });
  const controlPresentation = isTerminalMode ? "terminal" : "default";
  const approvalModeControl = isHarness ? (
    <ComposerApprovalModeControl
      presentation={controlPresentation}
      mode={harnessApprovalMode}
      disabled={disabled}
      mutating={harnessApprovalModeMutating}
      onCycle={onHarnessApprovalModeCycle}
      terminalFontStack={TERMINAL_FONT_STACK}
    />
  ) : null;
  const planControl = (
    <ComposerPlanControl
      enabled={canShowPlanControl}
      presentation={controlPresentation}
      open={showPlanMenu}
      onOpenChange={setShowPlanMenu}
      planMode={planMode}
      hasPlan={hasPlan}
      modeSwitch={isHarness}
      disabled={disabled}
      planBusy={planBusy}
      onTogglePlanMode={onTogglePlanMode}
      onApprovePlan={onApprovePlan}
      terminalBorder={terminalBorder}
      terminalFontStack={TERMINAL_FONT_STACK}
    />
  );

  // "Send now" — cancel stream and send immediately (web only)
  const handleSendNowLocal = useCallback(() => {
    applySubmitIntent(
      resolveCurrentSubmitIntent(),
      (message, files) => onSendNow?.(message, files),
      [4, 30, 8],
    );
  }, [applySubmitIntent, onSendNow, resolveCurrentSubmitIntent]);

  const handleComposerDragEnter = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer?.types?.includes("Files")) return;
    event.preventDefault();
    dragCounterRef.current += 1;
    setIsDraggingFiles(true);
  }, []);

  const handleComposerDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer?.types?.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  const handleComposerDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer?.types?.includes("Files")) return;
    event.preventDefault();
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
    if (dragCounterRef.current === 0) setIsDraggingFiles(false);
  }, []);

  const handleComposerDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer?.types?.includes("Files")) return;
    event.preventDefault();
    dragCounterRef.current = 0;
    setIsDraggingFiles(false);
    handleFileSelect(event.dataTransfer.files);
  }, [handleFileSelect]);

  const sendIconColor = showStop || recorder.isRecording
      ? t.danger
      : canSend
        ? t.accent
        : t.textDim;
    const sendBtnOpacity = canAttemptSend || showStop || showMic || recorder.isRecording ? 1 : 0.4;
    const pendingAttachmentBorder = isTerminalMode ? terminalBorder : t.overlayBorder;
    const pendingAttachmentShell = isTerminalMode
      ? {
          background: "transparent",
          borderRadius: 3,
          fontFamily: TERMINAL_FONT_STACK,
        }
      : {
          background: `${t.surfaceRaised}d9`,
          borderRadius: 8,
        };

    return (
      <div style={{ flexShrink: 0, marginTop: isTerminalMode ? 10 : 0 }}>
        {/* Audio recorder error */}
        {recorder.error && (
          <div role="alert" style={{ padding: "4px 20px", background: t.dangerSubtle }}>
            <span style={{ color: t.danger, fontSize: 12 }}>{recorder.error}</span>
          </div>
        )}
        {/* Pending file previews */}
        {pendingFiles.length > 0 && (
          <div
            style={{
              display: "flex", flexDirection: "row",
              gap: isTerminalMode ? 6 : 8,
              padding: isTerminalMode ? "4px 0 8px" : "0 20px 8px",
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            {pendingFiles.map((pf, i) => {
              const blocked = pf.status === "error" || pf.status === "rejected";
              const uploading = pf.status === "uploading";
              const uploaded = pf.status === "uploaded";
              const isImage = pf.file.type.startsWith("image/");
              const routeText = pf.route === "inline_image" ? "agent image" : "channel data";
              const statusText = blocked
                ? (pf.error || pf.reason || "Could not add file")
                : uploading
                  ? "uploading"
                  : uploaded && pf.upload?.path
                    ? pf.upload.path
                    : `${routeText} · ${formatFileSize(pf.file.size)}`;
              const statusIcon = uploading
                ? <Loader2 size={11} className="animate-spin" />
                : uploaded
                  ? <UploadCloud size={11} />
                  : blocked
                    ? <AlertCircle size={11} />
                    : null;
              return (
                <div
                  key={pf.id}
                  data-testid="chat-attachment-pending"
                  data-attachment-route={pf.route}
                  data-attachment-status={pf.status}
                  data-attachment-name={pf.file.name}
                  style={{
                    position: "relative",
                    display: "flex",
                    flexDirection: "row",
                    alignItems: "center",
                    gap: isTerminalMode ? 8 : 9,
                    width: isTerminalMode ? 260 : 236,
                    minWidth: 0,
                    minHeight: isTerminalMode ? 44 : 52,
                    padding: isTerminalMode ? "4px 26px 4px 4px" : "5px 28px 5px 5px",
                    overflow: "hidden",
                    border: `1px solid ${blocked ? t.danger : pendingAttachmentBorder}`,
                    background: pendingAttachmentShell.background,
                    borderRadius: pendingAttachmentShell.borderRadius,
                    fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
                  }}
                >
                  {pf.preview ? (
                    <img
                      src={pf.preview}
                      alt={pf.file.name}
                      style={{
                        width: isTerminalMode ? 34 : 42,
                        height: isTerminalMode ? 34 : 42,
                        objectFit: "cover",
                        display: "block",
                        borderRadius: isTerminalMode ? 2 : 6,
                        flexShrink: 0,
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        width: isTerminalMode ? 34 : 42,
                        height: isTerminalMode ? 34 : 42,
                        display: "flex", flexDirection: "row",
                        alignItems: "center",
                        justifyContent: "center",
                        background: isTerminalMode ? "transparent" : `${t.overlayLight}55`,
                        color: t.textMuted,
                        border: isTerminalMode ? `1px solid ${terminalBorder}` : `1px solid ${t.overlayBorder}`,
                        borderRadius: isTerminalMode ? 2 : 6,
                        flexShrink: 0,
                      }}
                    >
                      {isImage ? <ImageIcon size={17} /> : <FileText size={17} />}
                    </div>
                  )}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div
                      title={pf.file.name}
                      style={{
                        fontSize: isTerminalMode ? 11 : 12,
                        color: t.text,
                        lineHeight: isTerminalMode ? "15px" : "16px",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {pf.file.name}
                    </div>
                    <div
                      title={statusText}
                      style={{
                        display: "flex",
                        flexDirection: "row",
                        alignItems: "center",
                        gap: 5,
                        marginTop: 1,
                        fontSize: isTerminalMode ? 10 : 10.5,
                        color: blocked ? t.danger : uploaded ? t.textMuted : t.textDim,
                        lineHeight: "14px",
                        minWidth: 0,
                      }}
                    >
                      {statusIcon}
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {statusText}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => removeFile(i)}
                    style={{
                      position: "absolute",
                      top: isTerminalMode ? 5 : 4,
                      right: isTerminalMode ? 5 : 4,
                      width: 18,
                      height: 18,
                      borderRadius: isTerminalMode ? 3 : 9,
                      background: isTerminalMode ? "transparent" : `${t.surface}cc`,
                      border: isTerminalMode ? `1px solid ${terminalBorder}` : `1px solid ${t.overlayBorder}`,
                      display: "flex", flexDirection: "row",
                      alignItems: "center",
                      justifyContent: "center",
                      cursor: "pointer",
                      padding: 0,
                    }}
                  >
                    <X size={10} color={t.textMuted} />
                  </button>
                </div>
              );
            })}
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
                  <span>{queuedMessageText ? `Queued: ${queuedMessageText.slice(0, 72)}${queuedMessageText.length > 72 ? "..." : ""}` : "Message queued"}</span>
                </span>
                <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
                  <button
                    onClick={handleRecallQueued}
                    style={{
                      background: "none",
                      border: "none",
                      color: t.accent,
                      fontSize: 12,
                      cursor: "pointer",
                      padding: "2px 6px",
                      borderRadius: 4,
                    }}
                  >
                    Edit
                  </button>
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
                </span>
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
              : (compactLayout ? "0 10px 10px" : isMobile ? "0 4px 8px" : "0 16px 14px"),
          }}
        >
          {/* One card. Editor on top (flat — no inner border/bg), actions on bottom.
              The mobile radius is slightly tighter so the composer reads less like
              a floating CTA while preserving the desktop overlay treatment. */}
          <div
            ref={editorWrapperRef}
            data-testid="chat-composer-drop-zone"
            onDragEnter={handleComposerDragEnter}
            onDragOver={handleComposerDragOver}
            onDragLeave={handleComposerDragLeave}
            onDrop={handleComposerDrop}
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
              background: isTerminalMode ? t.overlayLight : `${t.surfaceRaised}d9`,
              backdropFilter: isTerminalMode ? undefined : "blur(14px)",
              WebkitBackdropFilter: isTerminalMode ? undefined : "blur(14px)",
              borderRadius: isTerminalMode ? 0 : compactLayout ? 14 : isMobile ? 16 : 20,
              border: isTerminalMode ? "none" : undefined,
              boxShadow: isTerminalMode
                ? "none"
                : isFocused
                  ? `inset 0 0 0 1px ${t.accentBorder}, inset 0 1px 0 ${t.overlayLight}, 0 0 0 3px ${t.accent}1a, 0 6px 24px -8px rgba(0,0,0,0.45), 0 2px 6px -2px rgba(0,0,0,0.3)`
                  : `inset 0 1px 0 ${t.overlayLight}, 0 6px 24px -8px rgba(0,0,0,0.45), 0 2px 6px -2px rgba(0,0,0,0.3)`,
              overflow: "hidden",
              transition: "box-shadow 0.15s, border-color 0.15s",
              position: "relative",
            }}
          >
            {isDraggingFiles && (
              <div
                data-testid="chat-composer-drop-overlay"
                style={{
                  position: "absolute",
                  inset: 0,
                  zIndex: 2,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: `${t.surfaceRaised}ee`,
                  color: t.accent,
                  fontSize: 12,
                  fontWeight: 600,
                  pointerEvents: "none",
                }}
              >
                Drop files to add
              </div>
            )}
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
                  onEscapeDraft={() => {
                    if (pendingFiles.length > 0) setPendingFiles([]);
                  }}
                  onEscapeEmpty={handleEscapeEmpty}
                  onArrowUpEmpty={handleRecallQueued}
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
                padding: isTerminalMode ? "2px 8px 4px" : compactLayout ? "3px 6px 4px" : isMobile ? "2px 6px 6px" : "4px 8px 6px",
                cursor: "text",
                borderTop: isTerminalMode ? undefined : undefined,
                backgroundColor: isTerminalMode ? "transparent" : undefined,
              }}
            >
              {addMenuVisible ? (
                <ComposerAddMenu
                  channelId={toolChannelId}
                  botId={currentBotId}
                  composerText={text}
                  onInsertSkillTag={(skillId) => {
                    editorRef.current?.insertMention(`skill:${skillId}`);
                  }}
                  onInsertToolTag={(toolName) => {
                    editorRef.current?.insertMention(`tool:${toolName}`);
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

              {/* Harness cost pill — desktop only. Replaces the configOverhead bar
                  for harness bots; shows cumulative session cost so far.
                  The number is what the SDK reports as if usage were billed
                  per-token. If the host CLI is signed in via a Claude
                  subscription (Pro/Max), nothing is actually charged — the
                  tilde and tooltip flag this. */}
              {!isTerminalMode && !isMobile && hideModelOverride && harnessCostTotal != null && harnessCostTotal > 0 && (
                <div
                  title={`SDK-reported usage cost (~$${harnessCostTotal.toFixed(4)}). If this host's CLI is signed in via a Claude subscription, this amount is NOT billed — your subscription covers it.`}
                  className="rounded bg-surface-overlay/40 px-1.5 py-0.5 font-mono text-[10px] text-text-dim"
                  style={{ flexShrink: 0, lineHeight: "16px" }}
                >
                  ~${harnessCostTotal.toFixed(harnessCostTotal < 0.01 ? 4 : 2)}
                </div>
              )}

              {/* Config overhead indicator — desktop only. Tucks before the model pill.
                  Hidden for harness bots: their context divisor is the harness model,
                  not bot.model, so the % is meaningless. */}
              {!isTerminalMode && !isMobile && !hideModelOverride && configOverhead != null && configOverhead >= 0.2 && (
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

              {!isTerminalMode && approvalModeControl}
              {!isTerminalMode && planControl}

              {!isTerminalMode && (
                <ComposerModelControl
                  presentation="default"
                  open={showModelPicker}
                  onOpenChange={setShowModelPicker}
                  channelId={channelId}
                  isMobile={isMobile}
                  hideModelOverride={hideModelOverride}
                  modelOverride={modelOverride}
                  modelProviderIdOverride={modelProviderIdOverride}
                  onModelOverrideChange={onModelOverrideChange}
                  defaultModel={defaultModel}
                  harnessRuntime={harnessRuntime}
                  harnessAvailableModels={harnessAvailableModels}
                  harnessEffortValues={harnessEffortValues}
                  harnessCurrentModel={harnessCurrentModel}
                  harnessCurrentEffort={harnessCurrentEffort}
                  harnessModelMutating={harnessModelMutating}
                  onHarnessModelChange={onHarnessModelChange}
                  onHarnessEffortChange={onHarnessEffortChange}
                  terminalFontStack={TERMINAL_FONT_STACK}
                />
              )}

              {/* Send / Stop / Mic button */}
              <button
                data-testid="chat-composer-send"
                data-audio-state={recorder.isRecording ? "recording" : showMic ? "idle" : "off"}
                aria-label={
                  showStop ? "Stop response"
                  : recorder.isRecording ? "Send recording"
                  : showMic ? "Record audio"
                  : "Send message"
                }
                title={
                  showStop ? "Stop response"
                  : recorder.isRecording ? "Send recording"
                  : showMic ? "Record audio"
                  : "Send message"
                }
                className="send-btn"
                onClick={
                  (showStop && stopArmed) ? () => { tapHaptic(12); onCancel?.(); }
                  : recorder.isRecording ? handleMicToggle
                  : showMic ? handleMicToggle
                  : showStop ? undefined
                  : handleSend
                }
                disabled={!canAttemptSend && !(showStop && stopArmed) && !showMic && !recorder.isRecording}
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 36,
                  height: 36,
                  flexShrink: 0,
                  borderRadius: isTerminalMode ? 0 : 8,
                  border: isTerminalMode ? "none" : "none",
                  padding: 0,
                  cursor: (!canAttemptSend && !(showStop && stopArmed) && !showMic && !recorder.isRecording) ? "default" : "pointer",
                  backgroundColor: "transparent",
                  opacity: (showStop && !stopArmed) ? 0.4 : sendBtnOpacity,
                  transition: "background-color 0.15s, opacity 0.15s, border-color 0.15s",
                }}
              >
                {showStop ? (
                  <Square size={14} color={sendIconColor} fill={sendIconColor} />
                ) : recorder.isRecording ? (
                  <Send size={isMobile ? 14 : 16} color={sendIconColor} />
                ) : showMic ? (
                  <Mic size={isMobile ? 14 : 16} color={t.textDim} />
                ) : (
                  <Send size={isMobile ? 14 : 16} color={sendIconColor} />
                )}
              </button>
            </div>
          </div>
          {isTerminalMode && (isHarness || onModelOverrideChange) && (
            <div
              style={{
                padding: "8px 0 0 8px",
                display: "flex",
                flexDirection: "row",
                justifyContent: "space-between",
                alignItems: "center",
                minHeight: 14,
                minWidth: 0,
                gap: 12,
              }}
            >
              <ComposerModelControl
                presentation="terminal"
                open={showModelPicker}
                onOpenChange={setShowModelPicker}
                channelId={channelId}
                isMobile={isMobile}
                hideModelOverride={hideModelOverride}
                modelOverride={modelOverride}
                modelProviderIdOverride={modelProviderIdOverride}
                onModelOverrideChange={onModelOverrideChange}
                defaultModel={defaultModel}
                harnessRuntime={harnessRuntime}
                harnessAvailableModels={harnessAvailableModels}
                harnessEffortValues={harnessEffortValues}
                harnessCurrentModel={harnessCurrentModel}
                harnessCurrentEffort={harnessCurrentEffort}
                harnessModelMutating={harnessModelMutating}
                onHarnessModelChange={onHarnessModelChange}
                onHarnessEffortChange={onHarnessEffortChange}
                terminalFontStack={TERMINAL_FONT_STACK}
              />
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
                {approvalModeControl}
                {planControl}
              </div>
            </div>
          )}
        </div>
      </div>
    );
}
