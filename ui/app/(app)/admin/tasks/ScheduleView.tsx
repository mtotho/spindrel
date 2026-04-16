import { useState, useMemo, Fragment } from "react";
import { ChevronRight, ChevronDown, RefreshCw, AlertTriangle } from "lucide-react";
import { formatTime } from "@/src/utils/time";
import {
  type TaskItem, STATUS_CFG,
  botColor, displayTitle, TaskStatusBadge as StatusBadge, BotDot,
} from "@/src/components/shared/TaskConstants";
import { ConflictBanner } from "./TaskTimelineComponents";
import {
  type StatusFilter,
  parseRecurrenceMs, startOfDay, addDays, getTaskTime,
  isToday, dateSectionLabel, passesStatusFilter,
} from "./taskUtils";

// ---------------------------------------------------------------------------
// Schedule view — grouped by bot, with date sub-headers
// ---------------------------------------------------------------------------
export function ScheduleView({ tasks, schedules, onTaskPress, bots, statusFilter, conflicts }: {
  tasks: TaskItem[];
  schedules: TaskItem[];
  onTaskPress: (t: TaskItem) => void;
  bots: any[] | undefined;
  statusFilter: StatusFilter;
  conflicts: Map<string, string[]>;
}) {
  const [collapsedBots, setCollapsedBots] = useState<Set<string>>(new Set());
  const now = new Date();

  // Merge schedules + concrete tasks, generate virtual occurrences for next 14 days
  const allItems = useMemo(() => {
    const SIX_HOURS = 6 * 60 * 60 * 1000;
    const pastCutoff = new Date(now.getTime() - SIX_HOURS);
    const items: TaskItem[] = [...tasks.filter(t =>
      passesStatusFilter(t, statusFilter) &&
      (getTaskTime(t) >= pastCutoff || t.status === "running" || t.status === "active")
    )];

    // Build set of (schedule_id, day) for concrete tasks
    const concreteByScheduleDay = new Set<string>();
    for (const t of tasks) {
      if (t.parent_task_id) {
        const d = startOfDay(getTaskTime(t)).toDateString();
        concreteByScheduleDay.add(`${t.parent_task_id}:${d}`);
      }
    }

    // Expand schedules into virtual entries for the next 14 days
    const rangeEnd = addDays(now, 14).getTime();
    const rangeStart = pastCutoff.getTime();

    for (const sched of schedules) {
      if (!passesStatusFilter(sched, statusFilter)) continue;

      // Add the schedule itself as a reference item
      items.push({ ...sched, is_schedule: true });

      if (!sched.recurrence || !sched.scheduled_at || sched.status === "cancelled") continue;
      const intervalMs = parseRecurrenceMs(sched.recurrence);
      if (!intervalMs) continue;

      const schedStart = new Date(sched.scheduled_at).getTime();
      let t = schedStart;
      if (t < rangeStart) {
        const steps = Math.floor((rangeStart - t) / intervalMs);
        t += steps * intervalMs;
      }
      if (t > rangeStart) {
        const prevT = t - intervalMs;
        if (prevT >= rangeStart) t = prevT;
      }

      let count = 0;
      while (t < rangeEnd && count < 100) {
        if (t >= rangeStart) {
          const occDate = new Date(t);
          const dayStr = startOfDay(occDate).toDateString();
          const key = `${sched.id}:${dayStr}`;
          if (!concreteByScheduleDay.has(key)) {
            items.push({
              ...sched,
              id: `virtual-${sched.id}-${t}`,
              status: "upcoming",
              scheduled_at: occDate.toISOString(),
              is_schedule: true,
              is_virtual: true,
              _schedule_id: sched.id,
              result: undefined,
              error: undefined,
            });
          }
        }
        t += intervalMs;
        count++;
      }
    }

    return items;
  }, [tasks, schedules, now, statusFilter]);

  // Group by bot_id
  const grouped = useMemo(() => {
    const map: Record<string, TaskItem[]> = {};
    for (const t of allItems) {
      (map[t.bot_id] ??= []).push(t);
    }
    // Sort each bot's tasks chronologically
    for (const key of Object.keys(map)) {
      map[key].sort((a, b) => getTaskTime(a).getTime() - getTaskTime(b).getTime());
    }
    // Sort bots by earliest upcoming task
    return Object.entries(map).sort(([, a], [, b]) => {
      const aNext = a.find(t => t.status !== "complete" && t.status !== "failed");
      const bNext = b.find(t => t.status !== "complete" && t.status !== "failed");
      if (!aNext && !bNext) return 0;
      if (!aNext) return 1;
      if (!bNext) return -1;
      return getTaskTime(aNext).getTime() - getTaskTime(bNext).getTime();
    });
  }, [allItems]);

  if (!grouped.length) {
    return (
      <div className="p-10 text-center text-text-dim text-[13px]">
        No tasks found.
      </div>
    );
  }

  const toggleBot = (botId: string) => {
    setCollapsedBots(prev => {
      const next = new Set(prev);
      if (next.has(botId)) next.delete(botId); else next.add(botId);
      return next;
    });
  };

  const botName = (botId: string) => {
    const b = bots?.find((x: any) => x.id === botId);
    return b?.name || botId;
  };

  return (
    <div className="flex flex-col pb-6">
      {grouped.map(([botId, botTasks]) => {
        const c = botColor(botId);
        const isCollapsed = collapsedBots.has(botId);
        const displayTasks = botTasks.filter(t => !(t.is_schedule && !t.is_virtual && t.status === "active"));
        const scheduleCount = botTasks.filter(t => t.is_schedule && !t.is_virtual && (t.status === "active" || t.status === "cancelled")).length;
        const cancelledCount = botTasks.filter(t => t.status === "cancelled").length;
        const botConflicts = conflicts.get(botId);

        // Group tasks by date
        const byDate: Record<string, TaskItem[]> = {};
        for (const t of displayTasks) {
          const d = startOfDay(getTaskTime(t)).toDateString();
          (byDate[d] ??= []).push(t);
        }

        return (
          <div key={botId}>
            {/* Bot section header — border-left and bg are runtime bot colors */}
            <div
              onClick={() => toggleBot(botId)}
              className="flex flex-row items-center gap-2.5 px-5 py-3 cursor-pointer select-none sticky top-0 z-[2]"
              style={{ borderLeft: `3px solid ${c.border}`, background: c.bg }}
            >
              {isCollapsed
                ? <ChevronRight size={14} className="text-text-dim" />
                : <ChevronDown size={14} className="text-text-dim" />
              }
              <BotDot botId={botId} size={10} />
              <span className="text-[13px] font-bold text-text">
                {botName(botId)}
              </span>
              <span className="text-[11px] text-text-dim">
                {displayTasks.length} task{displayTasks.length !== 1 ? "s" : ""}
                {scheduleCount > 0 && ` \u00b7 ${scheduleCount} schedule${scheduleCount !== 1 ? "s" : ""}`}
              </span>
              {cancelledCount > 0 && statusFilter === "all" && (
                <span className="text-[10px] font-semibold text-text-dim bg-surface-raised px-1.5 rounded">
                  {cancelledCount} cancelled
                </span>
              )}
              {botConflicts && (
                <span className="inline-flex flex-row items-center gap-1 text-[10px] font-bold text-warning-muted bg-warning/[0.08] px-2 py-0.5 rounded">
                  <AlertTriangle size={10} className="text-warning-muted" />
                  Overlap
                </span>
              )}
            </div>

            {/* Conflict warning */}
            {!isCollapsed && botConflicts && (
              <ConflictBanner warnings={botConflicts} />
            )}

            {/* Tasks grouped by date */}
            {!isCollapsed && Object.entries(byDate).map(([dayStr, dayTasks]) => (
              <div key={dayStr}>
                {/* Date sub-header */}
                <div
                  className="py-1.5 px-5 pl-9 border-b border-surface-raised"
                  style={{ borderLeft: `3px solid ${c.border}` }}
                >
                  <span className={`text-[11px] font-semibold ${isToday(new Date(dayStr)) ? "text-accent" : "text-text-dim"}`}>
                    {dateSectionLabel(new Date(dayStr))}
                  </span>
                </div>

                {/* Task rows */}
                {dayTasks.map((tk, idx) => {
                  const s = STATUS_CFG[tk.status] || STATUS_CFG.pending;
                  const Icon = s.icon;
                  const time = tk.scheduled_at || tk.created_at;
                  const isPast = getTaskTime(tk) < now && tk.status !== "running" && tk.status !== "active";
                  const isVirtual = tk.is_virtual;
                  const isCancelled = tk.status === "cancelled";

                  // Show NOW divider between past and future items on today
                  const prevTask = idx > 0 ? dayTasks[idx - 1] : null;
                  const prevIsPast = prevTask
                    ? (getTaskTime(prevTask) < now && prevTask.status !== "running" && prevTask.status !== "active")
                    : false;
                  const showNowDivider = isToday(new Date(dayStr)) && !isPast && !isCancelled && prevIsPast;

                  const opacityClass = isCancelled ? "opacity-35" : isVirtual ? "opacity-50" : isPast ? "opacity-35" : "";
                  const bgClass = isPast && !isCancelled ? "bg-gray-500/[0.04]" : "";

                  return (
                    <Fragment key={tk.id}>
                      {showNowDivider && (
                        <NowDivider borderColor={c.border} />
                      )}
                      <div
                        onClick={() => onTaskPress(tk)}
                        className={`flex flex-row items-center gap-2.5 py-2.5 px-5 pl-9 border-b border-surface-raised cursor-pointer transition-colors duration-100 hover:bg-surface-overlay ${opacityClass} ${bgClass}`}
                        style={{ borderLeft: `3px solid ${isCancelled ? "var(--color-surface-border, #333)" : c.border}` }}
                      >
                        <Icon size={14} color={s.fg} className="shrink-0" />

                        <div className="flex-1 min-w-0">
                          <div className={`text-[13px] font-semibold overflow-hidden text-ellipsis whitespace-nowrap ${isCancelled ? "text-text-dim line-through" : "text-text"}`}>
                            {displayTitle(tk)}
                          </div>
                        </div>

                        <StatusBadge status={tk.status} />

                        {tk.recurrence && (
                          <span className={`inline-flex flex-row items-center gap-[3px] px-[7px] rounded-[10px] text-[10px] font-bold shrink-0 ${
                            isCancelled
                              ? "bg-surface-raised text-text-dim"
                              : "bg-warning/[0.08] text-warning"
                          }`}>
                            <RefreshCw size={9} className={isCancelled ? "text-text-dim" : "text-warning"} />
                            {tk.recurrence}
                          </span>
                        )}

                        <span className="text-[10px] text-text-dim shrink-0 min-w-[90px] text-right">
                          {time ? formatTime(time) : "\u2014"}
                        </span>
                      </div>
                    </Fragment>
                  );
                })}
                {/* Trailing NOW line when all of today's items are past */}
                {isToday(new Date(dayStr)) && dayTasks.length > 0 && dayTasks.every(tk =>
                  getTaskTime(tk) < now && tk.status !== "running" && tk.status !== "active"
                ) && (
                  <NowDivider borderColor={c.border} />
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// NOW divider — extracted to avoid duplication
// ---------------------------------------------------------------------------
function NowDivider({ borderColor }: { borderColor: string }) {
  return (
    <div
      className="flex flex-row items-center gap-2 py-1.5 px-5 pl-9"
      style={{ borderLeft: `3px solid ${borderColor}` }}
    >
      <div className="w-2 h-2 rounded-full bg-danger" />
      <div className="flex-1 h-px bg-danger" />
      <span className="text-[9px] font-bold text-danger uppercase tracking-widest">NOW</span>
      <div className="flex-1 h-px bg-danger" />
    </div>
  );
}
