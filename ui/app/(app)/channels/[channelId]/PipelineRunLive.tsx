import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  PauseCircle,
  Workflow,
  X,
  XCircle,
} from "lucide-react";
import { useTask } from "@/src/api/hooks/useTasks";
import type { StepState } from "@/src/api/hooks/useTasks";
import { useSubmitChat } from "@/src/api/hooks/useChat";
import { SessionChatView } from "@/src/components/chat/SessionChatView";
import { MessageInput, type PendingFile } from "@/src/components/chat/MessageInput";
import { useChatStore } from "@/src/stores/chat";
import { cn } from "@/src/lib/cn";

export interface PipelineRunLiveProps {
  taskId: string;
  channelId: string;
  onClose: () => void;
}

/**
 * Live (and completed) pane of the run-view modal. Loads the run's Task,
 * resolves the sub-session id, and mounts ``SessionChatView`` against it.
 * Re-fetches the task row periodically so ``status`` + ``run_session_id``
 * transitions reach the UI without a full page refresh.
 */
export function PipelineRunLive({
  taskId,
  channelId,
  onClose,
}: PipelineRunLiveProps) {
  const navigate = useNavigate();
  // Poll the task row while it's running so status + run_session_id land.
  // `run_session_id` is spawned lazily inside `run_task_pipeline` → `ensure_anchor_message`,
  // so the first fetch after `/run` returns `null` for it. Polling stops on terminal status.
  const { data: task } = useTask(taskId, {
    refetchInterval: (t) => {
      if (!t) return 1500;
      const s = t.status;
      if (s === "complete" || s === "failed" || s === "cancelled") return false;
      // While spinning up, hit it fast; once run_session_id lands, relax.
      return t.run_session_id ? 3000 : 1500;
    },
  });

  const runSessionId = task?.run_session_id ?? null;
  const status = (task?.status ?? "pending") as string;
  const title = task?.title || task?.prompt?.split("\n")[0]?.slice(0, 60) || "Run";

  const stepStates = (task?.step_states as StepState[] | null | undefined) ?? [];
  const stepCount = (task?.steps?.length ?? stepStates.length) || 0;
  const doneCount = stepStates.filter(
    (s) => s?.status === "done" || s?.status === "skipped",
  ).length;
  const awaitingCount = stepStates.filter(
    (s) => s?.status === "awaiting_user_input",
  ).length;

  const isTerminal = status === "complete" || status === "failed" || status === "cancelled";

  // --- Session-scoped follow-up composer ---------------------------------
  // Enabled once the pipeline reaches a terminal state. Routes through POST
  // /chat with ``session_id=<sub>`` which the backend detects as a
  // sub-session follow-up, suppresses outbox dispatch, and runs the bot
  // under the sub-session's own history scope.
  const submitChat = useSubmitChat();
  const qc = useQueryClient();
  const [sendError, setSendError] = useState<string | null>(null);
  const sessionChatState = useChatStore((s) =>
    runSessionId ? s.getChannel(runSessionId) : null,
  );
  const isSending = submitChat.isPending || (sessionChatState?.isProcessing ?? false);

  const handleSend = useCallback(
    async (message: string, _files?: PendingFile[]) => {
      if (!runSessionId || !task?.bot_id || !isTerminal) return;
      setSendError(null);
      try {
        await submitChat.mutateAsync({
          session_id: runSessionId,
          bot_id: task.bot_id,
          client_id: "web",
          message,
        });
        qc.invalidateQueries({ queryKey: ["session-messages", runSessionId] });
      } catch (err) {
        setSendError(
          err instanceof Error ? err.message : "Failed to send follow-up message",
        );
      }
    },
    [runSessionId, task?.bot_id, isTerminal, submitChat, qc],
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-surface-border shrink-0">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Workflow size={16} className="text-accent shrink-0" />
          <span className="text-sm font-semibold text-text truncate">{title}</span>
          {awaitingCount > 0 ? (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded
                             bg-accent/10
                             text-[11px] font-semibold text-accent shrink-0">
              <PauseCircle size={11} />
              Your review needed
            </span>
          ) : (
            <span
              className={cn(
                "inline-flex items-center gap-1 text-[11px] font-medium shrink-0",
                status === "running" && "text-accent",
                status === "complete" && "text-success",
                status === "failed" && "text-danger",
                status === "pending" && "text-text-muted",
              )}
            >
              {status === "running" && <Loader2 size={11} className="animate-spin" />}
              {status === "complete" && <CheckCircle2 size={11} />}
              {status === "failed" && <XCircle size={11} />}
              <span>{status}</span>
              {stepCount > 0 && (
                <span className="text-text-dim">
                  {" · "}
                  {doneCount}/{stepCount}
                </span>
              )}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/admin/tasks/${taskId}`);
            }}
            className="hidden sm:inline-flex items-center gap-1 text-[11px] text-accent/80 hover:text-accent
                       px-2 py-1 rounded hover:bg-accent/5 transition-colors"
            title="Open raw task details in admin"
          >
            Raw task
            <ExternalLink size={10} />
          </button>
          <button
            onClick={onClose}
            aria-label="Close"
            className="p-1 text-text-dim hover:text-text"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Body — the sub-session transcript */}
      <div className="flex-1 min-h-0 relative">
        {runSessionId ? (
          <SessionChatView
            sessionId={runSessionId}
            parentChannelId={channelId}
            botId={task?.bot_id}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-text-dim text-xs">
            <Loader2 size={14} className="animate-spin" />
            Spinning up the run session…
          </div>
        )}
      </div>

      {/* Footer — composer is live once the run reaches a terminal state.
          Mid-run push-back requires step pause/resume (Phase E, parked). */}
      {isTerminal ? (
        <div className="border-t border-surface-border shrink-0">
          {sendError && (
            <div className="px-5 py-1.5 text-[11px] text-danger bg-danger/10">
              {sendError}
            </div>
          )}
          <MessageInput
            onSend={handleSend}
            disabled={!runSessionId}
            isStreaming={isSending}
            currentBotId={task?.bot_id}
            channelId={runSessionId ?? undefined}
          />
        </div>
      ) : (
        <div className="border-t border-surface-border shrink-0 px-5 py-2.5">
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-md
                       bg-surface-raised/40 text-[11px] text-text-dim/80"
            title="Mid-run push-back lands in a future phase."
          >
            <PauseCircle size={12} className="text-text-dim/60" />
            Composer unlocks once the run finishes — follow up with {task?.bot_id ?? "the bot"} from here.
          </div>
        </div>
      )}
    </div>
  );
}
