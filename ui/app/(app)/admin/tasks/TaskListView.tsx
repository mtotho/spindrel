import { useMemo } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { type TaskItem } from "@/src/components/shared/TaskConstants";
import { TaskCardRow } from "@/src/components/shared/TaskCardRow";
import {
  type StatusFilter,
  startOfDay, getTaskTime, isToday, dateSectionLabel, passesStatusFilter,
} from "./taskUtils";

// ---------------------------------------------------------------------------
// List view — simplified with title + bot dot
// ---------------------------------------------------------------------------
export function TaskListView({ tasks, schedules, onTaskPress, statusFilter }: {
  tasks: TaskItem[];
  schedules: TaskItem[];
  onTaskPress: (tk: TaskItem) => void;
  statusFilter: StatusFilter;
}) {
  const t = useThemeTokens();
  const now = new Date();
  const allItems = useMemo(() => {
    const schedulesWithFlag = schedules
      .filter(s => passesStatusFilter(s, statusFilter))
      .map(s => ({ ...s, is_schedule: true }));
    const sortedTasks = [...tasks]
      .filter(tk => passesStatusFilter(tk, statusFilter))
      .sort((a, b) => {
        const ta = getTaskTime(a).getTime();
        const tb = getTaskTime(b).getTime();
        return tb - ta; // newest first
      });
    return [...schedulesWithFlag, ...sortedTasks];
  }, [tasks, schedules, statusFilter]);

  if (!allItems.length) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
        No tasks found.
      </div>
    );
  }

  // Group by date
  const byDate: Record<string, TaskItem[]> = {};
  // Schedules go in a special section
  const activeSchedules: TaskItem[] = [];
  for (const item of allItems) {
    if (item.is_schedule && (item.status === "active" || item.status === "cancelled")) {
      activeSchedules.push(item);
    } else {
      const d = startOfDay(getTaskTime(item)).toDateString();
      (byDate[d] ??= []).push(item);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0, padding: "0 16px 24px" }}>
      {/* Active schedules section */}
      {activeSchedules.length > 0 && (
        <>
          <div style={{ padding: "12px 0 6px", fontSize: 11, fontWeight: 700, color: t.warning, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Schedules
          </div>
          {activeSchedules.map((tk) => (
            <TaskCardRow
              key={tk.id}
              task={tk}
              onPress={() => onTaskPress(tk)}
            />
          ))}
        </>
      )}

      {/* Date sections */}
      {Object.entries(byDate).map(([dayStr, dayTasks]) => (
        <div key={dayStr}>
          <div style={{ padding: "12px 0 6px", fontSize: 11, fontWeight: 700, color: isToday(new Date(dayStr)) ? t.accent : t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
            {dateSectionLabel(new Date(dayStr))}
          </div>
          {dayTasks.map((tk) => (
            <TaskCardRow
              key={tk.id}
              task={tk}
              onPress={() => onTaskPress(tk)}
              isPast={getTaskTime(tk) < now && tk.status !== "running"}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
