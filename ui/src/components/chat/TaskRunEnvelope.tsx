import { memo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleDot,
  ExternalLink,
  Loader2,
  PauseCircle,
  Workflow,
  XCircle,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { Message } from "../../types/api";
import { formatTimeShort } from "../../utils/time";
import { InlineApprovalReview } from "./InlineApprovalReview";
import { useTask } from "@/src/api/hooks/useTasks";
import type { StepState } from "@/src/api/hooks/useTasks";
import { cn } from "@/src/lib/cn";

// ---------------------------------------------------------------------------
// Metadata shape persisted on the anchor Message (see
// app/services/task_run_anchor.py:_build_metadata). Kept deliberately loose
// here — the renderer tolerates missing fields so a back-end that falls a
// release behind still renders something reasonable.
// ---------------------------------------------------------------------------

type StepStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "skipped"
  | "awaiting_user_input"
  | string;

interface StepInfo {
  index: number;
  type: "agent" | "exec" | "tool" | "user_prompt" | "foreach" | string;
  label: string;
  status: StepStatus;
  duration_ms?: number | null;
  result_preview?: string | null;
  error?: string | null;
  // user_prompt runtime payload — present when status === "awaiting_user_input"
  title?: string | null;
  widget_envelope?: Record<string, any> | null;
  response_schema?: Record<string, any> | null;
}

interface TaskRunMeta {
  kind?: string;
  task_id?: string;
  parent_task_id?: string | null;
  task_type?: string;
  bot_id?: string;
  title?: string | null;
  status?: "pending" | "running" | "complete" | "failed" | string;
  scheduled_at?: string | null;
  completed_at?: string | null;
  steps?: StepInfo[];
  step_count?: number;
  context_mode?: "none" | "recent" | "full" | string;
  context_recent_count?: number;
  post_final_to_channel?: boolean;
  result?: string | null;
  error?: string | null;
}

interface Props {
  message: Message;
}

// ---------------------------------------------------------------------------
// Type-label hygiene: user_prompt → REVIEW, foreach → APPLY. Friendlier for
// humans watching the run; admin UI still uses the technical type.
// ---------------------------------------------------------------------------

function stepTypeLabel(type: string): string {
  switch (type) {
    case "user_prompt":
      return "REVIEW";
    case "foreach":
      return "APPLY";
    default:
      return type.toUpperCase();
  }
}

function isActiveStatus(status: StepStatus): boolean {
  return status === "running" || status === "awaiting_user_input";
}

function StepIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case "done":
      return <CheckCircle2 size={14} className="text-green-500 flex-shrink-0" />;
    case "failed":
      return <XCircle size={14} className="text-red-500 flex-shrink-0" />;
    case "running":
      return <Loader2 size={14} className="text-accent animate-spin flex-shrink-0" />;
    case "awaiting_user_input":
      return <PauseCircle size={14} className="text-accent animate-pulse flex-shrink-0" />;
    case "skipped":
      return <CircleDot size={14} className="text-text-dim flex-shrink-0" />;
    default:
      return <Circle size={14} className="text-text-dim flex-shrink-0" />;
  }
}

function formatDuration(ms: number | null | undefined): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${Math.floor((ms % 60000) / 1000)}s`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const TaskRunEnvelope = memo(function TaskRunEnvelope({ message }: Props) {
  const navigate = useNavigate();
  const meta = (message.metadata ?? {}) as TaskRunMeta;
  const steps: StepInfo[] = Array.isArray(meta.steps) ? meta.steps : [];
  const totalSteps = meta.step_count ?? steps.length;
  const outerStatus = (meta.status ?? "pending") as string;
  const title = meta.title || "Task run";
  const taskType = (meta.task_type ?? "agent") as string;
  const isPipeline = taskType === "pipeline";

  const awaitingStep = steps.find((s) => s.status === "awaiting_user_input");
  const runningStep = steps.find((s) => s.status === "running");
  const activeStep = awaitingStep ?? runningStep;

  // Anchor messages persisted before the widget-envelope surfacing change
  // (2026-04-17 session 15) lack `widget_envelope` + `response_schema` on the
  // awaiting step. Rather than forcing a server-side re-emit of every stale
  // anchor, lazy-fetch the task detail — `step_states[i]` on the current task
  // row always carries the live envelope, so this self-heals in one request.
  const needsTaskFallback =
    !!awaitingStep && !awaitingStep.widget_envelope && !!meta.task_id;
  const { data: taskDetail } = useTask(needsTaskFallback ? meta.task_id : undefined);
  const liveStepState: StepState | null =
    awaitingStep && taskDetail?.step_states
      ? ((taskDetail.step_states as StepState[])[awaitingStep.index] ?? null)
      : null;

  // When any step awaits the user, the header pill wins over outerStatus —
  // "running" outer + "awaiting_user_input" inner is the paused state and we
  // want the user's attention on that, not the generic running chip.
  const headerStatus: StepStatus = awaitingStep
    ? "awaiting_user_input"
    : outerStatus === "running"
      ? "running"
      : outerStatus === "complete"
        ? "done"
        : outerStatus === "failed"
          ? "failed"
          : "pending";

  const doneCount = steps.filter(
    (s) => s.status === "done" || s.status === "skipped",
  ).length;
  const timestamp = formatTimeShort(message.created_at);
  const taskId = meta.task_id;

  const [expanded, setExpanded] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);

  return (
    <div
      className={cn(
        "mx-5 my-1.5 group rounded-r-md bg-surface-raised/40 border-l-2 transition-colors",
        headerStatus === "awaiting_user_input"
          ? "border-accent"
          : headerStatus === "failed"
            ? "border-red-500/60"
            : headerStatus === "running"
              ? "border-accent/60"
              : "border-surface-border",
      )}
      data-task-id={taskId || undefined}
      data-awaiting-review={awaitingStep ? "true" : undefined}
    >
      {/* ── Header row ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-2 px-3.5 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <Workflow size={14} className="text-text-dim flex-shrink-0" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-text-dim shrink-0">
            {isPipeline ? "pipeline" : taskType}
          </span>
          <span className="truncate text-xs font-semibold text-text">{title}</span>
          {headerStatus === "awaiting_user_input" ? (
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
                headerStatus === "running" && "text-accent",
                headerStatus === "done" && "text-green-500",
                headerStatus === "failed" && "text-red-500",
                headerStatus === "pending" && "text-text-muted",
              )}
            >
              {headerStatus === "running" && <Loader2 size={11} className="animate-spin" />}
              {headerStatus === "done" && <CheckCircle2 size={11} />}
              {headerStatus === "failed" && <XCircle size={11} />}
              <span>{headerStatus}</span>
              {totalSteps > 0 && (
                <span className="text-text-dim">
                  {" · "}
                  {doneCount}/{totalSteps}
                </span>
              )}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="hidden sm:inline text-[10px] text-text-dim whitespace-nowrap">{timestamp}</span>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[10px] text-text-dim hover:text-text-muted uppercase tracking-wider flex items-center gap-0.5 bg-transparent border-none cursor-pointer"
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            <span className="hidden sm:inline">{expanded ? "collapse" : "expand"}</span>
          </button>
        </div>
      </div>

      {/* ── Step list ──────────────────────────────────────────────── */}
      {steps.length > 0 && (
        <div className="border-t border-surface-border/40">
          {steps.map((s) => {
            const isActive = isActiveStatus(s.status) && activeStep?.index === s.index;
            const isOpen = openStep === s.index;
            const canOpen = !!(s.result_preview || s.error);
            // Fall back to live step_states from the task detail fetch when the
            // anchor metadata was persisted before widget-envelope surfacing.
            const envelope =
              s.widget_envelope ??
              (liveStepState && liveStepState.widget_envelope) ??
              null;
            const schema =
              s.response_schema ??
              (liveStepState && liveStepState.response_schema) ??
              null;
            const showInlineReview =
              s.status === "awaiting_user_input" && !!envelope && !!taskId;

            return (
              <div
                key={s.index}
                className="border-b border-surface-border/25 last:border-b-0"
              >
                <button
                  type="button"
                  onClick={() => canOpen && setOpenStep(isOpen ? null : s.index)}
                  disabled={!canOpen}
                  className={cn(
                    "flex w-full items-center gap-2.5 px-3.5 py-2 text-left bg-transparent border-none",
                    canOpen ? "cursor-pointer hover:bg-surface-overlay/30" : "cursor-default",
                  )}
                >
                  <span className="text-[10px] font-mono text-text-dim w-4 text-right flex-shrink-0">
                    {s.index + 1}
                  </span>
                  <StepIcon status={s.status} />
                  <span
                    className={cn(
                      "hidden sm:inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider flex-shrink-0",
                      isActive
                        ? "bg-accent/15 text-accent border border-accent/30"
                        : "bg-surface-overlay/40 text-text-dim border border-surface-border/60",
                    )}
                  >
                    {stepTypeLabel(s.type)}
                  </span>
                  <span
                    className={cn(
                      "flex-1 min-w-0 truncate text-[12px]",
                      s.status === "done" ? "text-text-muted" : "text-text",
                      s.status === "skipped" && "line-through text-text-dim",
                      isActive && "font-semibold",
                    )}
                  >
                    {s.label}
                  </span>
                  {s.duration_ms != null && (
                    <span className="text-[10px] font-mono text-text-dim flex-shrink-0">
                      {formatDuration(s.duration_ms)}
                    </span>
                  )}
                  {canOpen && (
                    <ChevronRight
                      size={12}
                      className={cn(
                        "text-text-dim transition-transform",
                        isOpen && "rotate-90",
                      )}
                    />
                  )}
                </button>

                {/* Inline review widget (fires inside the step row for
                    awaiting_user_input). Uses the same renderer as Findings. */}
                {showInlineReview && (
                  <div className="px-3.5 pb-3 pt-1">
                    <InlineApprovalReview
                      taskId={taskId!}
                      stepIndex={s.index}
                      widgetEnvelope={envelope}
                      responseSchema={schema}
                      headline={s.title || undefined}
                    />
                  </div>
                )}

                {/* Fallback prompt when we're awaiting but still loading the
                    envelope (or the fallback fetch failed). Gives the user a
                    path to admin so they're never stuck. */}
                {s.status === "awaiting_user_input" && !showInlineReview && (
                  <div className="px-3.5 pb-3 pt-1 flex flex-row items-center justify-between gap-2">
                    <span className="text-[11px] text-text-dim italic">
                      Loading review…
                    </span>
                    {taskId && (
                      <button
                        onClick={() => navigate(`/admin/tasks/${taskId}`)}
                        className="text-[11px] text-accent hover:underline"
                      >
                        Open in admin
                      </button>
                    )}
                  </div>
                )}

                {isOpen && canOpen && (
                  <div className="px-3.5 pb-2.5 -mt-1">
                    <pre className="m-0 rounded-md bg-surface-overlay/60 border border-surface-border px-3 py-2 font-mono text-[11px] text-text-muted whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
                      {s.error || s.result_preview}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Footer ────────────────────────────────────────────────────
          For pipeline runs we drop the boilerplate "No dispatch / Context:
          None" chips — they're noise when every pipeline shares them. The
          bot_id stays because it's the one piece of variable attribution. */}
      {(!isPipeline || meta.bot_id || taskId) && (
        <div className="flex items-center justify-between gap-3 border-t border-surface-border/40 px-3.5 py-1.5">
          <div className="hidden sm:flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-text-dim min-w-0">
            {meta.bot_id && <span className="truncate">{meta.bot_id}</span>}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0 ml-auto">
            {/* View runs — only shown on desktop where there's footer room.
                Lands on the definition's Runs tab (full execution history).
                On mobile the single "This run" link is the primary action —
                users pivot to admin history from inside that screen if needed. */}
            {meta.parent_task_id && (
              <button
                onClick={() => navigate(`/admin/tasks/${meta.parent_task_id}?tab=runs`)}
                className="hidden sm:inline-flex text-[10.5px] text-accent/80 hover:text-accent bg-transparent border-none cursor-pointer items-center gap-1 px-1 py-0.5 rounded hover:bg-accent/5 transition-colors"
              >
                View runs
                <ExternalLink size={10} />
              </button>
            )}
            {taskId && (
              <button
                onClick={() => navigate(`/admin/tasks/${taskId}`)}
                className="text-[10.5px] text-accent/80 hover:text-accent bg-transparent border-none cursor-pointer inline-flex items-center gap-1 px-1 py-0.5 rounded hover:bg-accent/5 transition-colors"
              >
                This run
                <ExternalLink size={10} />
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Expanded raw metadata (debug / json view) ──────────────── */}
      {expanded && (
        <div className="border-t border-surface-border/40 px-3.5 py-2 bg-surface-overlay/40">
          <pre className="m-0 font-mono text-[10px] text-text-dim whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
            {JSON.stringify(meta, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
});
