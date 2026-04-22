import { useState, useCallback, useEffect } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useTask, useTaskChildren, useRunTaskNow, type TaskDetail, type StepState, type StepDef } from "@/src/api/hooks/useTasks";
import { useTaskFormState } from "@/src/components/shared/task/useTaskFormState";
import { ContentFields, ExecutionFields, TriggerFields } from "@/src/components/shared/task/TaskFormFields";
import { Trash2, Play, ExternalLink, ArrowUpRight, BookOpen, ChevronRight, Terminal, Bot, Wrench, CheckCircle2, XCircle, Clock, SkipForward, Loader2, PauseCircle, Cog, CalendarClock, Hash } from "lucide-react";
import { Link } from "react-router-dom";
import { buildRecentHref } from "@/src/lib/recentPages";
import {
  useTaskSubscriptions,
  useUpdateSubscription,
  useUnsubscribePipeline,
  type TaskSubscription,
} from "@/src/api/hooks/useChannelPipelines";
import { CronScheduleModal } from "@/src/components/shared/CronScheduleModal";
import { humanLabelFor } from "@/src/components/shared/CronInput";
import { Section } from "@/src/components/shared/FormControls";
import {
  EnableToggle,
  InfoRow,
} from "@/src/components/shared/SchedulingPickers";
import { TaskStatusBadge, TypeBadge, BotDot } from "@/src/components/shared/TaskConstants";
import { useUIStore } from "@/src/stores/ui";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";

function fmtDatetime(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function durationStr(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return "\u2014";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `${mins}m ${remSecs}s`;
}

type Tab = "overview" | "runs";

export default function TaskDetailScreen() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  // Honor ?tab=runs so in-chat "View runs" deeplinks open on the right tab.
  const initialTab: Tab =
    new URLSearchParams(window.location.search).get("tab") === "runs"
      ? "runs"
      : "overview";
  const [tab, setTab] = useState<Tab>(initialTab);
  const [savedFlash, setSavedFlash] = useState(false);
  const runNowMut = useRunTaskNow();

  const form = useTaskFormState({
    mode: "edit",
    taskId,
    onSaved: () => {
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
    },
  });

  const [pollRuns, setPollRuns] = useState(false);
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const { data: children, isLoading: loadingChildren } = useTaskChildren(
    taskId,
    tab === "runs" && pollRuns ? 3000 : false,
  );
  const hasActiveRun = children?.some((c) => c.status === "running" || c.status === "pending");
  useEffect(() => {
    if (hasActiveRun) setPollRuns(true);
    else if (children) setPollRuns(false);
  }, [hasActiveRun, children]);
  const task = form.existingTask;
  const isSchedule = !!(task?.recurrence);

  // Enrich command palette recent with task title
  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);
  const loc = useLocation();
  useEffect(() => {
    const label = task?.title || task?.prompt?.substring(0, 40);
    if (label) enrichRecentPage(buildRecentHref(loc.pathname, loc.search, loc.hash), label);
  }, [task?.title, task?.prompt, loc.pathname, loc.search, loc.hash, enrichRecentPage]);
  const SYSTEM_TASK_TYPES = new Set(["memory_hygiene", "skill_review"]);
  const isSystemManaged = !!(task && SYSTEM_TASK_TYPES.has(task.task_type));
  const isSystemSeeded = task?.source === "system";
  const systemLabel = task?.task_type === "skill_review" ? "Skill Review" : "Memory Hygiene";

  const handleDelete = useCallback(async () => {
    if (!taskId) return;
    const ok = await confirm("Delete this task?", {
      title: "Delete task",
      confirmLabel: "Delete",
      variant: "danger",
    });
    if (!ok) return;
    await form.handleDelete();
    navigate("/admin/tasks");
  }, [taskId, form, navigate, confirm]);

  const handleRunNow = useCallback(() => {
    if (taskId) runNowMut.mutate(taskId, {
      onSuccess: () => { setTab("runs"); setPollRuns(true); },
    });
  }, [taskId, runNowMut]);

  if (form.loadingTask) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <div className="chat-spinner" />
      </div>
    );
  }

  if (!task) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <span className="text-text-dim text-sm">Task not found</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 bg-surface overflow-hidden">
      {/* Header */}
      <PageHeader variant="detail"
        parentLabel="Tasks"
        onBack={() => window.history.length > 1 ? navigate(-1) : navigate("/admin/tasks")}
        title={task.title || task.prompt?.substring(0, 50) || "Task"}
        subtitle={`${task.bot_id} \u00b7 ${task.task_type || "task"}`}
        right={
          <div className="flex flex-row items-center gap-1.5 sm:gap-2">
            {!isSystemManaged && (
              <button
                onClick={handleRunNow}
                disabled={runNowMut.isPending}
                title="Run now"
                className={`flex flex-row items-center gap-1 px-2 sm:px-3 py-1.5 text-xs font-semibold border-none rounded-lg cursor-pointer transition-colors ${
                  runNowMut.isPending
                    ? "bg-accent/30 text-accent animate-pulse"
                    : "bg-accent/10 text-accent hover:bg-accent/20"
                }`}
              >
                <Play size={12} fill="currentColor" />
                <span className="hidden sm:inline">Run Now</span>
              </button>
            )}
            {!isSystemManaged && !isSystemSeeded && (
              <EnableToggle
                enabled={form.status !== "cancelled"}
                onChange={(on) => {
                  form.setStatus(on ? (isSchedule ? "active" : "pending") : "cancelled");
                }}
                compact
              />
            )}
            {!isSystemManaged && !isSystemSeeded && (
              <button
                onClick={handleDelete}
                disabled={form.deleteMut.isPending}
                title="Delete"
                className="hidden sm:flex flex-row items-center gap-1 px-2.5 py-1.5 text-xs border border-danger/30 rounded-lg bg-transparent text-danger cursor-pointer hover:bg-danger/10 transition-colors"
              >
                <Trash2 size={13} />
              </button>
            )}
            {!isSystemManaged && !isSystemSeeded && (
              <button
                onClick={form.handleSave}
                disabled={form.saving || !form.canSave}
                className={`px-3 sm:px-4 py-1.5 text-xs font-semibold border-none rounded-lg transition-all duration-150 ${
                  savedFlash
                    ? "bg-success text-white"
                    : form.canSave
                      ? "bg-accent text-white cursor-pointer hover:bg-accent-hover"
                      : "bg-surface-border text-text-dim cursor-not-allowed"
                } ${form.saving ? "opacity-70" : ""}`}
              >
                {form.saving ? "..." : savedFlash ? "Saved!" : "Save"}
              </button>
            )}
          </div>
        }
      />

      {/* Error display */}
      {form.error && (
        <div className="px-5 py-2 bg-danger/[0.08] text-danger text-xs">
          {form.error?.message || "An error occurred"}
        </div>
      )}

      {/* System-seeded banner */}
      {isSystemSeeded && (
        <div className="flex flex-row items-start gap-2 px-5 py-2.5 bg-accent/[0.06] border-b border-accent/[0.15] text-xs text-accent">
          <Cog size={13} className="shrink-0 mt-px" />
          <span className="leading-relaxed">
            <span className="font-semibold">System pipeline</span> — seeded from{" "}
            <code className="font-mono bg-accent/10 px-1 rounded">
              app/data/system_pipelines/{task.id}.yaml
            </code>
            . Edits are overwritten on server restart.
          </span>
        </div>
      )}

      {/* Parent definition banner — shown when viewing a task run (child) */}
      {task.parent_task_id && (
        <button
          onClick={() => navigate(`/admin/tasks/${task.parent_task_id}`)}
          className="flex flex-row items-center gap-2 px-5 py-2 bg-accent/[0.06] border-b border-accent/[0.15] text-xs text-accent cursor-pointer hover:bg-accent/[0.10] transition-colors w-full border-none text-left shrink-0"
        >
          <ArrowUpRight size={13} className="shrink-0" />
          <span>
            This is a run instance.{" "}
            <span className="font-semibold underline decoration-accent/30">View task definition</span>
          </span>
        </button>
      )}

      {/* Tab bar — hidden for system-managed tasks */}
      {!isSystemManaged && (
        <div className="flex flex-row items-center gap-0.5 px-5 border-b border-surface-border">
          {(["overview", "runs"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2.5 text-xs font-semibold border-none bg-transparent cursor-pointer capitalize transition-colors relative ${
                tab === t
                  ? "text-accent"
                  : "text-text-muted hover:text-text"
              }`}
            >
              {t === "runs" ? `Runs (${children?.length ?? task.run_count ?? 0})` : t}
              {tab === t && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent rounded-full" />
              )}
            </button>
          ))}
        </div>
      )}

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {isSystemManaged ? (
          <SystemManagedOverview task={task} label={systemLabel} />
        ) : tab === "overview" ? (
          <OverviewTab form={form} task={task} readOnly={isSystemSeeded} />
        ) : (
          <RunsTab
            taskId={taskId!}
            task={task}
            children={children}
            loading={loadingChildren}
            onRunNow={handleRunNow}
            runningNow={runNowMut.isPending}
          />
        )}
      </div>
      <ConfirmDialogSlot />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Tab — reuses shared form fields
// ---------------------------------------------------------------------------
function OverviewTab({ form, task, readOnly }: { form: ReturnType<typeof useTaskFormState>; task: TaskDetail; readOnly?: boolean }) {
  return (
    <fieldset
      disabled={readOnly}
      className={`flex flex-col gap-0 max-w-4xl border-0 p-0 m-0 ${readOnly ? "opacity-95" : ""}`}
    >
      <div className="px-5 py-5 flex flex-col gap-4">
        <ContentFields form={form} promptRows={10} />
      </div>
      <div className="px-5 py-5 border-t border-surface-border flex flex-col gap-4">
        <ExecutionFields form={form} />
      </div>
      <div className="px-5 py-5 border-t border-surface-border flex flex-col gap-4">
        <TriggerFields form={form} />
      </div>

      {/* Subscribed channels — for pipeline definitions only */}
      {task.task_type === "pipeline" && (
        <div className="px-5 py-5 border-t border-surface-border">
          <SubscribedChannelsSection taskId={task.id} />
        </div>
      )}

      {/* Timing info */}
      <div className="px-5 py-5 border-t border-surface-border">
        <Section title="Timing">
          <div className="flex flex-col gap-2">
            <InfoRow label="Created" value={fmtDatetime(task.created_at)} />
            <InfoRow label="Scheduled" value={fmtDatetime(task.scheduled_at)} />
            <InfoRow label="Run At" value={fmtDatetime(task.run_at)} />
            <InfoRow label="Completed" value={fmtDatetime(task.completed_at)} />
            {task.run_count > 0 && <InfoRow label="Run Count" value={String(task.run_count)} />}
            {task.retry_count > 0 && <InfoRow label="Retry Count" value={String(task.retry_count)} />}
          </div>
        </Section>
      </div>

      {/* Result/Error for one-shot tasks */}
      {task.result && (
        <div className="px-5 py-5 border-t border-surface-border">
          <Section title="Result">
            <pre className="text-xs text-success font-mono whitespace-pre-wrap bg-input p-3 rounded-lg border border-surface-border max-h-72 overflow-auto m-0">
              {task.result}
            </pre>
          </Section>
        </div>
      )}
      {task.error && (
        <div className="px-5 py-5 border-t border-surface-border">
          <Section title="Error">
            <pre className="text-xs text-danger font-mono whitespace-pre-wrap bg-danger/5 p-3 rounded-lg border border-danger/20 max-h-48 overflow-auto m-0">
              {task.error}
            </pre>
          </Section>
        </div>
      )}
    </fieldset>
  );
}

// ---------------------------------------------------------------------------
// Runs Tab — child task history
// ---------------------------------------------------------------------------
function RunsTab({ taskId, task, children, loading, onRunNow, runningNow }: {
  taskId: string;
  task: TaskDetail;
  children: TaskDetail[] | undefined;
  loading: boolean;
  onRunNow: () => void;
  runningNow: boolean;
}) {
  const runs = children ?? [];
  const sortedRuns = [...runs].sort((a, b) =>
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
  const isOneShot = !task.recurrence && runs.length === 0;

  return (
    <div className="flex flex-col">
      {/* Action bar */}
      <div className="flex flex-row items-center justify-between px-5 py-3 border-b border-surface-border">
        <span className="text-xs text-text-muted">
          {isOneShot ? "Single execution" : `${runs.length} run${runs.length !== 1 ? "s" : ""}`}
        </span>
        <button
          onClick={onRunNow}
          disabled={runningNow}
          className={`flex flex-row items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border-none rounded-lg cursor-pointer transition-colors ${
            runningNow
              ? "bg-accent/30 text-accent animate-pulse"
              : "bg-accent/10 text-accent hover:bg-accent/20"
          }`}
        >
          <Play size={12} fill="currentColor" />
          Run Now
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="chat-spinner" />
        </div>
      ) : isOneShot ? (
        <OneShotResult task={task} />
      ) : runs.length === 0 ? (
        <div className="flex items-center justify-center py-16 text-text-dim text-sm">
          No runs yet. Click "Run Now" to trigger the first execution.
        </div>
      ) : (
        <div className="flex flex-col">
          {sortedRuns.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RunRow — expandable row with full result, error, and step states
// ---------------------------------------------------------------------------

const STEP_STATUS_ICON: Record<string, typeof CheckCircle2> = {
  done: CheckCircle2,
  failed: XCircle,
  running: Loader2,
  pending: Clock,
  skipped: SkipForward,
  awaiting_user_input: PauseCircle,
};

const STEP_TYPE_ICON: Record<string, typeof Terminal> = {
  exec: Terminal,
  tool: Wrench,
  agent: Bot,
};

function StepStatusIcon({ status }: { status: string }) {
  const Icon = STEP_STATUS_ICON[status] || Clock;
  const color = status === "done" ? "text-success" :
    status === "failed" ? "text-danger" :
    status === "running" ? "text-accent animate-spin" :
    status === "awaiting_user_input" ? "text-accent animate-pulse" :
    status === "skipped" ? "text-text-dim" : "text-text-dim";
  return <Icon size={12} className={color} />;
}

// Per-step row for the pipeline detail panel. Pulled out so each row can
// lazy-fetch its child task and surface a real Trace link once the child
// task's correlation_id lands — navigating to the actual trace page
// (/admin/logs/{correlation_id}) instead of the child task detail.
function PipelineStepRow({
  ss,
  stepDef,
  index,
}: {
  ss: StepState;
  stepDef: StepDef | undefined;
  index: number;
}) {
  const navigate = useNavigate();
  const childTaskId = ss.task_id;
  const StepIcon = STEP_TYPE_ICON[stepDef?.type || "agent"] || Bot;
  const label = stepDef?.label || stepDef?.id || `Step ${index + 1}`;
  // Only fetch child detail for active/terminal agent steps. Skipping when
  // pending/skipped saves queries on foreach-expanded pipelines.
  const shouldFetchChild = !!childTaskId && ss.status !== "pending" && ss.status !== "skipped";
  const { data: childTask } = useTask(shouldFetchChild ? childTaskId : undefined);
  const correlationId = childTask?.correlation_id;

  return (
    <div className="flex flex-col gap-1 rounded-lg bg-surface-raised/40 px-3 py-2">
      <div className="flex flex-row items-center gap-2">
        <StepStatusIcon status={ss.status} />
        <StepIcon size={11} className="text-text-dim" />
        <span className="text-[11px] font-medium text-text">{label}</span>
        <span className="text-[10px] text-text-dim ml-auto">
          {ss.started_at && ss.completed_at ? durationStr(ss.started_at, ss.completed_at) : ss.status}
        </span>
        {correlationId && (
          <button
            onClick={(e) => { e.stopPropagation(); navigate(`/admin/logs/${correlationId}`); }}
            title="Open the LLM trace for this step"
            className="flex items-center gap-1 text-[10px] text-accent/80 hover:text-accent
                       px-1.5 py-0.5 rounded hover:bg-accent/10 transition-colors"
          >
            Trace
            <ExternalLink size={10} />
          </button>
        )}
        {childTaskId && (
          <button
            onClick={(e) => { e.stopPropagation(); navigate(`/admin/tasks/${childTaskId}`); }}
            title="Open the child run detail"
            className="flex items-center gap-1 text-[10px] text-text-dim hover:text-text-muted
                       px-1.5 py-0.5 rounded hover:bg-surface-overlay/50 transition-colors"
          >
            Run
            <ExternalLink size={10} />
          </button>
        )}
      </div>
      {ss.result && (
        <pre className="text-[10px] text-text-muted font-mono whitespace-pre-wrap bg-input/50 px-2 py-1.5 rounded border border-surface-border/50 max-h-40 overflow-auto m-0 ml-5">
          {ss.result}
        </pre>
      )}
      {ss.error && (
        <pre className="text-[10px] text-danger font-mono whitespace-pre-wrap bg-danger/5 px-2 py-1.5 rounded border border-danger/20 max-h-32 overflow-auto m-0 ml-5">
          {ss.error}
        </pre>
      )}
    </div>
  );
}

function RunRow({ run }: { run: TaskDetail }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const hasPipeline = (run.step_states?.length ?? 0) > 0;
  const hasDetail = !!(run.result || run.error || hasPipeline);

  return (
    <div className="border-b border-surface-border/50">
      {/* Summary row */}
      <button
        onClick={() => hasDetail && setOpen(!open)}
        className={`flex flex-row items-center gap-3 px-5 py-2.5 w-full border-none text-left transition-colors ${
          hasDetail ? "cursor-pointer hover:bg-surface-overlay/30" : "cursor-default"
        } ${open ? "bg-surface-overlay/20" : "bg-transparent"}`}
      >
        {/* Chevron */}
        <div className="w-4 shrink-0 flex items-center justify-center">
          {hasDetail ? (
            <ChevronRight size={12} className={`text-text-dim transition-transform duration-150 ${open ? "rotate-90" : ""}`} />
          ) : (
            <span className="w-3" />
          )}
        </div>
        <div className="w-20 shrink-0">
          <TaskStatusBadge status={run.status} />
        </div>
        <div className="w-36 shrink-0 text-[11px] text-text-muted">
          {fmtDatetime(run.run_at || run.scheduled_at)}
        </div>
        <div className="w-36 shrink-0 text-[11px] text-text-muted">
          {fmtDatetime(run.completed_at)}
        </div>
        <div className="w-16 shrink-0 text-right text-[11px] text-text-dim font-mono">
          {durationStr(run.run_at || run.scheduled_at, run.completed_at)}
        </div>
        <div className="flex-1 min-w-0">
          {run.error ? (
            <span className="text-[11px] text-danger truncate block">{run.error.substring(0, 120)}</span>
          ) : run.result ? (
            <span className="text-[11px] text-text-muted truncate block">{run.result.substring(0, 120)}</span>
          ) : run.status === "running" ? (
            <span className="text-[11px] text-accent">Running...</span>
          ) : (
            <span className="text-[11px] text-text-dim">{"\u2014"}</span>
          )}
        </div>
        <div className="w-8 shrink-0 flex justify-end">
          {run.correlation_id && (
            <span
              onClick={(e) => { e.stopPropagation(); navigate(`/admin/logs/${run.correlation_id}`); }}
              title="View trace"
              className="flex items-center justify-center w-6 h-6 rounded-md text-text-muted hover:text-accent hover:bg-accent/10 transition-colors"
            >
              <ExternalLink size={11} />
            </span>
          )}
        </div>
      </button>

      {/* Expanded detail panel */}
      {open && (
        <div className="px-5 pb-4 pt-1 ml-4 border-l-2 border-surface-border">
          {/* Pipeline step states */}
          {hasPipeline && (
            <div className="mb-3">
              <div className="text-[10px] font-semibold text-text-dim uppercase tracking-wider mb-2">Steps</div>
              <div className="flex flex-col gap-1.5">
                {run.step_states!.map((ss, i) => (
                  <PipelineStepRow key={i} ss={ss} stepDef={run.steps?.[i]} index={i} />
                ))}
              </div>
            </div>
          )}

          {/* Full error */}
          {run.error && !hasPipeline && (
            <div className="mb-3">
              <div className="text-[10px] font-semibold text-text-dim uppercase tracking-wider mb-1.5">Error</div>
              <pre className="text-[11px] text-danger font-mono whitespace-pre-wrap bg-danger/5 p-3 rounded-lg border border-danger/20 max-h-48 overflow-auto m-0">
                {run.error}
              </pre>
            </div>
          )}

          {/* Full result (non-pipeline) */}
          {run.result && !hasPipeline && (
            <div className="mb-3">
              <div className="text-[10px] font-semibold text-text-dim uppercase tracking-wider mb-1.5">Result</div>
              <pre className="text-[11px] text-text-muted font-mono whitespace-pre-wrap bg-input p-3 rounded-lg border border-surface-border max-h-72 overflow-auto m-0">
                {run.result}
              </pre>
            </div>
          )}

          {/* Trace link */}
          {run.correlation_id && (
            <button
              onClick={() => navigate(`/admin/logs/${run.correlation_id}`)}
              className="flex flex-row items-center gap-1.5 text-[11px] text-accent bg-transparent border-none cursor-pointer hover:underline p-0"
            >
              <ExternalLink size={11} />
              View full trace
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// System-managed overview
// ---------------------------------------------------------------------------
function SystemManagedOverview({ task, label }: { task: TaskDetail; label: string }) {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col items-center justify-center gap-6 py-16 px-8 max-w-lg mx-auto">
      <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-accent/10">
        <BookOpen size={28} className="text-accent" />
      </div>
      <div className="text-center">
        <h3 className="text-base font-bold text-text m-0 mb-1">System-Managed Task</h3>
        <p className="text-sm text-text-muted m-0">
          This <span className="font-semibold">{label}</span> task is automatically configured from the Learning Center.
          To change its schedule, prompt, or bot settings, edit them there.
        </p>
      </div>

      <button
        onClick={() => navigate("/admin/learning")}
        className="flex flex-row items-center gap-2 px-5 py-2.5 text-sm font-semibold border-none rounded-lg bg-accent text-white cursor-pointer hover:bg-accent-hover transition-colors"
      >
        <BookOpen size={16} />
        Open Learning Center
      </button>

      {/* Read-only summary */}
      <div className="w-full border-t border-surface-border pt-5 flex flex-col gap-3">
        <div className="text-[11px] font-semibold text-text-dim uppercase tracking-wider">Task Info</div>
        <InfoRow label="Bot" value={task.bot_id} />
        <InfoRow label="Status" value={task.status} />
        <InfoRow label="Recurrence" value={task.recurrence || "None"} />
        <InfoRow label="Created" value={fmtDatetime(task.created_at)} />
        {task.scheduled_at && <InfoRow label="Next Run" value={fmtDatetime(task.scheduled_at)} />}
        {task.run_count > 0 && <InfoRow label="Total Runs" value={String(task.run_count)} />}
        {task.run_at && <InfoRow label="Last Run" value={fmtDatetime(task.run_at)} />}
        {task.completed_at && <InfoRow label="Completed" value={`${fmtDatetime(task.completed_at)} (${durationStr(task.run_at, task.completed_at)})`} />}
      </div>

      {/* Result / Error inline */}
      {task.result && (
        <div className="w-full border-t border-surface-border pt-5 flex flex-col gap-2">
          <div className="text-[11px] font-semibold text-text-dim uppercase tracking-wider">Result</div>
          <pre className="text-xs text-success font-mono whitespace-pre-wrap bg-input p-3 rounded-lg border border-surface-border max-h-96 overflow-auto m-0">
            {task.result}
          </pre>
        </div>
      )}
      {task.error && (
        <div className="w-full border-t border-surface-border pt-5 flex flex-col gap-2">
          <div className="text-[11px] font-semibold text-text-dim uppercase tracking-wider">Error</div>
          <pre className="text-xs text-danger font-mono whitespace-pre-wrap bg-danger/5 p-3 rounded-lg border border-danger/20 max-h-48 overflow-auto m-0">
            {task.error}
          </pre>
        </div>
      )}

      {/* Trace link */}
      {task.correlation_id && (
        <div className="w-full border-t border-surface-border pt-4">
          <button
            onClick={() => navigate(`/admin/logs/${task.correlation_id}`)}
            className="flex flex-row items-center gap-1.5 text-xs text-accent bg-transparent border-none cursor-pointer hover:underline p-0"
          >
            <ExternalLink size={12} />
            View full trace
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// One-shot result display
// ---------------------------------------------------------------------------
function OneShotResult({ task }: { task: TaskDetail }) {
  return (
    <div className="px-5 py-5 flex flex-col gap-4">
      <div className="flex flex-row items-center gap-3">
        <TaskStatusBadge status={task.status} />
        <span className="text-[11px] text-text-dim">
          {task.run_at ? `Started ${fmtDatetime(task.run_at)}` : "Not yet run"}
        </span>
        {task.completed_at && (
          <span className="text-[11px] text-text-dim">
            {durationStr(task.run_at, task.completed_at)}
          </span>
        )}
      </div>
      {task.result && (
        <pre className="text-xs text-success font-mono whitespace-pre-wrap bg-input p-3 rounded-lg border border-surface-border max-h-72 overflow-auto m-0">
          {task.result}
        </pre>
      )}
      {task.error && (
        <pre className="text-xs text-danger font-mono whitespace-pre-wrap bg-danger/5 p-3 rounded-lg border border-danger/20 max-h-48 overflow-auto m-0">
          {task.error}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subscribed channels — per-channel enable/schedule for a pipeline definition
// ---------------------------------------------------------------------------

function SubscribedChannelsSection({ taskId }: { taskId: string }) {
  const { data, isLoading } = useTaskSubscriptions(taskId);
  const subs = data?.subscriptions ?? [];

  return (
    <Section title={`Subscribed channels (${subs.length})`}>
      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-text-dim">
          <Loader2 size={12} className="animate-spin" />
          Loading subscriptions…
        </div>
      ) : subs.length === 0 ? (
        <div className="text-xs text-text-dim">
          No channels are subscribed to this pipeline yet. Subscribe from a
          channel's Settings → Pipelines tab.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {subs.map((s) => (
            <TaskSubscriptionRow key={s.id} sub={s} />
          ))}
        </div>
      )}
    </Section>
  );
}

function TaskSubscriptionRow({ sub }: { sub: TaskSubscription }) {
  const update = useUpdateSubscription(sub.channel_id);
  const unsub = useUnsubscribePipeline(sub.channel_id);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const scheduleLabel = sub.schedule
    ? humanLabelFor(sub.schedule) ?? sub.schedule
    : "—";

  return (
    <div className="flex flex-row items-center gap-3 px-3 py-2 rounded-lg border border-surface-border bg-surface-raised/50">
      <Hash size={14} className="text-text-dim shrink-0" />
      <Link
        to={`/channels/${sub.channel_id}/settings#pipelines`}
        className="flex-1 min-w-0 text-[13px] font-semibold text-text hover:text-accent truncate"
      >
        {sub.channel.name ?? sub.channel_id}
      </Link>
      <button
        onClick={() => setScheduleOpen(true)}
        title="Edit schedule"
        className="flex flex-row items-center gap-1 px-2 py-1 text-[11px] font-mono border border-surface-border rounded-md bg-transparent text-text-muted hover:text-text"
      >
        <CalendarClock size={11} />
        <span>{scheduleLabel}</span>
      </button>
      <label className="flex items-center gap-1 text-[11px] text-text-muted cursor-pointer">
        <input
          type="checkbox"
          checked={sub.enabled}
          onChange={(e) =>
            update.mutate({
              subscriptionId: sub.id,
              patch: { enabled: e.target.checked },
            })
          }
        />
        {sub.enabled ? "On" : "Off"}
      </label>
      <button
        title="Unsubscribe"
        onClick={async () => {
          const ok = await confirm(
            `Unsubscribe ${sub.channel.name ?? "this channel"} from this pipeline?`,
            { title: "Unsubscribe", confirmLabel: "Unsubscribe", variant: "danger" },
          );
          if (!ok) return;
          unsub.mutate(sub.id);
        }}
        className="p-1 text-text-dim hover:text-danger bg-transparent border-none cursor-pointer"
      >
        <Trash2 size={12} />
      </button>
      {scheduleOpen && (
        <CronScheduleModal
          title={`Schedule for ${sub.channel.name ?? "channel"}`}
          initial={sub.schedule}
          onClose={() => setScheduleOpen(false)}
          onSave={async (expr) => {
            await update.mutateAsync({
              subscriptionId: sub.id,
              patch: expr === null ? { clear_schedule: true } : { schedule: expr },
            });
          }}
        />
      )}
      <ConfirmDialogSlot />
    </div>
  );
}
