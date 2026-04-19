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
import { SessionChatView } from "@/src/components/chat/SessionChatView";
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

  const isTerminal = status === "complete" || status === "failed";

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-surface-border shrink-0">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Workflow size={16} className="text-accent shrink-0" />
          <span className="text-sm font-semibold text-text truncate">{title}</span>
          {awaitingCount > 0 ? (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded
                             bg-accent/15 border border-accent/40
                             text-[11px] font-semibold text-accent shrink-0">
              <PauseCircle size={11} className="animate-pulse" />
              Your review needed
            </span>
          ) : (
            <span
              className={cn(
                "inline-flex items-center gap-1 text-[11px] font-medium shrink-0",
                status === "running" && "text-accent",
                status === "complete" && "text-green-500",
                status === "failed" && "text-red-500",
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

      {/* Footer — disabled composer placeholder (Phase 3 will enable) */}
      {!isTerminal && (
        <div className="border-t border-surface-border shrink-0 px-5 py-2.5">
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-md
                       bg-surface/40 border border-surface-border/50 text-[11px] text-text-dim/80 italic"
            title="Joining a live pipeline run lands in Phase 3."
          >
            <span className="text-text-dim/60">🔒</span>
            Composer is read-only while the pipeline runs. Push-back lands in a future phase.
          </div>
        </div>
      )}
    </div>
  );
}
