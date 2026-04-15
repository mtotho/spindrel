import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, Plus, Calendar, CalendarDays, CalendarRange, List, Terminal,
} from "lucide-react";
import { AlertCircle } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useBots } from "@/src/api/hooks/useBots";
import { TaskEditor } from "@/src/components/shared/TaskEditor";
import { TaskCreateModal } from "@/src/components/shared/TaskCreateModal";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { formatDate } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";
import type { TaskItem, TasksResponse } from "@/src/components/shared/TaskConstants";
import { CronJobsView } from "./CronJobsView";
import { DayColumn, MobileWeekSummary } from "./TaskTimelineComponents";
import { ScheduleView } from "./ScheduleView";
import { TaskListView } from "./TaskListView";
import { TaskFilters } from "./TaskFilters";
import {
  type ViewMode, type TaskTypeFilter, type StatusFilter, type EditorState,
  addDays, startOfDay, getTaskTime, passesStatusFilter, parseRecurrenceMs,
  detectScheduleConflicts, detectInvalidSchedules,
} from "./taskUtils";

// ---------------------------------------------------------------------------
// Main Tasks screen
// ---------------------------------------------------------------------------
export default function TasksScreen() {
  const t = useThemeTokens();
  const [viewMode, setViewMode] = useState<ViewMode>("day");
  const [baseDate, setBaseDate] = useState(() => startOfDay(new Date()));
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>("scheduled");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [botFilter, setBotFilter] = useState<string>("");
  const [editorState, setEditorState] = useState<EditorState>({ mode: "closed" });
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { refreshing, onRefresh } = usePageRefresh();
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const { data: bots } = useBots();

  const isCalendar = viewMode === "day" || viewMode === "week";
  const rangeDays = viewMode === "day" ? 1 : viewMode === "week" ? 7 : 1;
  const rangeStart = baseDate;
  const rangeEnd = addDays(baseDate, rangeDays);

  const typeParam = typeFilter !== "all" ? `&task_type=${typeFilter}` : "";
  const botParam = botFilter ? `&bot_id=${botFilter}` : "";
  const dateParams = isCalendar
    ? `&after=${rangeStart.toISOString()}&before=${rangeEnd.toISOString()}`
    : "";

  const { data, isLoading } = useQuery({
    queryKey: ["admin-tasks-timeline", viewMode, rangeStart.toISOString(), rangeEnd.toISOString(), typeFilter, botFilter],
    queryFn: () => apiFetch<TasksResponse>(
      `/api/v1/admin/tasks?limit=200${dateParams}${typeParam}${botParam}`
    ),
  });

  // Compute schedule conflicts from schedule data
  const scheduleConflicts = useMemo(() => {
    return detectScheduleConflicts(data?.schedules ?? []);
  }, [data?.schedules]);

  // Detect schedules with invalid recurrence values
  const invalidSchedules = useMemo(() => {
    return detectInvalidSchedules(data?.schedules ?? []);
  }, [data?.schedules]);

  const tasksByDay = useMemo(() => {
    if (!isCalendar) return {};
    const map: Record<string, TaskItem[]> = {};
    for (let i = 0; i < rangeDays; i++) {
      const d = addDays(baseDate, i);
      map[d.toDateString()] = [];
    }
    const filteredTasks = (data?.tasks ?? []).filter(t => passesStatusFilter(t, statusFilter));
    for (const t of filteredTasks) {
      const d = startOfDay(getTaskTime(t)).toDateString();
      (map[d] ??= []).push(t);
    }

    const concreteByScheduleDay = new Set<string>();
    for (const t of data?.tasks ?? []) {
      if (t.parent_task_id) {
        const d = startOfDay(getTaskTime(t)).toDateString();
        concreteByScheduleDay.add(`${t.parent_task_id}:${d}`);
      }
    }

    for (const sched of data?.schedules ?? []) {
      if (!passesStatusFilter(sched, statusFilter)) continue;
      if (!sched.recurrence || !sched.scheduled_at || sched.status === "cancelled") continue;
      const intervalMs = parseRecurrenceMs(sched.recurrence);
      if (!intervalMs) continue;

      const rangeStartMs = rangeStart.getTime();
      const rangeEndMs = rangeEnd.getTime();
      const schedStart = new Date(sched.scheduled_at).getTime();

      let tt = schedStart;
      if (tt < rangeStartMs) {
        const steps = Math.floor((rangeStartMs - tt) / intervalMs);
        tt += steps * intervalMs;
      }
      if (tt > rangeStartMs) {
        const prevT = tt - intervalMs;
        if (prevT >= rangeStartMs) tt = prevT;
      }

      let count = 0;
      while (tt < rangeEndMs && count < 200) {
        if (tt >= rangeStartMs) {
          const occDate = new Date(tt);
          const dayStr = startOfDay(occDate).toDateString();
          const key = `${sched.id}:${dayStr}`;
          if (!concreteByScheduleDay.has(key)) {
            (map[dayStr] ??= []).push({
              ...sched,
              id: `virtual-${sched.id}-${tt}`,
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
        tt += intervalMs;
        count++;
      }
    }
    return map;
  }, [data, baseDate, rangeDays, rangeStart, rangeEnd, isCalendar, statusFilter]);

  const goToday = () => setBaseDate(startOfDay(new Date()));
  const goPrev = () => setBaseDate(addDays(baseDate, -rangeDays));
  const goNext = () => setBaseDate(addDays(baseDate, rangeDays));

  const handleEditorClose = () => setEditorState({ mode: "closed" });
  const handleEditorSaved = () => {
    setEditorState({ mode: "closed" });
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
  };

  const handleTaskPress = (task: TaskItem) => {
    if (task.task_type === "workflow") {
      navigate(`/admin/tasks/${task.id}`);
      return;
    }
    const taskId = task.is_virtual && task._schedule_id ? task._schedule_id : task.id;
    setEditorState({ mode: "edit", taskId });
  };

  const editorOpen = editorState.mode !== "closed";
  const editorTaskId = editorState.mode === "edit" ? editorState.taskId : null;
  const editorCloneFromId = editorState.mode === "clone" ? editorState.cloneFromId : undefined;

  const conflictCount = scheduleConflicts.size;
  const activeScheduleCount = (data?.schedules ?? []).filter(s => s.status === "active").length;
  const disabledScheduleCount = (data?.schedules ?? []).filter(s => s.status === "cancelled").length;

  const subtitle = data
    ? [
        activeScheduleCount > 0 && `${activeScheduleCount} schedule${activeScheduleCount !== 1 ? "s" : ""}`,
        disabledScheduleCount > 0 && `${disabledScheduleCount} disabled`,
        data.total > 0 && `${data.total} task run${data.total !== 1 ? "s" : ""}`,
      ].filter(Boolean).join(" \u00b7 ") || "No schedules"
    : undefined;

  const handleDayPress = (date: Date) => {
    setBaseDate(startOfDay(date));
    setViewMode("day");
  };

  const VIEW_MODES: { key: ViewMode; label: string; icon?: typeof Calendar }[] = [
    { key: "schedule", label: "Schedule", icon: Calendar },
    { key: "day", label: "Day", icon: CalendarDays },
    { key: "week", label: "Week", icon: CalendarRange },
    { key: "list", label: "List", icon: List },
    { key: "cron", label: "Cron Jobs", icon: Terminal },
  ];

  return (
    <div className="flex flex-1 min-h-0 bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Tasks"
        subtitle={!isMobile ? subtitle : undefined}
        right={
          isMobile ? (
            <button
              onClick={() => setEditorState({ mode: "create" })}
              title="New Task"
              className="flex flex-row items-center gap-1.5 px-3 py-[5px] text-xs font-semibold border-none cursor-pointer rounded-md bg-accent text-white hover:bg-accent-hover transition-colors"
            >
              <Plus size={14} />
            </button>
          ) : (
            <div className="flex flex-row items-center gap-1.5 flex-wrap">
              <button
                onClick={() => setEditorState({ mode: "create" })}
                title="New Task"
                className="flex flex-row items-center gap-1.5 px-3.5 py-[5px] text-xs font-semibold border-none cursor-pointer rounded-md bg-accent text-white hover:bg-accent-hover transition-colors"
              >
                <Plus size={14} />
                New Task
              </button>

              <select
                value={botFilter}
                onChange={(e) => setBotFilter(e.target.value)}
                className={`px-2 py-[5px] text-[11px] rounded-md bg-surface-raised cursor-pointer max-w-[140px] outline-none ${
                  botFilter
                    ? "text-text border border-accent"
                    : "text-text-dim border border-surface-border"
                }`}
              >
                <option value="">All Bots</option>
                {bots?.map((b: any) => (
                  <option key={b.id} value={b.id}>{b.name || b.id}</option>
                ))}
              </select>

              <div className="flex flex-row gap-0.5 bg-surface-raised rounded-lg border border-surface-border p-0.5">
                {VIEW_MODES.map((m) => {
                  const IconCmp = m.icon;
                  return (
                    <button
                      key={m.key}
                      onClick={() => setViewMode(m.key)}
                      className={`flex px-3 py-[5px] text-[11px] font-semibold border-none cursor-pointer rounded-md flex-row items-center gap-1 capitalize transition-colors duration-100 ${
                        viewMode === m.key
                          ? "bg-accent text-white"
                          : "bg-transparent text-text-muted hover:text-text"
                      }`}
                    >
                      {IconCmp && <IconCmp size={12} />}
                      {m.label}
                    </button>
                  );
                })}
              </div>

              {isCalendar && (
                <>
                  <button
                    onClick={goToday}
                    className="px-2 py-[5px] text-[11px] border border-surface-border rounded-md bg-transparent text-text-muted cursor-pointer hover:text-text hover:border-accent/50 transition-colors"
                  >
                    Today
                  </button>
                  <button onClick={goPrev} className="bg-transparent border-none cursor-pointer p-0.5">
                    <ChevronLeft size={16} className="text-text-muted" />
                  </button>
                  <span className="text-xs text-text font-medium text-center whitespace-nowrap">
                    {viewMode === "day"
                      ? formatDate(baseDate)
                      : `${formatDate(baseDate)} \u2014 ${formatDate(addDays(baseDate, 6))}`}
                  </span>
                  <button onClick={goNext} className="bg-transparent border-none cursor-pointer p-0.5">
                    <ChevronRight size={16} className="text-text-muted" />
                  </button>
                </>
              )}
            </div>
          )
        }
      />

      {/* Mobile control bar — view modes + date nav */}
      {isMobile && (
        <div className="flex flex-row items-center gap-1.5 px-3 py-2 border-b border-surface-border">
          <div className="flex flex-row gap-0.5 bg-surface-raised rounded-lg border border-surface-border p-0.5">
            {VIEW_MODES.map((m) => {
              const IconCmp = m.icon;
              return (
                <button
                  key={m.key}
                  onClick={() => setViewMode(m.key)}
                  className={`flex px-2.5 py-[5px] text-[11px] font-semibold border-none cursor-pointer rounded-md flex-row items-center gap-1 transition-colors duration-100 ${
                    viewMode === m.key
                      ? "bg-accent text-white"
                      : "bg-transparent text-text-muted hover:text-text"
                  }`}
                >
                  {IconCmp && <IconCmp size={12} />}
                </button>
              );
            })}
          </div>

          {isCalendar && (
            <>
              <button
                onClick={goToday}
                className="px-2 py-[5px] text-[11px] border border-surface-border rounded-md bg-transparent text-text-muted cursor-pointer hover:text-text hover:border-accent/50 transition-colors shrink-0"
              >
                Today
              </button>
              <button onClick={goPrev} className="bg-transparent border-none cursor-pointer p-0.5 shrink-0">
                <ChevronLeft size={16} className="text-text-muted" />
              </button>
              <span className="text-xs text-text font-medium text-center whitespace-nowrap min-w-0">
                {viewMode === "day"
                  ? formatDate(baseDate)
                  : `${baseDate.toLocaleDateString(undefined, { month: "short", day: "numeric" })} \u2013 ${addDays(baseDate, 6).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`}
              </span>
              <button onClick={goNext} className="bg-transparent border-none cursor-pointer p-0.5 shrink-0">
                <ChevronRight size={16} className="text-text-muted" />
              </button>
            </>
          )}
        </div>
      )}

      {/* Filter rows (hidden in cron mode) */}
      {viewMode !== "cron" && (
        <TaskFilters
          typeFilter={typeFilter}
          setTypeFilter={setTypeFilter}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          disabledScheduleCount={disabledScheduleCount}
          conflictCount={conflictCount}
          isMobile={isMobile}
          botFilter={isMobile ? botFilter : undefined}
          setBotFilter={isMobile ? setBotFilter : undefined}
          bots={isMobile ? bots : undefined}
        />
      )}

      {/* Invalid schedule warning */}
      {invalidSchedules.length > 0 && (
        <div className="flex flex-row items-start gap-2 px-4 py-2.5 bg-danger/[0.08] border-b border-danger/[0.15]">
          <AlertCircle size={14} className="text-danger shrink-0 mt-px" />
          <div className="flex-1 min-w-0">
            <div className="text-xs font-bold text-danger mb-0.5">
              {invalidSchedules.length} schedule{invalidSchedules.length !== 1 ? "s" : ""} with invalid recurrence — will never fire
            </div>
            {invalidSchedules.map((s) => (
              <span
                key={s.id}
                onClick={() => setEditorState({ mode: "edit", taskId: s.id })}
                className="inline-flex flex-row items-center gap-1 text-[11px] text-danger cursor-pointer mr-3 underline decoration-danger/30"
              >
                {s.title || s.prompt?.substring(0, 40) || s.id.slice(0, 8)} ({s.recurrence})
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Body */}
      {viewMode === "cron" ? (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
          <CronJobsView />
        </RefreshableScrollView>
      ) : isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="chat-spinner" />
        </div>
      ) : viewMode === "schedule" ? (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
          <ScheduleView
            tasks={data?.tasks ?? []}
            schedules={data?.schedules ?? []}
            onTaskPress={handleTaskPress}
            bots={bots}
            statusFilter={statusFilter}
            conflicts={scheduleConflicts}
          />
        </RefreshableScrollView>
      ) : viewMode === "list" ? (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
          <TaskListView
            tasks={data?.tasks ?? []}
            schedules={data?.schedules ?? []}
            onTaskPress={handleTaskPress}
            statusFilter={statusFilter}
          />
        </RefreshableScrollView>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
          {isMobile && viewMode === "week" ? (
            <MobileWeekSummary
              tasksByDay={tasksByDay}
              onDayPress={handleDayPress}
              onTaskPress={handleTaskPress}
            />
          ) : (
            <div
              className="flex flex-row flex-1 border-l border-surface-overlay"
              style={{ minHeight: 1500 }}
            >
              {Object.entries(tasksByDay).map(([dayStr, tasks], idx) => (
                <DayColumn
                  key={dayStr}
                  date={new Date(dayStr)}
                  tasks={tasks}
                  onTaskPress={handleTaskPress}
                  compact={viewMode === "week"}
                  showHourLabels={viewMode === "day" || idx === 0}
                />
              ))}
            </div>
          )}
        </RefreshableScrollView>
      )}

      {/* Task Create modal (create / clone) */}
      {editorState.mode === "create" && (
        <TaskCreateModal
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
        />
      )}
      {editorState.mode === "clone" && (
        <TaskCreateModal
          cloneFromId={editorCloneFromId}
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
        />
      )}
      {/* Task Editor overlay (edit) */}
      {editorState.mode === "edit" && (
        <TaskEditor
          taskId={editorTaskId}
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
          onClone={(id) => setEditorState({ mode: "clone", cloneFromId: id })}
        />
      )}
    </div>
  );
}
