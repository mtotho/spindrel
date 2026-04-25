import { useMemo } from "react";
import { type TaskItem } from "@/src/components/shared/TaskConstants";
import { TaskCardRow } from "@/src/components/shared/TaskCardRow";
import {
  type StatusFilter,
  startOfDay, getTaskTime, isToday, dateSectionLabel, passesStatusFilter,
  parseRecurrenceMs,
} from "./taskUtils";

// ---------------------------------------------------------------------------
// List view — Upcoming on top, Previous (completed/past) below a divider
// ---------------------------------------------------------------------------
export function TaskListView({ tasks, schedules, upcomingVirtual = [], onTaskPress, statusFilter }: {
  tasks: TaskItem[];
  schedules: TaskItem[];
  upcomingVirtual?: TaskItem[];
  onTaskPress: (tk: TaskItem) => void;
  statusFilter: StatusFilter;
}) {
  const now = new Date();
  const nowMs = now.getTime();

  // Partition concrete tasks into upcoming (future-scheduled, pending/active) and past
  const { pastTasks, upcomingTasks } = useMemo(() => {
    const past: TaskItem[] = [];
    const up: TaskItem[] = [];
    for (const tk of tasks) {
      if (!passesStatusFilter(tk, statusFilter)) continue;
      const tMs = getTaskTime(tk).getTime();
      const isFuture =
        tMs > nowMs && (tk.status === "pending" || tk.status === "active" || tk.status === "upcoming");
      if (isFuture) up.push(tk);
      else past.push(tk);
    }
    return { pastTasks: past, upcomingTasks: up };
  }, [tasks, statusFilter, nowMs]);

  // Expand recurring schedule templates into their next fire time → virtual upcoming rows
  const scheduleNextRuns = useMemo<TaskItem[]>(() => {
    const rows: TaskItem[] = [];
    for (const sched of schedules) {
      if (!passesStatusFilter(sched, statusFilter)) continue;
      if (sched.status !== "active" || !sched.recurrence || !sched.scheduled_at) continue;
      const intervalMs = parseRecurrenceMs(sched.recurrence);
      if (!intervalMs) continue;
      let next = new Date(sched.scheduled_at).getTime();
      if (next < nowMs) {
        const steps = Math.ceil((nowMs - next) / intervalMs);
        next += steps * intervalMs;
      }
      rows.push({
        ...sched,
        id: `virtual-sched-${sched.id}-${next}`,
        status: "upcoming",
        scheduled_at: new Date(next).toISOString(),
        is_schedule: true,
        is_virtual: true,
        _schedule_id: sched.id,
        result: undefined,
        error: undefined,
      });
    }
    return rows;
  }, [schedules, statusFilter, nowMs]);

  // Schedules that never fire (no recurrence + status active) — shown as a defn bucket
  const oneShotActiveSchedules = useMemo<TaskItem[]>(() => {
    return schedules.filter((s) => {
      if (!passesStatusFilter(s, statusFilter)) return false;
      if (s.status !== "active") return false;
      if (s.recurrence) return false;
      return true;
    });
  }, [schedules, statusFilter]);

  // Merge all upcoming + sort ascending
  const allUpcoming = useMemo(() => {
    const merged = [...upcomingTasks, ...scheduleNextRuns, ...upcomingVirtual, ...oneShotActiveSchedules];
    merged.sort((a, b) => getTaskTime(a).getTime() - getTaskTime(b).getTime());
    return merged;
  }, [upcomingTasks, scheduleNextRuns, upcomingVirtual, oneShotActiveSchedules]);

  // Group upcoming by day
  const upcomingByDate: Record<string, TaskItem[]> = {};
  for (const tk of allUpcoming) {
    const d = startOfDay(getTaskTime(tk)).toDateString();
    (upcomingByDate[d] ??= []).push(tk);
  }

  // Group past by day, newest first
  const pastSorted = [...pastTasks].sort(
    (a, b) => getTaskTime(b).getTime() - getTaskTime(a).getTime(),
  );
  const pastByDate: Record<string, TaskItem[]> = {};
  for (const tk of pastSorted) {
    const d = startOfDay(getTaskTime(tk)).toDateString();
    (pastByDate[d] ??= []).push(tk);
  }

  const hasUpcoming = allUpcoming.length > 0;
  const hasPast = pastSorted.length > 0;

  if (!hasUpcoming && !hasPast) {
    return (
      <div className="px-4 py-10 text-center text-[13px] text-text-dim">
        No tasks found.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 px-4 pb-6">
      {/* ── Upcoming ── */}
      {hasUpcoming ? (
        <>
          <div className="pt-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-accent">
            Upcoming
          </div>
          {Object.entries(upcomingByDate).map(([dayStr, dayTasks]) => (
            <div key={`up-${dayStr}`} className="flex flex-col gap-2">
              <div className={`text-[10px] font-semibold uppercase tracking-[0.08em] ${isToday(new Date(dayStr)) ? "text-accent" : "text-text-dim/70"}`}>
                {dateSectionLabel(new Date(dayStr))}
              </div>
              {dayTasks.map((tk) => (
                <TaskCardRow key={tk.id} task={tk} onClick={() => onTaskPress(tk)} />
              ))}
            </div>
          ))}
        </>
      ) : (
        <div className="px-4 py-6 text-center text-[12px] text-text-dim">
          Nothing upcoming.
        </div>
      )}

      {/* ── Fray divider + Previous runs ── */}
      {hasPast && (
        <>
          <div className="mt-4 flex flex-row items-center gap-3 text-text-dim/70">
            <div className="h-px flex-1 bg-surface-border/60" />
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em]">
              Previous runs
            </span>
            <div className="h-px flex-1 bg-surface-border/60" />
          </div>

          <div className="flex flex-col gap-2 opacity-85">
            {Object.entries(pastByDate).map(([dayStr, dayTasks]) => (
              <div key={`past-${dayStr}`} className="flex flex-col gap-2">
                <div className={`text-[10px] font-semibold uppercase tracking-[0.08em] ${isToday(new Date(dayStr)) ? "text-accent" : "text-text-dim/70"}`}>
                  {dateSectionLabel(new Date(dayStr))}
                </div>
                {dayTasks.map((tk) => (
                  <TaskCardRow
                    key={tk.id}
                    task={tk}
                    onClick={() => onTaskPress(tk)}
                    isPast={getTaskTime(tk) < now && tk.status !== "running"}
                  />
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
