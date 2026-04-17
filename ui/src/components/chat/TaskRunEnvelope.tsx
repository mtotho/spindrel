import { memo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleDot,
  ExternalLink,
  Loader2,
  Repeat,
  Timer,
  Workflow,
  XCircle,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import type { Message } from "../../types/api";
import { formatTimeShort } from "../../utils/time";

// ---------------------------------------------------------------------------
// Metadata shape persisted on the anchor Message (see
// app/services/task_run_anchor.py:_build_metadata). Kept deliberately loose
// here — the renderer tolerates missing fields so a back-end that falls a
// release behind still renders something reasonable.
// ---------------------------------------------------------------------------

interface StepInfo {
  index: number;
  type: "agent" | "exec" | "tool" | string;
  label: string;
  status: "pending" | "running" | "done" | "failed" | "skipped" | string;
  duration_ms?: number | null;
  result_preview?: string | null;
  error?: string | null;
}

interface TaskRunMeta {
  kind?: string;
  task_id?: string;
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
// Typography / colour helpers. We stay on Tailwind utility classes plus the
// existing surface-border / text-muted tokens so this envelope slots into
// the Phase 5 unified card design (surfaceRaised, rounded-lg, uppercase
// tracking-wider headers) used by WidgetCard + integration event envelopes.
// ---------------------------------------------------------------------------

function typeBadgeClasses(taskType: string | undefined): string {
  switch (taskType) {
    case "pipeline":
      return "bg-amber-500/15 text-amber-400 border border-amber-500/25";
    case "exec":
      return "bg-blue-500/15 text-blue-400 border border-blue-500/25";
    case "workflow":
      return "bg-violet-500/15 text-violet-400 border border-violet-500/25";
    default:
      return "bg-accent/10 text-accent border border-accent/25";
  }
}

function statusColor(status: string | undefined): string {
  switch (status) {
    case "running":
      return "text-accent";
    case "complete":
      return "text-green-500";
    case "failed":
      return "text-red-500";
    case "skipped":
      return "text-text-dim";
    case "pending":
    default:
      return "text-text-muted";
  }
}

function statusLabel(status: string | undefined): string {
  switch (status) {
    case "running":
      return "running";
    case "complete":
      return "complete";
    case "failed":
      return "failed";
    case "skipped":
      return "skipped";
    case "pending":
    default:
      return "pending";
  }
}

function StepIcon({ status }: { status: string }) {
  switch (status) {
    case "done":
      return <CheckCircle2 size={14} className="text-green-500 flex-shrink-0" />;
    case "failed":
      return <XCircle size={14} className="text-red-500 flex-shrink-0" />;
    case "running":
      return <Loader2 size={14} className="text-accent animate-spin flex-shrink-0" />;
    case "skipped":
      return <CircleDot size={14} className="text-text-dim flex-shrink-0" />;
    default:
      return <Circle size={14} className="text-text-dim flex-shrink-0" />;
  }
}

function stepTypeBadgeClasses(type: string): string {
  switch (type) {
    case "exec":
      return "bg-blue-500/10 text-blue-400 border border-blue-500/20";
    case "tool":
      return "bg-purple-500/10 text-purple-400 border border-purple-500/20";
    case "agent":
    default:
      return "bg-amber-500/10 text-amber-400 border border-amber-500/20";
  }
}

function formatDuration(ms: number | null | undefined): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${Math.floor((ms % 60000) / 1000)}s`;
}

function contextPill(
  mode: string | undefined,
  count: number | undefined,
): { label: string; Icon: LucideIcon } {
  if (mode === "recent") return { label: `Context: Last ${count ?? 10}`, Icon: Repeat };
  if (mode === "full") return { label: "Context: Full history", Icon: Repeat };
  return { label: "Context: None", Icon: Repeat };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const TaskRunEnvelope = memo(function TaskRunEnvelope({ message }: Props) {
  const navigate = useNavigate();
  const meta = (message.metadata ?? {}) as TaskRunMeta;
  const steps: StepInfo[] = Array.isArray(meta.steps) ? meta.steps : [];
  const totalSteps = meta.step_count ?? steps.length;
  const status = (meta.status ?? "pending") as string;
  const title = meta.title || "Task run";
  const taskType = (meta.task_type ?? "agent") as string;
  const isRunning = status === "running";
  const isDone = status === "complete";
  const isFailed = status === "failed";
  const doneCount = steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const timestamp = formatTimeShort(message.created_at);

  const [expanded, setExpanded] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);

  const ctx = contextPill(meta.context_mode, meta.context_recent_count);

  return (
    <div className="mx-5 my-1.5 group rounded-lg border border-surface-border bg-surface-raised/60 transition-colors">
      {/* ── Header row ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-2 px-3.5 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <Workflow size={14} className="text-text-dim flex-shrink-0" />
          <span
            className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${typeBadgeClasses(taskType)}`}
          >
            {taskType}
          </span>
          <span className="truncate text-xs font-semibold text-text">
            {title}
          </span>
          <span
            className={`inline-flex items-center gap-1 text-[11px] font-medium ${statusColor(status)}`}
          >
            {isRunning && <Loader2 size={11} className="animate-spin" />}
            {isDone && <CheckCircle2 size={11} />}
            {isFailed && <XCircle size={11} />}
            <span>{statusLabel(status)}</span>
            {totalSteps > 0 && (
              <span className="text-text-dim">
                {" · "}
                {doneCount}/{totalSteps}
              </span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-text-dim whitespace-nowrap">{timestamp}</span>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[10px] text-text-dim hover:text-text-muted uppercase tracking-wider flex items-center gap-0.5 bg-transparent border-none cursor-pointer"
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            {expanded ? "collapse" : "expand"}
          </button>
        </div>
      </div>

      {/* ── Step list ──────────────────────────────────────────────── */}
      {steps.length > 0 && (
        <div className="border-t border-surface-border/50">
          {steps.map((s) => {
            const isOpen = openStep === s.index;
            const canOpen = !!(s.result_preview || s.error);
            return (
              <div
                key={s.index}
                className="border-b border-surface-border/30 last:border-b-0"
              >
                <button
                  type="button"
                  onClick={() => canOpen && setOpenStep(isOpen ? null : s.index)}
                  disabled={!canOpen}
                  className={`flex w-full items-center gap-2.5 px-3.5 py-2 text-left bg-transparent border-none ${
                    canOpen ? "cursor-pointer hover:bg-surface-overlay/30" : "cursor-default"
                  }`}
                >
                  <span className="text-[10px] font-mono text-text-dim w-4 text-right flex-shrink-0">
                    {s.index + 1}
                  </span>
                  <StepIcon status={s.status} />
                  <span
                    className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${stepTypeBadgeClasses(s.type)}`}
                  >
                    {s.type}
                  </span>
                  <span
                    className={`flex-1 min-w-0 truncate text-[12px] ${
                      s.status === "done" ? "text-text-muted" : "text-text"
                    } ${s.status === "skipped" ? "line-through text-text-dim" : ""}`}
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
                      className={`text-text-dim transition-transform ${isOpen ? "rotate-90" : ""}`}
                    />
                  )}
                </button>
                {isOpen && (s.result_preview || s.error) && (
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

      {/* ── Footer meta row ────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 border-t border-surface-border/50 px-3.5 py-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-text-dim min-w-0">
          <span className="inline-flex items-center gap-1">
            <ctx.Icon size={10} />
            {ctx.label}
          </span>
          <span className="inline-flex items-center gap-1">
            <Timer size={10} />
            {meta.post_final_to_channel ? "Posts summary to channel" : "No dispatch"}
          </span>
          {meta.bot_id && (
            <span className="truncate">
              {meta.bot_id}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {meta.task_id && (
            <button
              onClick={() => navigate(`/admin/tasks/${meta.task_id}`)}
              className="text-[10.5px] text-accent hover:text-accent-hover bg-transparent border-none cursor-pointer inline-flex items-center gap-1 px-1 py-0.5 rounded hover:bg-accent/5 transition-colors"
            >
              Open in admin
              <ExternalLink size={10} />
            </button>
          )}
        </div>
      </div>

      {/* ── Expanded raw metadata (debug / json view) ──────────────── */}
      {expanded && (
        <div className="border-t border-surface-border/50 px-3.5 py-2 bg-surface-overlay/40">
          <pre className="m-0 font-mono text-[10px] text-text-dim whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
            {JSON.stringify(meta, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
});
