import { useMemo } from "react";
import { Play, MoreVertical, RefreshCw, Zap, Calendar } from "lucide-react";
import {
  type TaskItem, displayTitle,
  TaskStatusBadge, TypeBadge, BotDot, botColor, STATUS_CFG,
} from "@/src/components/shared/TaskConstants";

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function triggerLabel(task: TaskItem): string {
  if (task.recurrence) return task.recurrence;
  const tc = task.trigger_config;
  if (tc?.type === "event") {
    const src = tc.event_source || "event";
    return `event: ${src}`;
  }
  return "manual";
}

interface Props {
  tasks: TaskItem[];
  schedules: TaskItem[];
  onTaskPress: (task: TaskItem) => void;
  onRunNow: (taskId: string) => void;
  runningTaskId?: string | null;
}

export function TaskDefinitionsView({ tasks, schedules, onTaskPress, onRunNow, runningTaskId }: Props) {
  const definitions = useMemo(() => {
    // Schedules are always definitions
    const defs: TaskItem[] = schedules.map(s => ({ ...s, is_schedule: true }));

    // Top-level non-schedule tasks (one-shots, pipelines without recurrence)
    // Filter out internal types that aren't user-created
    const internalTypes = new Set(["delegation", "callback", "memory_hygiene", "skill_review", "heartbeat"]);
    for (const t of tasks) {
      if (!t.parent_task_id && !internalTypes.has(t.task_type || "")) {
        defs.push(t);
      }
    }

    // Sort: active first, then by most recent activity
    defs.sort((a, b) => {
      const aActive = a.status === "active" ? 0 : a.status === "pending" ? 1 : 2;
      const bActive = b.status === "active" ? 0 : b.status === "pending" ? 1 : 2;
      if (aActive !== bActive) return aActive - bActive;
      const aTime = new Date(a.scheduled_at || a.created_at || 0).getTime();
      const bTime = new Date(b.scheduled_at || b.created_at || 0).getTime();
      return bTime - aTime;
    });

    return defs;
  }, [tasks, schedules]);

  if (!definitions.length) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-text-dim text-sm">
        No task definitions yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col px-4 pb-6">
      {/* Table header */}
      <div className="flex flex-row items-center gap-3 px-3.5 py-2 text-[10px] font-semibold text-text-dim uppercase tracking-wider border-b border-surface-border">
        <div className="w-5" /> {/* status dot */}
        <div className="flex-1 min-w-0">Name</div>
        <div className="w-24 shrink-0">Bot</div>
        <div className="w-16 shrink-0 text-center">Type</div>
        <div className="w-20 shrink-0 text-center">Trigger</div>
        <div className="w-32 shrink-0">Last Run</div>
        <div className="w-16 shrink-0 text-right">Runs</div>
        <div className="w-20 shrink-0" /> {/* actions */}
      </div>

      {/* Rows */}
      {definitions.map((def) => (
        <DefinitionRow
          key={def.id}
          def={def}
          onPress={() => onTaskPress(def)}
          onRunNow={() => onRunNow(def.id)}
          isRunning={runningTaskId === def.id}
        />
      ))}
    </div>
  );
}

function DefinitionRow({ def, onPress, onRunNow, isRunning }: {
  def: TaskItem;
  onPress: () => void;
  onRunNow: () => void;
  isRunning: boolean;
}) {
  const isCancelled = def.status === "cancelled";
  const statusCfg = STATUS_CFG[def.status] || STATUS_CFG.pending;
  const lastRunTime = def.completed_at || def.run_at;
  const bc = botColor(def.bot_id);

  // For schedules, show the last run status from the definition's own fields
  // (the API doesn't include child info in the list, but completed_at/run_at indicate last execution)
  const hasRun = !!(def.run_count && def.run_count > 0);

  return (
    <div
      onClick={onPress}
      className={`flex flex-row items-center gap-3 px-3.5 py-2.5 cursor-pointer border-b border-surface-border/50 transition-colors duration-100 hover:bg-surface-overlay/40 ${
        isCancelled ? "opacity-40" : ""
      }`}
    >
      {/* Status dot */}
      <div className="w-5 flex items-center justify-center shrink-0">
        <div
          className="w-2.5 h-2.5 rounded-full"
          style={{ background: statusCfg.fg }}
          title={statusCfg.label}
        />
      </div>

      {/* Name */}
      <div className="flex-1 min-w-0">
        <span className={`text-[13px] font-semibold truncate block ${
          isCancelled ? "text-text-dim line-through" : "text-text"
        }`}>
          {displayTitle(def)}
        </span>
      </div>

      {/* Bot */}
      <div className="w-24 shrink-0 flex flex-row items-center gap-1.5">
        <BotDot botId={def.bot_id} />
        <span className="text-[11px] text-text-muted truncate">{def.bot_id}</span>
      </div>

      {/* Type */}
      <div className="w-16 shrink-0 flex justify-center">
        {def.task_type && <TypeBadge type={def.task_type} />}
      </div>

      {/* Trigger */}
      <div className="w-20 shrink-0 flex justify-center">
        <span className={`inline-flex flex-row items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${
          def.recurrence
            ? "bg-warning/10 text-warning"
            : "bg-surface-overlay text-text-dim"
        }`}>
          {def.recurrence ? <RefreshCw size={9} /> : def.trigger_config?.type === "event" ? <Zap size={9} /> : <Calendar size={9} />}
          {triggerLabel(def)}
        </span>
      </div>

      {/* Last Run */}
      <div className="w-32 shrink-0 flex flex-row items-center gap-1.5">
        {hasRun && lastRunTime ? (
          <>
            <TaskStatusBadge status={def.status === "active" ? "complete" : def.status} />
            <span className="text-[10px] text-text-dim">{relativeTime(lastRunTime)}</span>
          </>
        ) : hasRun ? (
          <span className="text-[10px] text-text-dim">{def.run_count} runs</span>
        ) : (
          <span className="text-[10px] text-text-dim">never</span>
        )}
      </div>

      {/* Run count */}
      <div className="w-16 shrink-0 text-right">
        <span className="text-[11px] text-text-muted font-mono">
          {def.run_count ?? 0}
        </span>
      </div>

      {/* Actions */}
      <div className="w-20 shrink-0 flex flex-row items-center justify-end gap-1">
        <button
          onClick={(e) => { e.stopPropagation(); onRunNow(); }}
          disabled={isRunning}
          title="Run now"
          className={`flex items-center justify-center w-7 h-7 rounded-md border-none cursor-pointer transition-colors ${
            isRunning
              ? "bg-accent/20 text-accent animate-pulse"
              : "bg-transparent text-text-muted hover:bg-accent/10 hover:text-accent"
          }`}
        >
          <Play size={13} fill="currentColor" />
        </button>
      </div>
    </div>
  );
}
