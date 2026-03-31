import { RefreshCw } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { formatTime } from "@/src/utils/time";
import {
  type TaskItem, STATUS_CFG, displayTitle,
  TaskStatusBadge, TypeBadge, BotDot,
} from "./TaskConstants";

export interface TaskCardRowProps {
  task: TaskItem;
  onPress: () => void;
  isPast?: boolean;
  showBotDot?: boolean;
  showBotName?: boolean;
}

export function TaskCardRow({
  task, onPress, isPast = false,
  showBotDot = true, showBotName = true,
}: TaskCardRowProps) {
  const t = useThemeTokens();
  const s = STATUS_CFG[task.status] || STATUS_CFG.pending;
  const Icon = s.icon;
  const time = task.scheduled_at || task.created_at;
  const isCancelled = task.status === "cancelled";

  return (
    <div
      onClick={onPress}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = t.accent; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = t.surfaceRaised; }}
      style={{
        padding: "10px 14px", background: t.inputBg, borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`, cursor: "pointer", marginBottom: 2,
        opacity: isCancelled ? 0.35 : isPast ? 0.6 : 1,
        transition: "border-color 0.15s",
      }}
    >
      {/* Main row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Icon size={14} color={s.fg} style={{ flexShrink: 0 }} />
        {showBotDot && <BotDot botId={task.bot_id} />}
        <span style={{
          fontSize: 13, fontWeight: 600,
          color: isCancelled ? t.textDim : t.text,
          textDecoration: isCancelled ? "line-through" : "none",
          flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {displayTitle(task)}
        </span>
        <TaskStatusBadge status={task.status} />
        {showBotName && (
          <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>{task.bot_id}</span>
        )}
        {task.task_type && <TypeBadge type={task.task_type} />}
        {task.recurrence && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            background: isCancelled ? t.surfaceRaised : t.warningSubtle,
            color: isCancelled ? t.textDim : t.warning,
            padding: "1px 7px", borderRadius: 10, fontSize: 10, fontWeight: 700,
            flexShrink: 0,
          }}>
            <RefreshCw size={9} color={isCancelled ? t.textDim : t.warning} />
            {task.recurrence}
          </span>
        )}
        {task.run_count != null && task.run_count > 0 && task.is_schedule && (
          <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>{task.run_count} runs</span>
        )}
        <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>
          {time ? formatTime(time) : "\u2014"}
        </span>
      </div>
      {/* Error preview — separate line so it doesn't fight the badges */}
      {task.error && (
        <div style={{
          fontSize: 10, color: t.danger, marginTop: 4,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {task.error.substring(0, 120)}
        </div>
      )}
    </div>
  );
}
