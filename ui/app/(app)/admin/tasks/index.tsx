import { useState, useMemo, useCallback, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, Plus, Calendar, CalendarDays, CalendarRange, List, Terminal, ListChecks, Cog, Network,
} from "lucide-react";
import { AlertCircle } from "lucide-react";
import { useRunTaskNow } from "@/src/api/hooks/useTasks";
import { useUpcomingActivity, type UpcomingItem } from "@/src/api/hooks/useUpcomingActivity";
import { apiFetch } from "@/src/api/client";
import { useBots } from "@/src/api/hooks/useBots";
import { TaskCreateWizard } from "@/src/components/shared/task/TaskCreateWizard";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { formatDate } from "@/src/utils/time";
import { SelectDropdown } from "@/src/components/shared/SelectDropdown";
import { SettingsSegmentedControl } from "@/src/components/shared/SettingsControls";
import type { TaskItem, TasksResponse } from "@/src/components/shared/TaskConstants";
import { CronJobsView } from "./CronJobsView";
import { DayColumn, MobileWeekSummary } from "./TaskTimelineComponents";
import { ScheduleView } from "./ScheduleView";
import { TaskListView } from "./TaskListView";
import { TaskDefinitionsView } from "./TaskDefinitionsView";
import { TaskFilters } from "./TaskFilters";
import { AutomationsCanvasPage } from "./canvas/AutomationsCanvasPage";
import {
  type ViewMode, type TaskTypeFilter, type StatusFilter, type EditorState,
  addDays, startOfDay, getTaskTime, passesStatusFilter, parseRecurrenceMs,
  detectScheduleConflicts, detectInvalidSchedules,
} from "./taskUtils";

// ---------------------------------------------------------------------------
// Main Tasks screen
// ---------------------------------------------------------------------------
const VIEW_MODE_SET = new Set<ViewMode>(["definitions", "schedule", "day", "week", "list", "cron"]);
const TYPE_FILTER_SET = new Set<TaskTypeFilter>(["all", "scheduled", "pipeline"]);
const STATUS_FILTER_SET = new Set<StatusFilter>(["active", "all", "cancelled", "failed"]);

export default function TasksScreen() {
  const [searchParams] = useSearchParams();
  // Canvas mode is a wholly different surface — short-circuit before the
  // list view's heavy hook tree fires. The split happens here (above all
  // hooks) so the two surfaces don't share state.
  if (searchParams.get("canvas") === "1") {
    return <AutomationsCanvasPage />;
  }
  return <TasksListScreen />;
}

function TasksListScreen() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read initial state from URL, fall back to defaults
  const viewMode = (VIEW_MODE_SET.has(searchParams.get("view") as ViewMode) ? searchParams.get("view") : "definitions") as ViewMode;
  const typeFilter = (TYPE_FILTER_SET.has(searchParams.get("type") as TaskTypeFilter) ? searchParams.get("type") : "all") as TaskTypeFilter;
  const statusFilter = (STATUS_FILTER_SET.has(searchParams.get("status") as StatusFilter) ? searchParams.get("status") : "active") as StatusFilter;
  const botFilter = searchParams.get("bot") || "";
  const baseDateParam = searchParams.get("date");
  const baseDate = useMemo(() => {
    if (baseDateParam) {
      const d = new Date(baseDateParam);
      if (!isNaN(d.getTime())) return startOfDay(d);
    }
    return startOfDay(new Date());
  }, [baseDateParam]);

  // Update URL params — replaces history entry to avoid flooding back stack
  const updateParams = useCallback((updates: Record<string, string | null>) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(updates)) {
        if (v === null || v === "") next.delete(k);
        else next.set(k, v);
      }
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const setViewMode = useCallback((v: ViewMode) => updateParams({ view: v === "definitions" ? null : v }), [updateParams]);
  const setTypeFilter = useCallback((v: TaskTypeFilter) => updateParams({ type: v === "all" ? null : v }), [updateParams]);
  const setStatusFilter = useCallback((v: StatusFilter) => updateParams({ status: v === "active" ? null : v }), [updateParams]);
  const setBotFilter = useCallback((v: string) => updateParams({ bot: v || null }), [updateParams]);
  const setBaseDate = useCallback((d: Date) => updateParams({ date: d.toISOString().slice(0, 10) }), [updateParams]);

  const [editorState, setEditorState] = useState<EditorState>({ mode: "closed" });

  // System-seeded tasks (source=system) are hidden from the admin list by default.
  // Persist the toggle across sessions so power users who opt in stay opted in.
  const [showSystem, setShowSystem] = useState<boolean>(() => {
    try { return localStorage.getItem("admin.tasks.showSystem") === "1"; } catch { return false; }
  });
  const toggleShowSystem = useCallback(() => {
    setShowSystem((v) => {
      const next = !v;
      try { localStorage.setItem("admin.tasks.showSystem", next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  }, []);

  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setEditorState({ mode: "create" });
      updateParams({ new: null });
    }
  }, [searchParams, updateParams]);

  const qc = useQueryClient();
  const navigate = useNavigate();
  const { refreshing, onRefresh } = usePageRefresh();
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const { data: bots } = useBots();
  const runNowMut = useRunTaskNow();

  const isCalendar = viewMode === "day" || viewMode === "week";
  const rangeDays = viewMode === "day" ? 1 : viewMode === "week" ? 7 : 1;
  const rangeStart = baseDate;
  const rangeEnd = addDays(baseDate, rangeDays);

  const typeParam = typeFilter !== "all" ? `&task_type=${typeFilter}` : "";
  const botParam = botFilter ? `&bot_id=${botFilter}` : "";
  const dateParams = isCalendar
    ? `&after=${rangeStart.toISOString()}&before=${rangeEnd.toISOString()}`
    : "";
  const defsParam = viewMode === "definitions" ? "&definitions_only=true" : "";

  const { data: rawData, isLoading } = useQuery({
    queryKey: ["admin-tasks-timeline", viewMode, rangeStart.toISOString(), rangeEnd.toISOString(), typeFilter, botFilter],
    queryFn: () => apiFetch<TasksResponse>(
      `/api/v1/admin/tasks?limit=200${dateParams}${typeParam}${botParam}${defsParam}`
    ),
  });

  // Client-side system-source filter. Server has no `source` query param yet;
  // filtering here keeps user-authored and system-seeded rows cleanly separated
  // without a second fetch. The count lets us surface "N system hidden" in UI.
  const { data, systemHiddenCount } = useMemo(() => {
    if (!rawData) return { data: rawData, systemHiddenCount: 0 };
    if (showSystem) return { data: rawData, systemHiddenCount: 0 };
    const filteredTasks = rawData.tasks.filter((t) => t.source !== "system");
    const filteredSchedules = rawData.schedules.filter((s) => s.source !== "system");
    const hidden =
      (rawData.tasks.length - filteredTasks.length) +
      (rawData.schedules.length - filteredSchedules.length);
    return {
      data: { ...rawData, tasks: filteredTasks, schedules: filteredSchedules },
      systemHiddenCount: hidden,
    };
  }, [rawData, showSystem]);

  // Upcoming activity (heartbeats + memory hygiene) — only needed for views that
  // surface upcoming runs. Tasks' pending rows are already in `data.tasks`; we only
  // materialize heartbeat + memory_hygiene because those live on bot/channel rows,
  // not as pending Task rows.
  const needUpcoming = isCalendar || viewMode === "list";
  const { data: upcomingRaw } = useQuery({
    queryKey: ["admin-tasks-upcoming"],
    queryFn: () => apiFetch<{ items: UpcomingItem[] }>(`/api/v1/admin/upcoming-activity?limit=200`),
    enabled: needUpcoming,
  });

  const upcomingVirtualTasks = useMemo<TaskItem[]>(() => {
    if (!needUpcoming || !upcomingRaw?.items) return [];
    // Non-"all" type filters target concrete user-created task types — don't pollute
    // them with heartbeat/hygiene virtual rows.
    if (typeFilter !== "all") return [];
    const out: TaskItem[] = [];
    for (const it of upcomingRaw.items) {
      if (it.type !== "heartbeat" && it.type !== "memory_hygiene") continue;
      if (botFilter && it.bot_id !== botFilter) continue;
      if (!it.scheduled_at) continue;
      const base = new Date(it.scheduled_at).getTime();
      const intervalMs =
        it.type === "heartbeat" && it.interval_minutes
          ? it.interval_minutes * 60_000
          : it.type === "memory_hygiene" && it.interval_hours
            ? it.interval_hours * 3_600_000
            : 0;
      const title =
        it.type === "heartbeat" && it.channel_name
          ? `Heartbeat — #${it.channel_name}`
          : it.title;
      const makeRow = (tMs: number, idx: number): TaskItem => ({
        id: `virtual-${it.type}-${it.bot_id}-${it.channel_id ?? ""}-${tMs}-${idx}`,
        status: "upcoming",
        bot_id: it.bot_id,
        prompt: "",
        title,
        dispatch_type: "none",
        task_type: it.type,
        recurrence:
          it.type === "heartbeat" && it.interval_minutes
            ? `+${it.interval_minutes}m`
            : it.type === "memory_hygiene" && it.interval_hours
              ? `+${it.interval_hours}h`
              : undefined,
        scheduled_at: new Date(tMs).toISOString(),
        channel_id: it.channel_id ?? undefined,
        is_virtual: true,
      });

      if (intervalMs > 0 && isCalendar) {
        // Expand occurrences across range [rangeStart, rangeEnd)
        const rangeStartMs = rangeStart.getTime();
        const rangeEndMs = rangeEnd.getTime();
        let tt = base;
        if (tt < rangeStartMs) {
          const steps = Math.floor((rangeStartMs - tt) / intervalMs);
          tt += steps * intervalMs;
        }
        let count = 0;
        let idx = 0;
        while (tt < rangeEndMs && count < 200) {
          if (tt >= rangeStartMs) out.push(makeRow(tt, idx++));
          tt += intervalMs;
          count++;
        }
      } else {
        // List view: just add the next occurrence returned by the API
        out.push(makeRow(base, 0));
      }
    }
    return out;
  }, [needUpcoming, upcomingRaw, botFilter, isCalendar, rangeStart, rangeEnd, typeFilter]);

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

    // Merge upcoming heartbeats + memory_hygiene virtual entries
    for (const vt of upcomingVirtualTasks) {
      const d = startOfDay(getTaskTime(vt)).toDateString();
      (map[d] ??= []).push(vt);
    }

    return map;
  }, [data, baseDate, rangeDays, rangeStart, rangeEnd, isCalendar, statusFilter, upcomingVirtualTasks]);

  const goToday = () => setBaseDate(startOfDay(new Date()));
  const goPrev = () => setBaseDate(addDays(baseDate, -rangeDays));
  const goNext = () => setBaseDate(addDays(baseDate, rangeDays));

  const handleEditorClose = () => setEditorState({ mode: "closed" });
  const handleEditorSaved = (createdTaskId?: string) => {
    setEditorState({ mode: "closed" });
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
    if (createdTaskId) {
      navigate(`/admin/automations/${createdTaskId}`);
    }
  };

  const handleTaskPress = (task: TaskItem) => {
    // Heartbeat virtual row → channel settings (heartbeat section)
    if (task.is_virtual && task.task_type === "heartbeat" && task.channel_id) {
      navigate(`/channels/${task.channel_id}/settings#heartbeat`);
      return;
    }
    // Memory hygiene virtual row → bot memory settings
    if (task.is_virtual && task.task_type === "memory_hygiene") {
      navigate(`/admin/bots/${task.bot_id}#memory`);
      return;
    }
    const taskId = task.is_virtual && task._schedule_id ? task._schedule_id : task.id;
    navigate(`/admin/automations/${taskId}`);
  };

  const handleRunNow = (taskId: string) => {
    runNowMut.mutate(taskId);
  };

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
    updateParams({ date: startOfDay(date).toISOString().slice(0, 10), view: "day" });
  };

  const VIEW_MODES: { key: ViewMode; label: string; icon?: typeof Calendar }[] = [
    { key: "definitions", label: "Definitions", icon: ListChecks },
    { key: "schedule", label: "Schedule", icon: Calendar },
    { key: "day", label: "Day", icon: CalendarDays },
    { key: "week", label: "Week", icon: CalendarRange },
    { key: "list", label: "List", icon: List },
    { key: "cron", label: "Cron Jobs", icon: Terminal },
  ];

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-surface overflow-hidden">
      <PageHeader
        variant="list"
        title="Tasks"
        subtitle={!isMobile ? subtitle : undefined}
        right={
          <div className="flex flex-row items-center gap-1">
            {!isMobile && (
              <button
                onClick={() => navigate("/canvas")}
                title="Open in spatial canvas"
                className="flex flex-row items-center gap-1.5 px-3 py-[5px] text-xs font-semibold border-none cursor-pointer rounded-md bg-transparent text-text-dim hover:text-text hover:bg-surface-overlay/45 transition-colors"
              >
                <Network size={14} />
                Open in spatial canvas
              </button>
            )}
            <button
              onClick={() => navigate("/admin/automations?canvas=1&new=1")}
              title="New Task"
              className="flex flex-row items-center gap-1.5 px-3 py-[5px] text-xs font-semibold border-none cursor-pointer rounded-md bg-transparent text-accent hover:bg-accent/[0.08] transition-colors"
            >
              <Plus size={14} />
              {!isMobile && "New Task"}
            </button>
          </div>
        }
      />

      {!isMobile && (
        <div className="flex shrink-0 flex-col gap-2 px-4 py-3">
          <div className="flex min-w-0 flex-row items-center gap-2">
            <div className="w-[260px] shrink-0">
              <SelectDropdown
                value={botFilter}
                onChange={setBotFilter}
                options={[
                  { value: "", label: "All Bots" },
                  ...(bots?.map((b: any) => ({ value: b.id, label: b.name || b.id, searchText: `${b.name ?? ""} ${b.id}` })) ?? []),
                ]}
                searchable={(bots?.length ?? 0) > 8}
                size="compact"
                popoverWidth="content"
                triggerClassName="min-h-[34px] w-full bg-surface-raised/50 text-[12px]"
              />
            </div>
            <button
              onClick={toggleShowSystem}
              title={showSystem ? "Hide system-seeded pipelines" : "Show system-seeded pipelines"}
              className={`flex min-h-[34px] shrink-0 cursor-pointer flex-row items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[11px] font-semibold outline-none transition-colors ${
                showSystem
                  ? "bg-accent/10 text-accent"
                  : "bg-surface-raised/40 text-text-dim hover:bg-surface-overlay/45 hover:text-text"
              }`}
            >
              <Cog size={12} />
              {showSystem ? "System on" : systemHiddenCount > 0 ? `${systemHiddenCount} system hidden` : "System"}
            </button>
          </div>

          <div className="flex min-w-0 flex-row items-center gap-2 overflow-x-auto">
            <SettingsSegmentedControl<ViewMode>
              value={viewMode}
              onChange={setViewMode}
              options={VIEW_MODES.map((m) => {
                const IconCmp = m.icon;
                return {
                  value: m.key,
                  label: m.label,
                  icon: IconCmp ? <IconCmp size={12} /> : undefined,
                };
              })}
              className="shrink-0"
            />

            {isCalendar && (
              <div className="flex shrink-0 flex-row items-center gap-1.5">
                <button
                  onClick={goToday}
                  className="px-2 py-[5px] text-[11px] rounded-md bg-transparent text-text-muted cursor-pointer hover:bg-surface-overlay/50 hover:text-text transition-colors"
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
              </div>
            )}
          </div>
        </div>
      )}

      {/* Mobile control bar — view modes + date nav */}
      {isMobile && (
        <div className="flex flex-row items-center gap-1.5 px-3 py-2">
          <SettingsSegmentedControl<ViewMode>
            value={viewMode}
            onChange={setViewMode}
            options={VIEW_MODES.map((m) => {
              const IconCmp = m.icon;
              return {
                value: m.key,
                label: "",
                icon: IconCmp ? <IconCmp size={12} /> : undefined,
              };
            })}
            className="shrink-0"
          />

          {isCalendar && (
            <>
              <button
                onClick={goToday}
                className="shrink-0 cursor-pointer rounded-md bg-transparent px-2 py-[5px] text-[11px] text-text-muted transition-colors hover:bg-surface-overlay/50 hover:text-text"
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

      {/* Filter rows (hidden in cron and definitions mode) */}
      {viewMode !== "cron" && viewMode !== "definitions" && (
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
        <div className="flex flex-row items-start gap-2 px-4 py-2.5 bg-danger/[0.08]">
          <AlertCircle size={14} className="text-danger shrink-0 mt-px" />
          <div className="flex-1 min-w-0">
            <div className="text-xs font-bold text-danger mb-0.5">
              {invalidSchedules.length} schedule{invalidSchedules.length !== 1 ? "s" : ""} with invalid recurrence — will never fire
            </div>
            {invalidSchedules.map((s) => (
              <span
                key={s.id}
                onClick={() => navigate(`/admin/automations/${s.id}`)}
                className="inline-flex flex-row items-center gap-1 text-[11px] text-danger cursor-pointer mr-3 underline decoration-danger/30"
              >
                {s.title || s.prompt?.substring(0, 40) || s.id.slice(0, 8)} ({s.recurrence})
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Body */}
      {viewMode === "definitions" ? (
        isLoading ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="chat-spinner" />
          </div>
        ) : (
          <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
            <TaskDefinitionsView
              tasks={data?.tasks ?? []}
              schedules={data?.schedules ?? []}
              onTaskPress={handleTaskPress}
              onRunNow={handleRunNow}
              runningTaskId={runNowMut.isPending ? (typeof runNowMut.variables === "string" ? runNowMut.variables : runNowMut.variables?.taskId ?? null) : null}
              isMobile={isMobile}
            />
          </RefreshableScrollView>
        )
      ) : viewMode === "cron" ? (
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
            upcomingVirtual={upcomingVirtualTasks}
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
              className="flex flex-row flex-1"
              style={{ minHeight: 1500 }}
            >
              {Object.entries(tasksByDay).map(([dayStr, tasks], idx) => (
                <DayColumn
                  key={dayStr}
                  date={new Date(dayStr)}
                  tasks={tasks}
                  onTaskPress={handleTaskPress}
                  onDayPress={handleDayPress}
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
        <TaskCreateWizard
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
        />
      )}
      {editorState.mode === "clone" && (
        <TaskCreateWizard
          cloneFromId={editorCloneFromId}
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
        />
      )}
    </div>
  );
}
