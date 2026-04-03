import { useState, useMemo, Fragment } from "react";
import { ChevronRight, ChevronDown, RefreshCw, AlertTriangle } from "lucide-react";
import { formatTime } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";
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
  const t = useThemeTokens();
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
      <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 0, padding: "0 0 24px" }}>
      {grouped.map(([botId, botTasks]) => {
        const c = botColor(botId);
        const isCollapsed = collapsedBots.has(botId);
        // Filter out schedule reference items (is_schedule && !is_virtual && status === "active") — they're shown as headers
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
            {/* Bot section header */}
            <div
              onClick={() => toggleBot(botId)}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "12px 20px",
                borderLeft: `3px solid ${c.border}`,
                background: c.bg,
                cursor: "pointer",
                userSelect: "none",
                position: "sticky", top: 0, zIndex: 2,
              }}
            >
              {isCollapsed ? <ChevronRight size={14} color={t.textDim} /> : <ChevronDown size={14} color={t.textDim} />}
              <BotDot botId={botId} size={10} />
              <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>
                {botName(botId)}
              </span>
              <span style={{ fontSize: 11, color: t.textDim }}>
                {displayTasks.length} task{displayTasks.length !== 1 ? "s" : ""}
                {scheduleCount > 0 && ` \u00b7 ${scheduleCount} schedule${scheduleCount !== 1 ? "s" : ""}`}
              </span>
              {cancelledCount > 0 && statusFilter === "all" && (
                <span style={{
                  fontSize: 10, fontWeight: 600, color: t.textDim,
                  background: t.surfaceRaised, padding: "1px 6px", borderRadius: 4,
                }}>
                  {cancelledCount} cancelled
                </span>
              )}
              {botConflicts && (
                <span style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  fontSize: 10, fontWeight: 700, color: t.warningMuted,
                  background: t.warningSubtle, padding: "2px 8px", borderRadius: 4,
                }}>
                  <AlertTriangle size={10} color={t.warningMuted} />
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
                <div style={{
                  padding: "6px 20px 6px 36px",
                  borderLeft: `3px solid ${c.border}`,
                  borderBottom: `1px solid ${t.surfaceRaised}`,
                }}>
                  <span style={{
                    fontSize: 11, fontWeight: 600,
                    color: isToday(new Date(dayStr)) ? t.accent : t.textDim,
                  }}>
                    {dateSectionLabel(new Date(dayStr))}
                  </span>
                </div>

                {/* Task cards */}
                {dayTasks.map((tk, idx) => {
                  const s = STATUS_CFG[tk.status] || STATUS_CFG.pending;
                  const Icon = s.icon;
                  const time = tk.scheduled_at || tk.created_at;
                  const isPast = getTaskTime(tk) < now && tk.status !== "running" && tk.status !== "active";
                  const isVirtual = tk.is_virtual;
                  const isCancelled = tk.status === "cancelled";
                  const pastBg = isPast && !isCancelled ? "rgba(107,114,128,0.04)" : "transparent";

                  // Show NOW divider between past and future items on today
                  const prevTask = idx > 0 ? dayTasks[idx - 1] : null;
                  const prevIsPast = prevTask
                    ? (getTaskTime(prevTask) < now && prevTask.status !== "running" && prevTask.status !== "active")
                    : false;
                  const showNowDivider = isToday(new Date(dayStr)) && !isPast && !isCancelled && prevIsPast;

                  return (
                    <Fragment key={tk.id}>
                      {showNowDivider && (
                        <div style={{
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "6px 20px 6px 36px",
                          borderLeft: `3px solid ${c.border}`,
                        }}>
                          <div style={{ width: 8, height: 8, borderRadius: 4, background: t.danger }} />
                          <div style={{ flex: 1, height: 1, background: t.danger }} />
                          <span style={{ fontSize: 9, fontWeight: 700, color: t.danger, textTransform: "uppercase", letterSpacing: 1 }}>NOW</span>
                          <div style={{ flex: 1, height: 1, background: t.danger }} />
                        </div>
                      )}
                      <div
                        onClick={() => onTaskPress(tk)}
                        style={{
                          display: "flex", alignItems: "center", gap: 10,
                          padding: "10px 20px 10px 36px",
                          borderLeft: `3px solid ${isCancelled ? t.surfaceBorder : c.border}`,
                          borderBottom: `1px solid ${t.surfaceRaised}`,
                          cursor: "pointer",
                          opacity: isCancelled ? 0.35 : isVirtual ? 0.5 : isPast ? 0.35 : 1,
                          background: pastBg,
                          transition: "background 0.1s, opacity 0.1s",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = t.surfaceOverlay; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = pastBg; }}
                      >
                        <Icon size={14} color={s.fg} style={{ flexShrink: 0 }} />

                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{
                            fontSize: 13, fontWeight: 600,
                            color: isCancelled ? t.textDim : t.text,
                            textDecoration: isCancelled ? "line-through" : "none",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}>
                            {displayTitle(tk)}
                          </div>
                        </div>

                        <StatusBadge status={tk.status} />

                        {tk.recurrence && (
                          <span style={{
                            display: "inline-flex", alignItems: "center", gap: 3,
                            background: isCancelled ? t.surfaceRaised : t.warningSubtle,
                            color: isCancelled ? t.textDim : t.warning,
                            padding: "1px 7px", borderRadius: 10, fontSize: 10, fontWeight: 700,
                            flexShrink: 0,
                          }}>
                            <RefreshCw size={9} color={isCancelled ? t.textDim : t.warning} />
                            {tk.recurrence}
                          </span>
                        )}

                        <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0, minWidth: 90, textAlign: "right" }}>
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
                  <div style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "6px 20px 6px 36px",
                    borderLeft: `3px solid ${c.border}`,
                  }}>
                    <div style={{ width: 8, height: 8, borderRadius: 4, background: t.danger }} />
                    <div style={{ flex: 1, height: 1, background: t.danger }} />
                    <span style={{ fontSize: 9, fontWeight: 700, color: t.danger, textTransform: "uppercase", letterSpacing: 1 }}>NOW</span>
                    <div style={{ flex: 1, height: 1, background: t.danger }} />
                  </div>
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
