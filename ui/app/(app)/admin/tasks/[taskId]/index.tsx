import { useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useTask, useTaskChildren, useRunTaskNow, type TaskDetail } from "@/src/api/hooks/useTasks";
import { useTaskFormState } from "@/src/components/shared/task/useTaskFormState";
import { ContentFields, ExecutionFields, TriggerFields } from "@/src/components/shared/task/TaskFormFields";
import { Trash2, Play, ExternalLink } from "lucide-react";
import { Section } from "@/src/components/shared/FormControls";
import {
  EnableToggle,
  InfoRow,
} from "@/src/components/shared/SchedulingPickers";
import { TaskStatusBadge, TypeBadge, BotDot } from "@/src/components/shared/TaskConstants";

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
  const [tab, setTab] = useState<Tab>("overview");
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

  const { data: children, isLoading: loadingChildren } = useTaskChildren(taskId);
  const task = form.existingTask;
  const isSchedule = !!(task?.recurrence);

  const handleDelete = useCallback(async () => {
    if (!taskId || !confirm("Delete this task?")) return;
    await form.handleDelete();
    navigate("/admin/tasks");
  }, [taskId, form, navigate]);

  const handleRunNow = useCallback(() => {
    if (taskId) runNowMut.mutate(taskId);
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
        backTo="/admin/tasks"
        title={task.title || task.prompt?.substring(0, 50) || "Task"}
        subtitle={`${task.bot_id} \u00b7 ${task.task_type || "task"}`}
        right={
          <div className="flex flex-row items-center gap-1.5 sm:gap-2">
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
            <EnableToggle
              enabled={form.status !== "cancelled"}
              onChange={(on) => {
                form.setStatus(on ? (isSchedule ? "active" : "pending") : "cancelled");
              }}
              compact
            />
            <button
              onClick={handleDelete}
              disabled={form.deleteMut.isPending}
              title="Delete"
              className="hidden sm:flex flex-row items-center gap-1 px-2.5 py-1.5 text-xs border border-danger/30 rounded-lg bg-transparent text-danger cursor-pointer hover:bg-danger/10 transition-colors"
            >
              <Trash2 size={13} />
            </button>
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
          </div>
        }
      />

      {/* Error display */}
      {form.error && (
        <div className="px-5 py-2 bg-danger/[0.08] text-danger text-xs">
          {form.error?.message || "An error occurred"}
        </div>
      )}

      {/* Tab bar */}
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

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {tab === "overview" ? (
          <OverviewTab form={form} task={task} />
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Tab — reuses shared form fields
// ---------------------------------------------------------------------------
function OverviewTab({ form, task }: { form: ReturnType<typeof useTaskFormState>; task: TaskDetail }) {
  return (
    <div className="flex flex-col gap-0 max-w-4xl">
      <div className="px-5 py-5 flex flex-col gap-4">
        <ContentFields form={form} promptRows={10} />
      </div>
      <div className="px-5 py-5 border-t border-surface-border flex flex-col gap-4">
        <ExecutionFields form={form} />
      </div>
      <div className="px-5 py-5 border-t border-surface-border flex flex-col gap-4">
        <TriggerFields form={form} />
      </div>

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
    </div>
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
  const navigate = useNavigate();
  const runs = children ?? [];
  // Show most recent first
  const sortedRuns = [...runs].sort((a, b) =>
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  // For one-shot tasks with no children, show own result
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
          {/* Table header */}
          <div className="flex flex-row items-center gap-3 px-5 py-2 text-[10px] font-semibold text-text-dim uppercase tracking-wider border-b border-surface-border bg-surface-raised/30">
            <div className="w-24 shrink-0">Status</div>
            <div className="w-36 shrink-0">Started</div>
            <div className="w-36 shrink-0">Completed</div>
            <div className="w-16 shrink-0 text-right">Duration</div>
            <div className="flex-1 min-w-0">Result</div>
            <div className="w-10 shrink-0" />
          </div>

          {/* Run rows */}
          {sortedRuns.map((run) => (
            <div
              key={run.id}
              className="flex flex-row items-center gap-3 px-5 py-2.5 border-b border-surface-border/50 hover:bg-surface-overlay/30 transition-colors"
            >
              <div className="w-24 shrink-0">
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
                  <span className="text-[11px] text-danger truncate block">{run.error.substring(0, 100)}</span>
                ) : run.result ? (
                  <span className="text-[11px] text-text-muted truncate block">{run.result.substring(0, 100)}</span>
                ) : run.status === "running" ? (
                  <span className="text-[11px] text-accent">Running...</span>
                ) : (
                  <span className="text-[11px] text-text-dim">\u2014</span>
                )}
              </div>
              <div className="w-10 shrink-0 flex flex-col justify-end">
                {run.correlation_id && (
                  <button
                    onClick={() => navigate(`/admin/logs/${run.correlation_id}`)}
                    title="View trace"
                    className="flex items-center justify-center w-7 h-7 rounded-md bg-transparent border-none cursor-pointer text-text-muted hover:text-accent hover:bg-accent/10 transition-colors"
                  >
                    <ExternalLink size={12} />
                  </button>
                )}
              </div>
            </div>
          ))}
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
