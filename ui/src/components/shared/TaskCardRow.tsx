import { RefreshCw, FileText } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { formatTime } from "@/src/utils/time";
import {
  type TaskItem, STATUS_CFG, displayTitle,
  TaskStatusBadge, TypeBadge, BotDot,
} from "./TaskConstants";

export interface TaskCardRowProps {
  task: TaskItem;
  onClick: () => void;
  isPast?: boolean;
  showBotDot?: boolean;
  showBotName?: boolean;
}

export function TaskCardRow({
  task, onClick, isPast = false,
  showBotDot = true, showBotName = true,
}: TaskCardRowProps) {
  const navigate = useNavigate();
  const s = STATUS_CFG[task.status] || STATUS_CFG.pending;
  const Icon = s.icon;
  const time = task.scheduled_at || task.created_at;
  const isCancelled = task.status === "cancelled";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      className={
        `w-full rounded-md bg-surface-raised/40 px-3 py-2.5 text-left transition-colors ` +
        `cursor-pointer ` +
        `hover:bg-surface-overlay/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 ` +
        (isCancelled ? "opacity-35 " : isPast ? "opacity-60 " : "")
      }
    >
      {/* Main row */}
      <div className="flex min-w-0 flex-row items-center gap-2.5">
        <Icon size={14} className={`shrink-0 ${s.iconClass}`} />
        {showBotDot && <BotDot botId={task.bot_id} />}
        <span
          className={
            `min-w-0 flex-1 truncate text-[13px] font-semibold ` +
            (isCancelled ? "text-text-dim line-through" : "text-text")
          }
        >
          {displayTitle(task)}
        </span>
        <TaskStatusBadge status={task.status} />
        {showBotName && (
          <span className="shrink-0 text-[10px] text-text-dim">{task.bot_id}</span>
        )}
        {task.task_type && <TypeBadge type={task.task_type} />}
        {task.workflow_run_id && (
          <span className="inline-block shrink-0 rounded-sm bg-surface-overlay px-1.5 py-px font-mono text-[9px] text-text-dim">
            run:{task.workflow_run_id.slice(0, 6)}
          </span>
        )}
        {task.recurrence && (
          <span
            className={
              `inline-flex shrink-0 flex-row items-center gap-1 rounded-full px-2 py-px text-[10px] font-semibold ` +
              (isCancelled ? "bg-surface-overlay text-text-dim" : "bg-warning/10 text-warning-muted")
            }
          >
            <RefreshCw size={9} />
            {task.recurrence}
          </span>
        )}
        {task.run_count != null && task.run_count > 0 && task.is_schedule && (
          <span className="shrink-0 text-[10px] text-text-dim">{task.run_count} runs</span>
        )}
        {task.correlation_id && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/admin/logs/${task.correlation_id}`);
            }}
            title="View trace"
            className="inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-text-dim transition-colors hover:bg-surface-overlay/60 hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35"
          >
            <FileText size={11} />
          </button>
        )}
        <span className="shrink-0 text-[11px] text-text-dim">
          {time ? formatTime(time) : "\u2014"}
        </span>
      </div>
      {/* Error preview — separate line so it doesn't fight the badges */}
      {task.error && (
        <div className="mt-1 truncate text-[10px] text-danger">
          {task.error.substring(0, 120)}
        </div>
      )}
    </div>
  );
}
