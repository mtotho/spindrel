import { useCallback, useEffect, useState } from "react";
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
import { useChatStore } from "@/src/stores/chat";
import { EphemeralBotPicker } from "./EphemeralBotPicker";
import { EphemeralSessionModal } from "./EphemeralSessionModal";
import { EphemeralSessionDock } from "./EphemeralSessionDock";
import { SessionChatView } from "./SessionChatView";
import { MessageInput, type PendingFile } from "./MessageInput";
import { useThemeTokens } from "@/src/theme/tokens";
import { RotateCcw } from "lucide-react";

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
 * Manages: session spawn-on-first-send, bot picker state, localStorage
 * persistence, and shape routing (modal vs. dock). Mounts SessionChatView
 * and MessageInput verbatim — no parallel renderer.
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

  // Resolve default bot — caller's defaultBotId or first available bot
  const resolvedDefault = defaultBotId ?? bots?.[0]?.id ?? "";

  // Restore or initialise persisted state
  const [stored, setStored] = useState<StoredEphemeralState | null>(() =>
    sessionStorageKey ? loadEphemeralState(sessionStorageKey) : null,
  );

  const sessionId = stored?.sessionId ?? null;
  const botId = stored?.botId ?? resolvedDefault;

  const setBotId = useCallback(
    (id: string) => {
      if (stored && stored.sessionId) return; // locked once session exists
      const next = { sessionId: stored?.sessionId ?? "", botId: id };
      setStored((s) => ({ ...s, botId: id, sessionId: s?.sessionId ?? "" }));
      if (sessionStorageKey) saveEphemeralState(sessionStorageKey, next);
    },
    [stored, sessionStorageKey],
  );

  // Sync resolvedDefault into state if no session yet and no stored choice
  useEffect(() => {
    if (!stored?.botId && resolvedDefault) {
      setStored((s) => ({ sessionId: s?.sessionId ?? "", botId: resolvedDefault }));
    }
  }, [resolvedDefault, stored?.botId]);

  // --- Spawn mutation ---
  const spawn = useSpawnEphemeralSession();

  // --- Chat submission ---
  const submitChat = useSubmitChat();
  const [sendError, setSendError] = useState<string | null>(null);
  const chatState = useChatStore((s) =>
    sessionId ? s.getChannel(sessionId) : null,
  );
  const isSending = submitChat.isPending || (chatState?.isProcessing ?? false);

  const handleSend = useCallback(
    async (message: string, _files?: PendingFile[]) => {
      setSendError(null);
      if (!botId) {
        setSendError("Pick a bot first.");
        return;
      }

      let activeSessionId = sessionId;

      // Spawn on first send
      if (!activeSessionId) {
        try {
          const result = await spawn.mutateAsync({
            bot_id: botId,
            parent_channel_id: parentChannelId,
            context,
          });
          activeSessionId = result.session_id;
          const next = { sessionId: activeSessionId, botId };
          setStored(next);
          if (sessionStorageKey) saveEphemeralState(sessionStorageKey, next);
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
        });
        qc.invalidateQueries({ queryKey: ["session-messages", activeSessionId] });
      } catch (err) {
        setSendError(err instanceof Error ? err.message : "Failed to send message");
      }
    },
    [botId, sessionId, parentChannelId, context, sessionStorageKey, spawn, submitChat, qc],
  );

  const handleNewChat = useCallback(() => {
    if (sessionStorageKey) clearEphemeralState(sessionStorageKey);
    setStored(null);
    setSendError(null);
  }, [sessionStorageKey]);

  const header = (
    <div
      className="flex items-center justify-between gap-2 px-4 py-2.5 shrink-0"
      style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <span className="text-sm font-semibold text-text truncate">{title}</span>
      </div>
      <div className="flex items-center gap-0.5 shrink-0">
        <EphemeralBotPicker
          value={botId}
          onChange={setBotId}
          disabled={!!sessionId}
        />
        {sessionId && (
          <button
            onClick={handleNewChat}
            title="Start new chat"
            className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
          >
            <RotateCcw size={13} />
          </button>
        )}
      </div>
    </div>
  );

  const body = (
    <div className="flex flex-col h-full">
      {header}
      <div className="flex-1 min-h-0 relative">
        {sessionId && parentChannelId ? (
          <SessionChatView
            sessionId={sessionId}
            parentChannelId={parentChannelId}
            botId={botId}
            emptyStateComponent={emptyState}
          />
        ) : (
          <div
            className="absolute inset-0 flex items-center justify-center text-text-dim text-sm"
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
        />
      </div>
    </div>
  );

  if (shape === "modal") {
    return (
      <EphemeralSessionModal open={open} onClose={onClose} title={title}>
        {body}
      </EphemeralSessionModal>
    );
  }

  return (
    <EphemeralSessionDock open={open} onClose={onClose} title={title}>
      {body}
    </EphemeralSessionDock>
  );
}
