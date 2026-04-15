import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, Plus, Calendar, List, Terminal,
} from "lucide-react";
import { AlertCircle } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useBots } from "@/src/api/hooks/useBots";
import { TaskEditor } from "@/src/components/shared/TaskEditor";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { formatDate } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";
import type { TaskItem, TasksResponse } from "@/src/components/shared/TaskConstants";
import { CronJobsView } from "./CronJobsView";
import { DayColumn } from "./TaskTimelineComponents";
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
    // Workflow tasks -> navigate to task detail page (has WorkflowRunLink)
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

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, background: t.surface, overflow: "hidden" }}>
      <PageHeader variant="list"
        title="Tasks"
        subtitle={subtitle}
        right={
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <button
              onClick={() => setEditorState({ mode: "create" })}
              title="New Task"
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                padding: "5px 14px", fontSize: 12, fontWeight: 600,
                border: "none", cursor: "pointer", borderRadius: 6, background: t.accent, color: "#fff",
              }}
            >
              <Plus size={14} />
              {!isMobile && "New Task"}
            </button>

            <select
              value={botFilter}
              onChange={(e) => setBotFilter(e.target.value)}
              style={{
                padding: "5px 8px", fontSize: 11, borderRadius: 6,
                background: t.surfaceRaised, color: botFilter ? t.text : t.textDim,
                border: botFilter ? `1px solid ${t.accent}` : `1px solid ${t.surfaceBorder}`,
                cursor: "pointer", maxWidth: 140,
              }}
            >
              <option value="">All Bots</option>
              {bots?.map((b: any) => (
                <option key={b.id} value={b.id}>{b.name || b.id}</option>
              ))}
            </select>

            <div style={{ display: "flex", flexDirection: "row", background: t.surfaceRaised, borderRadius: 6, overflow: "hidden" }}>
              {(["schedule", "day", "week", "list", "cron"] as ViewMode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setViewMode(m)}
                  style={{
                    padding: "5px 12px", fontSize: 11, fontWeight: 500,
                    border: "none", cursor: "pointer",
                    background: viewMode === m ? t.accent : "transparent",
                    color: viewMode === m ? "#fff" : t.textMuted,
                    textTransform: "capitalize",
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  }}
                >
                  {m === "schedule" && <Calendar size={12} />}
                  {m === "list" && <List size={12} />}
                  {m === "cron" && <Terminal size={12} />}
                  {m === "schedule" ? "Schedule" : m === "cron" ? "Cron Jobs" : m}
                </button>
              ))}
            </div>

            {isCalendar && (
              <>
                <button onClick={goToday} style={{
                  padding: "5px 8px", fontSize: 11, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                  background: "transparent", color: t.textMuted, cursor: "pointer",
                }}>
                  Today
                </button>
                <button onClick={goPrev} style={{ background: "none", border: "none", cursor: "pointer", padding: 2 }}>
                  <ChevronLeft size={16} color={t.textMuted} />
                </button>
                <span style={{ fontSize: 12, color: t.text, fontWeight: 500, textAlign: "center" }}>
                  {viewMode === "day"
                    ? formatDate(baseDate)
                    : `${formatDate(baseDate)} \u2014 ${formatDate(addDays(baseDate, 6))}`}
                </span>
                <button onClick={goNext} style={{ background: "none", border: "none", cursor: "pointer", padding: 2 }}>
                  <ChevronRight size={16} color={t.textMuted} />
                </button>
              </>
            )}
          </div>
        }
      />

      {/* Filter rows (hidden in cron mode) */}
      {viewMode !== "cron" && (
        <TaskFilters
          typeFilter={typeFilter}
          setTypeFilter={setTypeFilter}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          disabledScheduleCount={disabledScheduleCount}
          conflictCount={conflictCount}
        />
      )}

      {/* Invalid schedule warning */}
      {invalidSchedules.length > 0 && (
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 8,
          padding: "10px 16px",
          background: t.dangerSubtle,
          borderBottom: `1px solid ${t.dangerBorder}`,
        }}>
          <AlertCircle size={14} color={t.danger} style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: t.danger, marginBottom: 2 }}>
              {invalidSchedules.length} schedule{invalidSchedules.length !== 1 ? "s" : ""} with invalid recurrence — will never fire
            </div>
            {invalidSchedules.map((s) => (
              <span
                key={s.id}
                onClick={() => setEditorState({ mode: "edit", taskId: s.id })}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  fontSize: 11, color: t.danger, cursor: "pointer",
                  marginRight: 12,
                  textDecoration: "underline",
                  textDecorationColor: t.dangerBorder,
                }}
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
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
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
          <div style={{
            display: "flex", flexDirection: "row", flex: 1, minHeight: 1500,
            borderLeft: `1px solid ${t.surfaceOverlay}`,
          }}>
            {Object.entries(tasksByDay).map(([dayStr, tasks]) => (
              <DayColumn
                key={dayStr}
                date={new Date(dayStr)}
                tasks={tasks}
                onTaskPress={handleTaskPress}
                compact={viewMode === "week"}
              />
            ))}
          </div>
        </RefreshableScrollView>
      )}

      {/* Task Editor overlay */}
      {editorOpen && (
        <TaskEditor
          taskId={editorTaskId}
          cloneFromId={editorCloneFromId}
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
          onClone={(id) => setEditorState({ mode: "clone", cloneFromId: id })}
        />
      )}
    </div>
  );
}
