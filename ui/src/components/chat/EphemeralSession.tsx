import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useBots } from "@/src/api/hooks/useBots";
import { useSubmitChat } from "@/src/api/hooks/useChat";
import { useQueryClient } from "@tanstack/react-query";
import {
  useSpawnEphemeralSession,
  loadEphemeralState,
  saveEphemeralState,
  clearEphemeralState,
  type StoredEphemeralState,
} from "@/src/api/hooks/useEphemeralSession";
import { useSessionConfigOverhead } from "@/src/api/hooks/useSessionConfigOverhead";
import { selectIsStreaming, useChatStore } from "@/src/stores/chat";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { EphemeralSessionModal } from "./EphemeralSessionModal";
import { EphemeralSessionDock } from "./EphemeralSessionDock";
import { SessionChatView } from "./SessionChatView";
import { MessageInput, type PendingFile } from "./MessageInput";
import { useThemeTokens } from "@/src/theme/tokens";
import { Maximize2, Minimize2, RotateCcw, X } from "lucide-react";

export interface EphemeralContextPayload {
  page_name?: string;
  url?: string;
  tags?: string[];
  payload?: Record<string, unknown>;
  tool_hints?: string[];
}

export interface EphemeralSessionProps {
  /** Display mode — the controller renders the appropriate shell. */
  shape: "modal" | "dock";
  /** Controlled open state (caller owns open/close). */
  open: boolean;
  onClose: () => void;
  /** Default bot to pre-select. Sticky via storageKey. */
  defaultBotId?: string;
  /** Optional parent channel for SSE bus routing. Required for streaming. */
  parentChannelId?: string;
  /** Page-level context persisted as the first system message. */
  context?: EphemeralContextPayload;
  /** localStorage key for cross-mount session persistence. Omit to disable. */
  sessionStorageKey?: string;
  /** Displayed in the modal/dock header. */
  title?: string;
  /** Empty-state content shown before the first message is sent. */
  emptyState?: React.ReactNode;
}

/**
 * Generic ephemeral chat controller.
 *
 * Owns: session spawn-on-first-send, bot/model picker state, runtime
 * shape toggle (dock ↔ modal), localStorage persistence, and mounts
 * SessionChatView + MessageInput verbatim — no parallel renderer.
 */
export function EphemeralSession({
  shape,
  open,
  onClose,
  defaultBotId,
  parentChannelId,
  context,
  sessionStorageKey,
  title = "Chat",
  emptyState,
}: EphemeralSessionProps) {
  const t = useThemeTokens();
  const qc = useQueryClient();
  const { data: bots } = useBots();

  const resolvedDefault = defaultBotId ?? bots?.[0]?.id ?? "";

  const [stored, setStored] = useState<StoredEphemeralState | null>(() =>
    sessionStorageKey ? loadEphemeralState(sessionStorageKey) : null,
  );

  const sessionId = stored?.sessionId ?? null;
  const botId = stored?.botId ?? resolvedDefault;
  const modelOverride = stored?.modelOverride ?? undefined;
  const modelProviderId = stored?.modelProviderId ?? null;

  // Runtime shape (defaults to the prop but the expand button toggles it).
  const [mode, setMode] = useState<"dock" | "modal">(shape);
  useEffect(() => {
    setMode(shape);
  }, [shape]);
  // Dock expansion (FAB vs panel). The controller owns it so the header
  // X button can collapse back to the FAB.
  const [dockExpanded, setDockExpanded] = useState(false);

  const persist = useCallback(
    (patch: Partial<StoredEphemeralState>) => {
      setStored((s) => {
        const next: StoredEphemeralState = {
          sessionId: s?.sessionId ?? "",
          botId: s?.botId ?? resolvedDefault,
          modelOverride: s?.modelOverride ?? null,
          modelProviderId: s?.modelProviderId ?? null,
          ...patch,
        };
        if (sessionStorageKey) saveEphemeralState(sessionStorageKey, next);
        return next;
      });
    },
    [resolvedDefault, sessionStorageKey],
  );

  const setBotId = useCallback(
    (id: string) => {
      if (stored?.sessionId) return; // locked once session exists
      persist({ botId: id });
    },
    [persist, stored?.sessionId],
  );

  const setModelOverride = useCallback(
    (m: string | undefined, pid?: string | null) => {
      persist({ modelOverride: m ?? null, modelProviderId: pid ?? null });
    },
    [persist],
  );

  // Seed the default bot into state (without yet creating a session).
  useEffect(() => {
    if (!stored?.botId && resolvedDefault) {
      persist({ botId: resolvedDefault });
    }
  }, [resolvedDefault, stored?.botId, persist]);

  const spawn = useSpawnEphemeralSession();
  const submitChat = useSubmitChat();
  const [sendError, setSendError] = useState<string | null>(null);
  const chatState = useChatStore((s) =>
    sessionId ? s.getChannel(sessionId) : null,
  );
  const turnActive = chatState ? selectIsStreaming(chatState) : false;
  const isSending = submitChat.isPending || turnActive;

  const { data: overheadData } = useSessionConfigOverhead(sessionId ?? undefined);
  const overheadPct = overheadData?.overhead_pct ?? null;

  const handleSend = useCallback(
    async (message: string, _files?: PendingFile[]) => {
      setSendError(null);
      if (!botId) {
        setSendError("Pick a bot first.");
        return;
      }

      let activeSessionId = sessionId;

      if (!activeSessionId) {
        try {
          const result = await spawn.mutateAsync({
            bot_id: botId,
            parent_channel_id: parentChannelId,
            context,
          });
          activeSessionId = result.session_id;
          persist({ sessionId: activeSessionId, botId });
        } catch (err) {
          setSendError(err instanceof Error ? err.message : "Failed to start session");
          return;
        }
      }

      try {
        await submitChat.mutateAsync({
          message,
          bot_id: botId,
          client_id: "web",
          session_id: activeSessionId,
          channel_id: parentChannelId,
          ...(modelOverride ? {
            model_override: modelOverride,
            model_provider_id_override: modelProviderId,
          } : {}),
        });
        qc.invalidateQueries({ queryKey: ["session-messages", activeSessionId] });
      } catch (err) {
        setSendError(err instanceof Error ? err.message : "Failed to send message");
      }
    },
    [botId, sessionId, parentChannelId, context, persist, spawn, submitChat, modelOverride, modelProviderId, qc],
  );

  // Two-click speed-bump for reset.
  const [resetArmed, setResetArmed] = useState(false);
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!resetArmed) return;
    resetTimerRef.current = setTimeout(() => setResetArmed(false), 3000);
    return () => {
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
    };
  }, [resetArmed]);

  const handleReset = useCallback(() => {
    if (!resetArmed) {
      setResetArmed(true);
      return;
    }
    if (sessionStorageKey) clearEphemeralState(sessionStorageKey);
    setStored(null);
    setSendError(null);
    setResetArmed(false);
  }, [resetArmed, sessionStorageKey]);

  const handleHeaderClose = useCallback(() => {
    // Dock mode: collapse to FAB so the session stays recoverable.
    // Modal mode: call the parent-supplied onClose — the parent decides
    // whether the dock/modal remains mounted.
    if (mode === "dock") setDockExpanded(false);
    else onClose();
  }, [mode, onClose]);

  const expandTitle = mode === "dock" ? "Expand to full view" : "Minimize to dock";
  const ExpandIcon = mode === "dock" ? Maximize2 : Minimize2;
  const overheadColor = useMemo(() => {
    if (overheadPct == null) return null;
    if (overheadPct >= 0.4) return "#ef4444";
    if (overheadPct >= 0.2) return "#eab308";
    return null;
  }, [overheadPct]);

  const header = (
    <div
      className="flex items-center justify-between gap-2 px-3 py-2 shrink-0"
      style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
    >
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className="text-[13px] font-semibold text-text truncate shrink-0">{title}</span>
        <div className="min-w-[120px] max-w-[200px]">
          <BotPicker
            compact
            value={botId}
            onChange={setBotId}
            bots={bots ?? []}
            disabled={!!sessionId}
            placeholder="Pick a bot"
          />
        </div>
      </div>
      <div className="flex items-center gap-0.5 shrink-0">
        {overheadColor && (
          <button
            type="button"
            title={`Context overhead: ${Math.round((overheadPct ?? 0) * 100)}% of the model's window is spent on tools, skills, and system prompts`}
            className="w-2 h-2 rounded-full mx-1"
            style={{ backgroundColor: overheadColor, border: "none", cursor: "help" }}
          />
        )}
        <button
          onClick={() => setMode((m) => (m === "dock" ? "modal" : "dock"))}
          title={expandTitle}
          aria-label={expandTitle}
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
        >
          <ExpandIcon size={13} />
        </button>
        {sessionId && (
          <button
            onClick={handleReset}
            title={resetArmed ? "Click again within 3 s to reset the session" : "Reset session"}
            aria-label="Reset session"
            className={`p-1.5 rounded transition-colors ${
              resetArmed
                ? "text-red-400 bg-red-500/10 animate-pulse"
                : "text-text-dim hover:text-text hover:bg-white/5"
            }`}
          >
            <RotateCcw size={13} />
          </button>
        )}
        <button
          onClick={handleHeaderClose}
          title={mode === "dock" ? "Collapse to button" : "Close"}
          aria-label={mode === "dock" ? "Collapse to button" : "Close"}
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
        >
          <X size={13} />
        </button>
      </div>
    </div>
  );

  const body = (
    <div className="flex flex-col h-full">
      {header}
      <div className="flex-1 min-h-0 relative">
        {sessionId ? (
          <SessionChatView
            sessionId={sessionId}
            parentChannelId={parentChannelId}
            botId={botId}
            emptyStateComponent={emptyState}
          />
        ) : (
          <div
            className="absolute inset-0 flex items-center justify-center text-text-dim text-sm px-4 text-center"
          >
            {emptyState ?? "Send a message to start the conversation"}
          </div>
        )}
      </div>
      {sendError && (
        <div className="px-4 py-1.5 text-[11px] text-red-400 border-t border-red-500/20 bg-red-500/5 shrink-0">
          {sendError}
        </div>
      )}
      <div className="shrink-0" style={{ borderTop: `1px solid ${t.surfaceBorder}` }}>
        <MessageInput
          onSend={handleSend}
          disabled={!botId}
          isStreaming={isSending}
          currentBotId={botId || undefined}
          channelId={sessionId ?? undefined}
          modelOverride={modelOverride}
          modelProviderIdOverride={modelProviderId}
          onModelOverrideChange={setModelOverride}
          defaultModel={bots?.find((b) => b.id === botId)?.model}
          configOverhead={overheadPct}
        />
      </div>
    </div>
  );

  if (mode === "modal") {
    return (
      <EphemeralSessionModal open={open} onClose={onClose} title={title}>
        {body}
      </EphemeralSessionModal>
    );
  }

  return (
    <EphemeralSessionDock
      open={open}
      expanded={dockExpanded}
      onExpandedChange={setDockExpanded}
      title={title}
    >
      {body}
    </EphemeralSessionDock>
  );
}
