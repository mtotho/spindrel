import { RefreshCw, FileText } from "lucide-react";
import { useRouter } from "expo-router";
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
  const router = useRouter();
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
        {task.workflow_run_id && (
          <span style={{
            display: "inline-block", fontFamily: "monospace",
            background: t.codeBg, border: `1px solid ${t.codeBorder}`,
            color: t.textDim, padding: "1px 5px", borderRadius: 3,
            fontSize: 9, flexShrink: 0,
          }}>
            run:{task.workflow_run_id.slice(0, 6)}
          </span>
        )}
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
        {task.correlation_id && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/admin/logs/${task.correlation_id}`);
            }}
            title="View trace"
            style={{
              display: "inline-flex", alignItems: "center", padding: "2px 6px",
              background: "transparent", border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4, cursor: "pointer", flexShrink: 0,
              color: t.textMuted,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = t.accent; e.currentTarget.style.color = t.accent; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = t.surfaceBorder; e.currentTarget.style.color = t.textMuted; }}
          >
            <FileText size={11} />
          </button>
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
