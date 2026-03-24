import { useState, useMemo } from "react";
import { View, ScrollView, ActivityIndicator } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, Plus,
  Clock, AlertCircle, CheckCircle2, Loader2, RefreshCw, Calendar,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { TaskEditor } from "@/src/components/shared/TaskEditor";
import { MobileMenuButton } from "@/src/components/layout/MobileMenuButton";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";

interface TaskItem {
  id: string;
  status: string;
  bot_id: string;
  prompt: string;
  result?: string;
  error?: string;
  dispatch_type: string;
  task_type?: string;
  recurrence?: string;
  channel_id?: string;
  created_at?: string;
  scheduled_at?: string;
  run_at?: string;
  completed_at?: string;
}

interface TasksResponse {
  tasks: TaskItem[];
  total: number;
}

type ViewMode = "day" | "week";
type TaskTypeFilter = "all" | "scheduled" | "heartbeat" | "delegation" | "harness" | "exec" | "callback" | "api" | "recurrence";

type EditorState =
  | { mode: "closed" }
  | { mode: "create" }
  | { mode: "edit"; taskId: string }
  | { mode: "clone"; cloneFromId: string };

const TASK_TYPE_FILTERS: { key: TaskTypeFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "scheduled", label: "Scheduled" },
  { key: "heartbeat", label: "Heartbeat" },
  { key: "delegation", label: "Delegation" },
  { key: "harness", label: "Harness" },
  { key: "exec", label: "Exec" },
  { key: "callback", label: "Callback" },
  { key: "api", label: "API" },
  { key: "recurrence", label: "Recurrence" },
];

const TYPE_BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  scheduled: { bg: "#1e3a5f", fg: "#93c5fd" },
  heartbeat: { bg: "#3b2e1a", fg: "#fbbf24" },
  delegation: { bg: "#2d1b4e", fg: "#c084fc" },
  harness: { bg: "#1a3333", fg: "#5eead4" },
  exec: { bg: "#333", fg: "#a3a3a3" },
  callback: { bg: "#2e1a1a", fg: "#f87171" },
  api: { bg: "#1a2e1a", fg: "#86efac" },
  recurrence: { bg: "#92400e", fg: "#fcd34d" },
  agent: { bg: "#222", fg: "#666" },
};

const STATUS_CFG: Record<string, { bg: string; fg: string; icon: any }> = {
  pending: { bg: "#333", fg: "#999", icon: Clock },
  running: { bg: "#1e3a5f", fg: "#93c5fd", icon: Loader2 },
  complete: { bg: "#166534", fg: "#86efac", icon: CheckCircle2 },
  failed: { bg: "#7f1d1d", fg: "#fca5a5", icon: AlertCircle },
};

function startOfDay(d: Date) {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}

function addDays(d: Date, n: number) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function fmtDate(d: Date) {
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function getTaskTime(t: TaskItem): Date {
  return new Date(t.scheduled_at || t.created_at || Date.now());
}

function isToday(d: Date) {
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

// ---------------------------------------------------------------------------
// Current time indicator line
// ---------------------------------------------------------------------------
function NowLine() {
  const now = new Date();
  const minutesSinceMidnight = now.getHours() * 60 + now.getMinutes();
  const pct = (minutesSinceMidnight / 1440) * 100;
  return (
    <div style={{
      position: "absolute", left: 0, right: 0, top: `${pct}%`,
      display: "flex", alignItems: "center", zIndex: 5, pointerEvents: "none",
    }}>
      <div style={{ width: 8, height: 8, borderRadius: 4, background: "#ef4444", marginLeft: -4 }} />
      <div style={{ flex: 1, height: 1, background: "#ef4444" }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hour labels
// ---------------------------------------------------------------------------
function HourLabels() {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => {
        const pct = (h / 24) * 100;
        return (
          <div key={h} style={{
            position: "absolute", left: 0, top: `${pct}%`,
            fontSize: 10, color: "#444", width: 40, textAlign: "right", paddingRight: 8,
            transform: "translateY(-50%)",
          }}>
            {h === 0 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`}
          </div>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Hour grid lines
// ---------------------------------------------------------------------------
function HourGrid() {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => (
        <div key={h} style={{
          position: "absolute", left: 48, right: 0,
          top: `${(h / 24) * 100}%`,
          borderTop: "1px solid #1a1a1a",
        }} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Task type badge
// ---------------------------------------------------------------------------
function TypeBadge({ type }: { type: string }) {
  const c = TYPE_BADGE_COLORS[type] || TYPE_BADGE_COLORS.agent;
  return (
    <span style={{
      display: "inline-block",
      background: c.bg, color: c.fg,
      padding: "1px 6px", borderRadius: 4, fontSize: 9, fontWeight: 600,
      textTransform: "uppercase", letterSpacing: 0.5,
    }}>
      {type}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Task card on timeline
// ---------------------------------------------------------------------------
function TaskCard({
  task, isPast, onPress, style: extraStyle,
}: {
  task: TaskItem; isPast: boolean; onPress: () => void; style?: React.CSSProperties;
}) {
  const [hovered, setHovered] = useState(false);
  const s = STATUS_CFG[task.status] || STATUS_CFG.pending;
  const Icon = s.icon;
  const isRecurring = !!task.recurrence;
  const time = task.scheduled_at || task.created_at;

  return (
    <div
      onClick={onPress}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: "8px 12px", borderRadius: 8,
        background: hovered ? "#222" : isPast ? "#111" : "#1a1a1a",
        border: `1px solid ${hovered ? "#3b82f6" : isPast ? "#1a1a1a" : "#2a2a2a"}`,
        opacity: isPast && !hovered ? 0.5 : 1,
        transition: "opacity 0.15s, box-shadow 0.15s, border-color 0.15s",
        cursor: "pointer",
        boxShadow: hovered ? "0 4px 16px rgba(0,0,0,0.5)" : "none",
        zIndex: hovered ? 100 : undefined,
        ...extraStyle,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon size={13} color={s.fg} />
        <span style={{ fontSize: 12, fontWeight: 600, color: s.fg }}>{task.status}</span>

        {task.task_type && <TypeBadge type={task.task_type} />}

        {isRecurring && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            background: "#92400e", color: "#fcd34d",
            padding: "1px 7px", borderRadius: 10, fontSize: 10, fontWeight: 700,
          }}>
            <RefreshCw size={9} color="#fcd34d" />
            {task.recurrence}
          </span>
        )}

        <span style={{ fontSize: 11, color: "#555", marginLeft: "auto" }}>
          {time ? fmtTime(time) : "\u2014"}
        </span>
      </div>

      <div style={{ fontSize: 11, color: "#999", marginTop: 4, fontFamily: "monospace" }}>
        {task.bot_id}
      </div>
      {task.prompt && (
        <div style={{
          fontSize: 11, color: isPast ? "#555" : "#888", marginTop: 4,
          whiteSpace: "pre-wrap", maxHeight: 40, overflow: "hidden",
        }}>
          {task.prompt.substring(0, 150)}{task.prompt.length > 150 ? "..." : ""}
        </div>
      )}
      {task.error && (
        <div style={{ fontSize: 10, color: "#fca5a5", marginTop: 4 }}>
          {task.error.substring(0, 100)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day column
// ---------------------------------------------------------------------------
const CARD_HEIGHT_PX = 80;
const CARD_MIN_GAP = 4;

function DayColumn({ date, tasks, onTaskPress }: { date: Date; tasks: TaskItem[]; onTaskPress: (t: TaskItem) => void }) {
  const now = new Date();
  const showNow = isToday(date);

  const positioned = useMemo(() => {
    const sorted = [...tasks].sort((a, b) => getTaskTime(a).getTime() - getTaskTime(b).getTime());
    const items: { task: TaskItem; topPx: number }[] = [];

    for (const t of sorted) {
      const taskTime = getTaskTime(t);
      const minutes = taskTime.getHours() * 60 + taskTime.getMinutes();
      let topPx = minutes;

      for (const prev of items) {
        const prevBottom = prev.topPx + CARD_HEIGHT_PX + CARD_MIN_GAP;
        if (topPx < prevBottom) {
          topPx = prevBottom;
        }
      }
      items.push({ task: t, topPx });
    }
    return items;
  }, [tasks]);

  return (
    <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
      <div style={{
        padding: "8px 12px", borderBottom: "1px solid #2a2a2a",
        background: showNow ? "rgba(59,130,246,0.08)" : "transparent",
        position: "sticky", top: 0, zIndex: 3,
      }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: showNow ? "#3b82f6" : "#e5e5e5" }}>
          {fmtDate(date)}
        </div>
        <div style={{ fontSize: 10, color: "#555" }}>
          {tasks.length} task{tasks.length !== 1 ? "s" : ""}
        </div>
      </div>

      <div style={{ position: "relative", height: 1440, paddingLeft: 48 }}>
        <HourGrid />
        <HourLabels />
        {showNow && <NowLine />}

        {positioned.map(({ task: t, topPx }) => (
          <TaskCard
            key={t.id}
            task={t}
            isPast={getTaskTime(t) < now && t.status !== "running"}
            onPress={() => onTaskPress(t)}
            style={{
              position: "absolute",
              top: topPx,
              left: 52,
              right: 8,
            }}
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Tasks screen
// ---------------------------------------------------------------------------
export default function TasksScreen() {
  const [viewMode, setViewMode] = useState<ViewMode>("day");
  const [baseDate, setBaseDate] = useState(() => startOfDay(new Date()));
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>("scheduled");
  const [editorState, setEditorState] = useState<EditorState>({ mode: "closed" });
  const qc = useQueryClient();
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";

  const rangeDays = viewMode === "day" ? 1 : 7;
  const rangeStart = baseDate;
  const rangeEnd = addDays(baseDate, rangeDays);

  const typeParam = typeFilter !== "all" ? `&task_type=${typeFilter}` : "";

  const { data, isLoading } = useQuery({
    queryKey: ["admin-tasks-timeline", rangeStart.toISOString(), rangeEnd.toISOString(), typeFilter],
    queryFn: () => apiFetch<TasksResponse>(
      `/api/v1/admin/tasks?after=${rangeStart.toISOString()}&before=${rangeEnd.toISOString()}&limit=200${typeParam}`
    ),
  });

  const tasksByDay = useMemo(() => {
    const map: Record<string, TaskItem[]> = {};
    for (let i = 0; i < rangeDays; i++) {
      const d = addDays(baseDate, i);
      map[d.toDateString()] = [];
    }
    for (const t of data?.tasks ?? []) {
      const d = startOfDay(getTaskTime(t)).toDateString();
      (map[d] ??= []).push(t);
    }
    return map;
  }, [data, baseDate, rangeDays]);

  const goToday = () => setBaseDate(startOfDay(new Date()));
  const goPrev = () => setBaseDate(addDays(baseDate, -rangeDays));
  const goNext = () => setBaseDate(addDays(baseDate, rangeDays));

  const handleEditorClose = () => setEditorState({ mode: "closed" });
  const handleEditorSaved = () => {
    setEditorState({ mode: "closed" });
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
  };

  // Derive TaskEditor props from editor state
  const editorOpen = editorState.mode !== "closed";
  const editorTaskId = editorState.mode === "edit" ? editorState.taskId : null;
  const editorCloneFromId = editorState.mode === "clone" ? editorState.cloneFromId : undefined;

  return (
    <View className="flex-1 bg-surface">
      {/* Header bar */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: isMobile ? "10px 12px" : "12px 20px", borderBottom: "1px solid #2a2a2a",
        gap: 8, flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <MobileMenuButton />
          <Calendar size={16} color="#3b82f6" />
          {!isMobile && (
            <span style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Tasks</span>
          )}
          <span style={{ fontSize: 11, color: "#555" }}>
            {data ? `${data.total}` : ""}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {/* New Task */}
          <button
            onClick={() => setEditorState({ mode: "create" })}
            title="New Task"
            style={{
              display: "flex", alignItems: "center", gap: isMobile ? 0 : 6,
              padding: isMobile ? "5px 8px" : "5px 14px", fontSize: 12, fontWeight: 600,
              border: "none", cursor: "pointer", borderRadius: 6, background: "#3b82f6", color: "#fff",
            }}
          >
            <Plus size={14} />
            {!isMobile && "New Task"}
          </button>

          {/* View mode toggle */}
          <div style={{ display: "flex", background: "#1a1a1a", borderRadius: 6, overflow: "hidden" }}>
            {(["day", "week"] as ViewMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setViewMode(m)}
                style={{
                  padding: isMobile ? "5px 10px" : "5px 14px", fontSize: 11, fontWeight: 500,
                  border: "none", cursor: "pointer",
                  background: viewMode === m ? "#3b82f6" : "transparent",
                  color: viewMode === m ? "#fff" : "#999",
                  textTransform: "capitalize",
                }}
              >
                {isMobile ? m[0].toUpperCase() : m}
              </button>
            ))}
          </div>

          {/* Navigation */}
          <button onClick={goToday} style={{
            padding: "5px 8px", fontSize: 11, border: "1px solid #333", borderRadius: 6,
            background: "transparent", color: "#999", cursor: "pointer",
          }}>
            Today
          </button>
          <button onClick={goPrev} style={{ background: "none", border: "none", cursor: "pointer", padding: 2 }}>
            <ChevronLeft size={16} color="#999" />
          </button>
          <span style={{ fontSize: 12, color: "#e5e5e5", fontWeight: 500, textAlign: "center" }}>
            {viewMode === "day"
              ? fmtDate(baseDate)
              : isMobile
                ? fmtDate(baseDate)
                : `${fmtDate(baseDate)} \u2014 ${fmtDate(addDays(baseDate, 6))}`}
          </span>
          <button onClick={goNext} style={{ background: "none", border: "none", cursor: "pointer", padding: 2 }}>
            <ChevronRight size={16} color="#999" />
          </button>
        </div>
      </div>

      {/* Type filter pills */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "8px 20px", borderBottom: "1px solid #1a1a1a",
        overflowX: "auto",
      }}>
        {TASK_TYPE_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setTypeFilter(f.key)}
            style={{
              padding: "4px 12px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 12,
              background: typeFilter === f.key ? "#3b82f6" : "#1a1a1a",
              color: typeFilter === f.key ? "#fff" : "#888",
              whiteSpace: "nowrap",
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Timeline body */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <ScrollView className="flex-1" contentContainerStyle={{ minHeight: 1500 }}>
          <div style={{
            display: "flex", flex: 1, minHeight: 1500,
            borderLeft: "1px solid #2a2a2a",
          }}>
            {Object.entries(tasksByDay).map(([dayStr, tasks]) => (
              <DayColumn
                key={dayStr}
                date={new Date(dayStr)}
                tasks={tasks}
                onTaskPress={(t) => setEditorState({ mode: "edit", taskId: t.id })}
              />
            ))}
          </div>
        </ScrollView>
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
    </View>
  );
}
