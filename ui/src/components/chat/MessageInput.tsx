import { useState, useRef, useCallback, useEffect } from "react";
import { Send, Square, X, Mic, Check, ListTodo, ChevronDown } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useAudioRecorder } from "../../hooks/useAudioRecorder";
import { RecordingOverlay } from "./RecordingOverlay";
import { useThemeTokens } from "../../theme/tokens";
import { TiptapChatInput, type TiptapChatInputHandle } from "./TiptapChatInput";
import { toast } from "../../stores/toast";
import { useSlashCommandList } from "@/src/api/hooks/useSlashCommands";
import { createPortal } from "react-dom";
import { LlmModelDropdownContent } from "../shared/LlmModelDropdown";
import { ComposerAddMenu } from "./ComposerAddMenu";
import { resolveComposerSubmitIntent, type ComposerSubmitIntent } from "./composerSubmit";
import { getComposerPlanControlState, type ComposerPlanTone } from "./planControl";
import {
  getHarnessApprovalModeControlState,
  type HarnessApprovalMode,
  type HarnessApprovalModeTone,
} from "./harnessApprovalModeControl";
import { useComposerDraftFiles, type PendingFile } from "./useComposerDraftFiles";
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
  /** Channel ID for persisting drafts across navigation */
  channelId?: string;
  /** Handler for slash commands typed in the input */
  onSlashCommand?: (id: string, args?: string[]) => void;
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

export function MessageInput({ onSend, onSendAudio, disabled, sendDisabledReason = null, isStreaming, onCancel, modelOverride, modelProviderIdOverride, onModelOverrideChange, defaultModel, currentBotId, isMultiBot, channelId, onSlashCommand, slashSurface = "channel", availableSlashCommands, isQueued, queuedMessageText, onCancelQueue, onEditQueue, onSendNow, configOverhead, onConfigOverheadClick, compact: compactLayout = false, chatMode = "default", planMode = null, hasPlan = false, planBusy = false, canTogglePlanMode = false, onTogglePlanMode, onApprovePlan, hideModelOverride = false, harnessCostTotal = null, harnessRuntime = null, harnessAvailableModels, harnessEffortValues = [], harnessCurrentModel = null, harnessCurrentEffort = null, harnessApprovalMode = null, onHarnessModelChange, onHarnessEffortChange, onHarnessApprovalModeCycle, harnessModelMutating = false, harnessApprovalModeMutating = false }: Props) {
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const t = useThemeTokens();
  const recorder = useAudioRecorder();
  // Phase 4: scope slash catalog by bot id so harness sessions get the
  // runtime-allowlisted set automatically (picker + /help share one source).
  const slashCatalog = useSlashCommandList(currentBotId);

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
  // External openers (typed `/model` with no args, header pill mirror, etc.)
  // can request the picker open via a custom event scoped to this channel.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ channelId?: string }>).detail;
      if (!detail?.channelId || detail.channelId === channelId) {
        setShowModelPicker(true);
      }
    };
    window.addEventListener("spindrel:open-model-picker", handler);
    return () => window.removeEventListener("spindrel:open-model-picker", handler);
  }, [channelId]);
  const [showPlanMenu, setShowPlanMenu] = useState(false);
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const planControlRef = useRef<HTMLDivElement>(null);
  const planMenuRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<TiptapChatInputHandle>(null);
  const editorWrapperRef = useRef<HTMLDivElement>(null);
  const [isFocused, setIsFocused] = useState(false);
  const collapsed = false;

  const resolveCurrentSubmitIntent = useCallback(() => resolveComposerSubmitIntent({
    rawMessage: editorRef.current?.getMarkdown() ?? text,
    pendingFiles,
    disabled,
    sendDisabledReason,
    slashSurface,
    slashCatalog,
    availableSlashCommands,
  }), [
    text,
    pendingFiles,
    disabled,
    sendDisabledReason,
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
      onSlashCommand?.(intent.id, intent.args);
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
    clearDraftState();
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
  const sendBlocked = !!sendDisabledReason;
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
  // Harness pill is always visible (header pill is canonical, but the
  // composer pill is the muscle-memory surface for typed `/model` users).
  // Non-harness pill respects the existing hideModelOverride opt-out.
  const modelPillVisible = isHarness
    ? !isTerminalMode
    : (onModelOverrideChange && !isTerminalMode && !hideModelOverride);
  const terminalHint = text.trim().startsWith("/") ? "command" : "message";
  const hasOverride = isHarness ? !!harnessCurrentModel : !!modelOverride;
  // Harness channels run a separate runtime; the bot's LLM `model` field
  // (gpt-4o, gemma, etc) is irrelevant to a Codex/Claude Code session, so
  // never leak it into the harness footer. When the user hasn't picked a
  // harness model the runtime picks its own default — show "default" rather
  // than the bot's unrelated provider model.
  const effectiveName = isHarness
    ? harnessCurrentModel
    : (modelOverride
        ? modelOverride.split("/").pop()
        : defaultModel?.split("/").pop());
  const canRenderModelLabel = !!effectiveName;
  const cycleHarnessEffort = useCallback(() => {
    if (!onHarnessEffortChange || harnessModelMutating) return;
    const cycle = [...harnessEffortValues, null];
    if (cycle.length === 1) return;
    const idx = harnessCurrentEffort ? harnessEffortValues.indexOf(harnessCurrentEffort) : harnessEffortValues.length;
    onHarnessEffortChange(cycle[(idx + 1) % cycle.length]);
  }, [harnessCurrentEffort, harnessEffortValues, harnessModelMutating, onHarnessEffortChange]);
  const terminalPlaceholder = compactLayout
    ? "Type / or enter a message..."
    : "Type / for commands or enter a message...";
  // Non-harness sessions use the composer plan action. Harness sessions use
  // the approval-mode footer text as the single mode control.
  const canShowPlanControl = !isHarness && canTogglePlanMode && !!onTogglePlanMode;
  const planControlState = getComposerPlanControlState({
    planMode,
    hasPlan,
    canApprovePlan: !!onApprovePlan && planMode === "planning",
  });
  const planColors = planToneColors(t, planControlState.tone);
  const approvalModeControlState = getHarnessApprovalModeControlState(harnessApprovalMode);
  const approvalModeColors = harnessApprovalModeToneColors(t, approvalModeControlState.tone);
  const approvalModeControl = isHarness && onHarnessApprovalModeCycle ? (
    <button
      type="button"
      onMouseDown={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onHarnessApprovalModeCycle();
      }}
      disabled={disabled || harnessApprovalModeMutating}
      title={approvalModeControlState.title}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: isTerminalMode ? 22 : 24,
        padding: isTerminalMode ? "0 2px" : "4px 4px",
        border: "none",
        borderRadius: 0,
        background: "transparent",
        color: approvalModeColors.text,
        cursor: disabled || harnessApprovalModeMutating ? "default" : "pointer",
        fontSize: isTerminalMode ? 11.5 : 11,
        lineHeight: 1.2,
        whiteSpace: "nowrap",
        fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
        fontWeight: isTerminalMode ? 500 : 600,
        textTransform: "lowercase",
        opacity: disabled || harnessApprovalModeMutating ? 0.55 : 1,
        flexShrink: 0,
      }}
    >
      {approvalModeControlState.label}
    </button>
  ) : null;

  useEffect(() => {
    if (!showPlanMenu || !planControlState.showMenu) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      const clickedTrigger = !!(planControlRef.current && target && planControlRef.current.contains(target));
      const clickedMenu = !!(planMenuRef.current && target && planMenuRef.current.contains(target));
      if (!clickedTrigger && !clickedMenu) {
        setShowPlanMenu(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [planControlState.showMenu, showPlanMenu]);

  const planControl = canShowPlanControl ? (
    <div ref={planControlRef} style={{ position: "relative", display: "flex", alignItems: "center", flexShrink: 0 }}>
      <button
        type="button"
        onMouseDown={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (planControlState.showMenu) {
            setShowPlanMenu((open) => !open);
          } else {
            setShowPlanMenu(false);
            onTogglePlanMode?.();
          }
        }}
        disabled={disabled || planBusy}
        title={planControlState.title}
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          minHeight: isTerminalMode ? 22 : 24,
          padding: isTerminalMode ? "0 0 0 2px" : "4px 8px",
          border: isTerminalMode ? "none" : `1px solid ${planColors.border}`,
          borderRadius: isTerminalMode ? 0 : 8,
          background: isTerminalMode ? "transparent" : planColors.background,
          color: planColors.text,
          cursor: disabled || planBusy ? "default" : "pointer",
          fontSize: 11,
          lineHeight: 1.2,
          whiteSpace: "nowrap",
          fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
          opacity: disabled || planBusy ? 0.55 : 1,
          flexShrink: 0,
        }}
      >
        <ListTodo size={isTerminalMode ? 13 : 14} color={planColors.icon} />
        <span>{planControlState.label}</span>
        {planControlState.showMenu && <ChevronDown size={12} color={planColors.icon} />}
      </button>
      {showPlanMenu && planControlState.showMenu && (() => {
        const rect = planControlRef.current?.getBoundingClientRect();
        const dropdownWidth = 168;
        const dropdownLeft = isTerminalMode
          ? Math.max(12, (rect?.right ?? window.innerWidth - 16) - dropdownWidth)
          : Math.max(12, Math.min(rect?.left ?? 16, window.innerWidth - dropdownWidth - 12));
        const dropdownBottom = rect ? window.innerHeight - rect.top + 8 : 80;
        return createPortal(
          <>
            <div
              onClick={() => setShowPlanMenu(false)}
              style={{ position: "fixed", inset: 0, zIndex: 50000 }}
            />
            <div
              ref={planMenuRef}
              style={{
                position: "fixed",
                bottom: dropdownBottom,
                left: dropdownLeft,
                width: isTerminalMode ? 136 : 156,
                background: isTerminalMode ? t.overlayLight : t.surfaceRaised,
                border: isTerminalMode ? `1px solid ${terminalBorder}` : `1px solid ${t.surfaceBorder}`,
                borderRadius: isTerminalMode ? 6 : 10,
                boxShadow: isTerminalMode ? "none" : "0 10px 24px rgba(0,0,0,0.14)",
                padding: isTerminalMode ? 2 : 4,
                zIndex: 50001,
              }}
            >
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                }}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setShowPlanMenu(false);
                  onTogglePlanMode?.();
                }}
                style={menuItemStyle(t, isTerminalMode)}
              >
                {planControlState.primaryActionLabel}
              </button>
              {planControlState.canApprove && onApprovePlan && (
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                  }}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setShowPlanMenu(false);
                    onApprovePlan();
                  }}
                  style={menuItemStyle(t, isTerminalMode)}
                >
                  Approve plan
                </button>
              )}
            </div>
          </>,
          document.body
        );
      })()}
    </div>
  ) : null;

  // "Send now" — cancel stream and send immediately (web only)
  const handleSendNowLocal = useCallback(() => {
    applySubmitIntent(
      resolveCurrentSubmitIntent(),
      (message, files) => onSendNow?.(message, files),
      [4, 30, 8],
    );
  }, [applySubmitIntent, onSendNow, resolveCurrentSubmitIntent]);

  const sendIconColor = showStop || recorder.isRecording
      ? t.danger
      : canSend
        ? t.accent
        : t.textDim;
    const sendBtnOpacity = canAttemptSend || showStop || showMic || recorder.isRecording ? 1 : 0.4;

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
                  channelId={channelId}
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

              {/* Inline model pill — desktop only. Always visible showing the current
                  effective model; clicking opens the LlmModelDropdown portal. Purple
                  accent only when a channel-level override is set. */}
              {modelPillVisible && (() => {
                // Harness channels always show a pill — runtime picks a default
                // when no explicit selection. Non-harness channels only render
                // when there's a name to show.
                const pillLabel = effectiveName ?? (isHarness ? "default" : null);
                const canRenderPill = !!pillLabel;
                const pillTitle = isHarness
                  ? (hasOverride
                      ? `Harness model: ${harnessCurrentModel}`
                      : "Harness model: runtime default")
                  : (hasOverride
                      ? `Channel model override: ${modelOverride}`
                      : `Model: ${defaultModel ?? effectiveName}`);
                return (
                  <div ref={modelPickerRef} style={{ position: "relative", display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
                    {canRenderPill ? (
                      <button
                        type="button"
                        onClick={() => setShowModelPicker(true)}
                        title={pillTitle}
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
                          {pillLabel}
                        </span>
                        {hasOverride && (
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              if (isHarness) {
                                onHarnessModelChange?.(null);
                              } else {
                                onModelOverrideChange?.(undefined, null);
                              }
                            }}
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
                            {isHarness ? (
                              <HarnessModelPickerContent
                                t={t}
                                models={harnessAvailableModels ?? []}
                                current={harnessCurrentModel ?? null}
                                disabled={harnessModelMutating}
                                onSelect={(m) => {
                                  onHarnessModelChange?.(m);
                                  setShowModelPicker(false);
                                }}
                              />
                            ) : (
                              <>
                                <LlmModelDropdownContent
                                  value={modelOverride ?? ""}
                                  selectedProviderId={modelProviderIdOverride}
                                  onSelect={(m, pid) => {
                                    onModelOverrideChange?.(m || undefined, pid);
                                    setShowModelPicker(false);
                                  }}
                                />
                                {hasOverride && (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      onModelOverrideChange?.(undefined, null);
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
                              </>
                            )}
                          </div>
                        </>,
                        document.body
                      );
                    })()}
                    {isHarness && harnessEffortValues.length > 0 && (
                      <button
                        type="button"
                        onClick={cycleHarnessEffort}
                        disabled={harnessModelMutating}
                        title={harnessCurrentEffort ? `Harness effort: ${harnessCurrentEffort}. Click to cycle.` : "Harness effort: default. Click to set."}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                          background: harnessCurrentEffort ? t.warningSubtle : "transparent",
                          border: `1px solid ${harnessCurrentEffort ? t.warningBorder : "transparent"}`,
                          borderRadius: 8,
                          padding: "4px 8px",
                          fontSize: 11,
                          color: harnessCurrentEffort ? t.warningMuted : t.textMuted,
                          cursor: harnessModelMutating ? "default" : "pointer",
                          opacity: harnessModelMutating ? 0.6 : 1,
                          whiteSpace: "nowrap",
                        }}
                      >
                        effort {harnessCurrentEffort ?? "default"}
                      </button>
                    )}
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
              <div
                ref={modelPickerRef}
                style={{ minWidth: 0, display: "flex", alignItems: "center", flex: 1, gap: 12 }}
              >
                <button
                  type="button"
                  onClick={() => setShowModelPicker(true)}
                  title={isHarness
                    ? (hasOverride ? `Harness model: ${harnessCurrentModel}` : "Harness model: runtime default")
                    : (hasOverride ? `Channel model override: ${modelOverride}` : `Model: ${defaultModel ?? effectiveName ?? "default"}`)}
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
                  {effectiveName ?? (isHarness ? "default" : "select model")}
                </button>
                {isHarness && harnessEffortValues.length > 0 && (
                  <button
                    type="button"
                    onClick={cycleHarnessEffort}
                    disabled={harnessModelMutating}
                    title={harnessCurrentEffort ? `Harness effort: ${harnessCurrentEffort}. Click to cycle.` : "Harness effort: default. Click to set."}
                    style={{
                      background: "transparent",
                      border: "none",
                      padding: 0,
                      margin: 0,
                      color: harnessCurrentEffort ? t.warningMuted : t.textDim,
                      fontFamily: TERMINAL_FONT_STACK,
                      fontSize: 11.5,
                      lineHeight: 1.2,
                      cursor: harnessModelMutating ? "default" : "pointer",
                      whiteSpace: "nowrap",
                    }}
                  >
                    effort {harnessCurrentEffort ?? "default"}
                  </button>
                )}
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
                        {isHarness ? (
                          <HarnessModelPickerContent
                            t={t}
                            models={harnessAvailableModels ?? []}
                            current={harnessCurrentModel ?? null}
                            disabled={harnessModelMutating}
                            onSelect={(m) => {
                              onHarnessModelChange?.(m);
                              setShowModelPicker(false);
                            }}
                          />
                        ) : (
                          <>
                            <LlmModelDropdownContent
                              value={modelOverride ?? ""}
                              selectedProviderId={modelProviderIdOverride}
                              onSelect={(m, pid) => {
                                onModelOverrideChange?.(m || undefined, pid);
                                setShowModelPicker(false);
                              }}
                            />
                            {hasOverride && (
                              <button
                                type="button"
                                onClick={() => {
                                  onModelOverrideChange?.(undefined, null);
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
                          </>
                        )}
                      </div>
                    </>,
                    document.body
                  );
                })()}
              </div>
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

function menuItemStyle(t: ReturnType<typeof useThemeTokens>, isTerminalMode = false) {
  return {
    width: "100%",
    display: "block",
    background: "transparent",
    border: "none",
    borderRadius: isTerminalMode ? 4 : 8,
    padding: isTerminalMode ? "6px 8px" : "8px 10px",
    color: isTerminalMode ? t.textMuted : t.text,
    fontSize: isTerminalMode ? 11 : 12,
    fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
    textAlign: "left" as const,
    cursor: "pointer",
  };
}

function planToneColors(t: ReturnType<typeof useThemeTokens>, tone: ComposerPlanTone) {
  switch (tone) {
    case "warning":
      return {
        border: t.warningBorder,
        background: t.warningSubtle,
        text: t.warningMuted,
        icon: t.warning,
      };
    case "danger":
      return {
        border: t.dangerBorder,
        background: t.dangerSubtle,
        text: t.dangerMuted,
        icon: t.danger,
      };
    case "success":
      return {
        border: t.successBorder,
        background: t.successSubtle,
        text: t.success,
        icon: t.success,
      };
    case "neutral":
    default:
      return {
        border: "transparent",
        background: "transparent",
        text: t.textMuted,
        icon: t.textDim,
      };
  }
}

function harnessApprovalModeToneColors(
  t: ReturnType<typeof useThemeTokens>,
  tone: HarnessApprovalModeTone,
) {
  switch (tone) {
    case "success":
      return { text: t.success };
    case "warning":
      return { text: t.warningMuted };
    case "plan":
      return { text: t.accent };
    case "neutral":
    default:
      return { text: t.textDim };
  }
}

/** Harness model picker — same popover shell as the LLM picker, but the
 *  list comes from the runtime adapter (``GET /runtimes/{name}/capabilities``)
 *  and selection writes to ``harness_settings.model`` rather than
 *  ``channel.model_override``. Selecting "Default" clears the override. */
function HarnessModelPickerContent({
  t,
  models,
  current,
  disabled,
  onSelect,
}: {
  t: ReturnType<typeof useThemeTokens>;
  models: string[];
  current: string | null;
  disabled: boolean;
  onSelect: (model: string | null) => void;
}) {
  return (
    <div
      style={{
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        padding: 6,
        maxHeight: 360,
        overflowY: "auto",
        boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
      }}
    >
      <div
        style={{
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: t.textDim,
          padding: "6px 8px 4px",
        }}
      >
        Harness model
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSelect(null)}
        style={{
          display: "block",
          width: "100%",
          textAlign: "left",
          background: current === null ? t.surfaceOverlay : "transparent",
          color: t.textMuted,
          border: "none",
          borderRadius: 6,
          padding: "8px 10px",
          fontSize: 12,
          cursor: disabled ? "default" : "pointer",
          opacity: disabled ? 0.6 : 1,
        }}
      >
        Default — runtime picks
      </button>
      {models.map((m) => {
        const selected = m === current;
        return (
          <button
            key={m}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(m)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              background: selected ? t.purpleSubtle : "transparent",
              color: selected ? t.purple : t.text,
              border: "none",
              borderRadius: 6,
              padding: "8px 10px",
              fontSize: 12,
              fontFamily: "'Menlo', monospace",
              cursor: disabled ? "default" : "pointer",
              opacity: disabled ? 0.6 : 1,
            }}
          >
            {m}
          </button>
        );
      })}
      {models.length === 0 && (
        <div style={{ padding: "8px 10px", fontSize: 11, color: t.textDim }}>
          No model list reported by the runtime adapter.
        </div>
      )}
    </div>
  );
}
