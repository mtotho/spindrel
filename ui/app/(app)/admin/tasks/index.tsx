import { useState, useMemo, Fragment } from "react";
import { View, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Plus,
  Clock, AlertCircle, CheckCircle2, Loader2, RefreshCw, Calendar,
  List, AlertTriangle, XCircle, Terminal,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useBots } from "@/src/api/hooks/useBots";
import { TaskEditor } from "@/src/components/shared/TaskEditor";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { formatTime, formatDate } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";
import { CronJobsView } from "./CronJobsView";

interface TaskItem {
  id: string;
  status: string;
  bot_id: string;
  prompt: string;
  title?: string;
  result?: string;
  error?: string;
  dispatch_type: string;
  task_type?: string;
  recurrence?: string;
  run_count?: number;
  channel_id?: string;
  parent_task_id?: string;
  correlation_id?: string;
  created_at?: string;
  scheduled_at?: string;
  run_at?: string;
  completed_at?: string;
  is_schedule?: boolean;
  is_virtual?: boolean;
  /** For virtual entries, the real schedule ID to open in editor */
  _schedule_id?: string;
}

interface TasksResponse {
  tasks: TaskItem[];
  schedules: TaskItem[];
  total: number;
}

type ViewMode = "schedule" | "day" | "week" | "list" | "cron";
type TaskTypeFilter = "all" | "scheduled" | "delegation" | "harness" | "exec" | "api";
type StatusFilter = "active" | "all" | "cancelled" | "failed";

type EditorState =
  | { mode: "closed" }
  | { mode: "create" }
  | { mode: "edit"; taskId: string }
  | { mode: "clone"; cloneFromId: string };

const TASK_TYPE_FILTERS: { key: TaskTypeFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "scheduled", label: "Scheduled" },
  { key: "delegation", label: "Delegation" },
  { key: "harness", label: "Harness" },
  { key: "exec", label: "Exec" },
  { key: "api", label: "API" },
];

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "all", label: "All Statuses" },
  { key: "cancelled", label: "Cancelled" },
  { key: "failed", label: "Failed" },
];

const TYPE_BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  scheduled: { bg: "rgba(59,130,246,0.12)", fg: "#3b82f6" },
  heartbeat: { bg: "rgba(234,179,8,0.12)", fg: "#ca8a04" },
  delegation: { bg: "rgba(168,85,247,0.12)", fg: "#9333ea" },
  harness: { bg: "rgba(20,184,166,0.12)", fg: "#0d9488" },
  exec: { bg: "rgba(107,114,128,0.12)", fg: "#6b7280" },
  callback: { bg: "rgba(239,68,68,0.12)", fg: "#dc2626" },
  api: { bg: "rgba(34,197,94,0.12)", fg: "#16a34a" },
  agent: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af" },
};

const STATUS_CFG: Record<string, { bg: string; fg: string; icon: any; label: string }> = {
  pending:   { bg: "rgba(107,114,128,0.12)", fg: "#6b7280",  icon: Clock,        label: "Pending" },
  running:   { bg: "rgba(59,130,246,0.12)",  fg: "#3b82f6",  icon: Loader2,      label: "Running" },
  complete:  { bg: "rgba(34,197,94,0.12)",   fg: "#16a34a",  icon: CheckCircle2, label: "Complete" },
  failed:    { bg: "rgba(239,68,68,0.12)",   fg: "#dc2626",  icon: AlertCircle,  label: "Failed" },
  active:    { bg: "rgba(234,179,8,0.12)",   fg: "#ca8a04",  icon: RefreshCw,    label: "Active" },
  upcoming:  { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af",  icon: Clock,        label: "Upcoming" },
  cancelled: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af",  icon: XCircle,      label: "Cancelled" },
};

// ---------------------------------------------------------------------------
// Bot color palette — deterministic hash to 12 distinct hues
// ---------------------------------------------------------------------------
const BOT_COLORS = [
  { bg: "rgba(59,130,246,0.12)", border: "#3b82f6", dot: "#3b82f6", fg: "#2563eb" },  // blue
  { bg: "rgba(168,85,247,0.12)", border: "#a855f7", dot: "#a855f7", fg: "#9333ea" },  // purple
  { bg: "rgba(236,72,153,0.12)", border: "#ec4899", dot: "#ec4899", fg: "#db2777" },  // pink
  { bg: "rgba(239,68,68,0.12)",  border: "#ef4444", dot: "#ef4444", fg: "#dc2626" },  // red
  { bg: "rgba(249,115,22,0.12)", border: "#f97316", dot: "#f97316", fg: "#ea580c" },  // orange
  { bg: "rgba(234,179,8,0.12)",  border: "#eab308", dot: "#eab308", fg: "#ca8a04" },  // yellow
  { bg: "rgba(34,197,94,0.12)",  border: "#22c55e", dot: "#22c55e", fg: "#16a34a" },  // green
  { bg: "rgba(20,184,166,0.12)", border: "#14b8a6", dot: "#14b8a6", fg: "#0d9488" },  // teal
  { bg: "rgba(6,182,212,0.12)",  border: "#06b6d4", dot: "#06b6d4", fg: "#0891b2" },  // cyan
  { bg: "rgba(99,102,241,0.12)", border: "#6366f1", dot: "#6366f1", fg: "#4f46e5" },  // indigo
  { bg: "rgba(244,63,94,0.12)",  border: "#f43f5e", dot: "#f43f5e", fg: "#e11d48" },  // rose
  { bg: "rgba(132,204,22,0.12)", border: "#84cc16", dot: "#84cc16", fg: "#65a30d" },  // lime
];

function botColor(botId: string) {
  let hash = 0;
  for (let i = 0; i < botId.length; i++) {
    hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
  }
  return BOT_COLORS[Math.abs(hash) % BOT_COLORS.length];
}

function displayTitle(task: TaskItem): string {
  if (task.title) return task.title;
  if (!task.prompt) return "(no title)";
  const clean = task.prompt.replace(/\n/g, " ").trim();
  return clean.length > 60 ? clean.substring(0, 57) + "..." : clean;
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------
const UNIT_MS: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000, w: 604_800_000 };
function parseRecurrenceMs(recurrence: string): number | null {
  const m = recurrence.match(/^\+(\d+)([smhdw])$/);
  if (!m) return null;
  return parseInt(m[1]) * (UNIT_MS[m[2]] || 0);
}

function isValidRecurrence(recurrence: string): boolean {
  return /^\+\d+[smhdw]$/.test(recurrence);
}

/** Find active schedules with unparseable recurrence values. */
function detectInvalidSchedules(schedules: TaskItem[]): TaskItem[] {
  return schedules.filter(
    s => s.status === "active" && s.recurrence && !isValidRecurrence(s.recurrence)
  );
}

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

// fmtDate and fmtTime are imported from @/src/utils/time as formatDate and formatTime

function getTaskTime(t: TaskItem): Date {
  return new Date(t.scheduled_at || t.created_at || Date.now());
}

function isToday(d: Date) {
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

function isTomorrow(d: Date) {
  const tom = addDays(new Date(), 1);
  return d.getFullYear() === tom.getFullYear() && d.getMonth() === tom.getMonth() && d.getDate() === tom.getDate();
}

function dateSectionLabel(d: Date): string {
  if (isToday(d)) return "Today";
  if (isTomorrow(d)) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

// ---------------------------------------------------------------------------
// Status filter helper
// ---------------------------------------------------------------------------
function passesStatusFilter(task: TaskItem, filter: StatusFilter): boolean {
  if (filter === "all") return true;
  if (filter === "active") return task.status !== "cancelled";
  if (filter === "cancelled") return task.status === "cancelled";
  if (filter === "failed") return task.status === "failed";
  return true;
}

// ---------------------------------------------------------------------------
// Schedule conflict detection
// ---------------------------------------------------------------------------
function detectScheduleConflicts(schedules: TaskItem[]): Map<string, string[]> {
  const TWO_HOURS = 2 * 60 * 60 * 1000;
  const conflicts = new Map<string, string[]>();

  // Group active schedules by bot (only scheduled task_type)
  const byBot: Record<string, TaskItem[]> = {};
  for (const s of schedules) {
    if (s.status !== "active" || !s.recurrence) continue;
    if (s.task_type && s.task_type !== "scheduled") continue;
    (byBot[s.bot_id] ??= []).push(s);
  }

  const now = Date.now();
  const rangeEnd = now + 24 * 60 * 60 * 1000;

  for (const [botId, botSchedules] of Object.entries(byBot)) {
    if (botSchedules.length < 2) continue;

    const warnings: string[] = [];
    for (let i = 0; i < botSchedules.length; i++) {
      for (let j = i + 1; j < botSchedules.length; j++) {
        const a = botSchedules[i];
        const b = botSchedules[j];
        const aMs = parseRecurrenceMs(a.recurrence!);
        const bMs = parseRecurrenceMs(b.recurrence!);
        if (!aMs || !bMs) continue;

        // Both intervals <= 2h means they'll definitely fire close together
        if (aMs <= TWO_HOURS && bMs <= TWO_HOURS) {
          const aTitle = a.title || a.prompt?.substring(0, 30) || a.id.slice(0, 8);
          const bTitle = b.title || b.prompt?.substring(0, 30) || b.id.slice(0, 8);
          warnings.push(`"${aTitle}" (${a.recurrence}) and "${bTitle}" (${b.recurrence})`);
          continue;
        }

        // Expand next 24h of occurrences and check proximity
        const aStart = a.scheduled_at ? new Date(a.scheduled_at).getTime() : now;
        const bStart = b.scheduled_at ? new Date(b.scheduled_at).getTime() : now;

        const aOccs: number[] = [];
        let t = aStart;
        while (t < now) t += aMs;
        while (t < rangeEnd && aOccs.length < 50) { aOccs.push(t); t += aMs; }

        const bOccs: number[] = [];
        t = bStart;
        while (t < now) t += bMs;
        while (t < rangeEnd && bOccs.length < 50) { bOccs.push(t); t += bMs; }

        let hasConflict = false;
        for (const at of aOccs) {
          for (const bt of bOccs) {
            if (Math.abs(at - bt) < TWO_HOURS) {
              hasConflict = true;
              break;
            }
          }
          if (hasConflict) break;
        }

        if (hasConflict) {
          const aTitle = a.title || a.prompt?.substring(0, 30) || a.id.slice(0, 8);
          const bTitle = b.title || b.prompt?.substring(0, 30) || b.id.slice(0, 8);
          warnings.push(`"${aTitle}" (${a.recurrence}) and "${bTitle}" (${b.recurrence})`);
        }
      }
    }

    if (warnings.length > 0) {
      conflicts.set(botId, warnings);
    }
  }

  return conflicts;
}

// ---------------------------------------------------------------------------
// Current time indicator line
// ---------------------------------------------------------------------------
function NowLine() {
  const t = useThemeTokens();
  const now = new Date();
  const minutesSinceMidnight = now.getHours() * 60 + now.getMinutes();
  const pct = (minutesSinceMidnight / 1440) * 100;
  return (
    <div style={{
      position: "absolute", left: 0, right: 0, top: `${pct}%`,
      display: "flex", alignItems: "center", zIndex: 5, pointerEvents: "none",
    }}>
      <div style={{ width: 8, height: 8, borderRadius: 4, background: t.danger, marginLeft: -4 }} />
      <div style={{ flex: 1, height: 1, background: t.danger }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hour labels / grid
// ---------------------------------------------------------------------------
function HourLabels() {
  const t = useThemeTokens();
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => {
        const pct = (h / 24) * 100;
        return (
          <div key={h} style={{
            position: "absolute", left: 0, top: `${pct}%`,
            fontSize: 10, color: t.textDim, width: 40, textAlign: "right", paddingRight: 8,
            transform: "translateY(-50%)", pointerEvents: "none",
          }}>
            {h === 0 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`}
          </div>
        );
      })}
    </>
  );
}

function HourGrid() {
  const t = useThemeTokens();
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => (
        <div key={h} style={{
          position: "absolute", left: 48, right: 0,
          top: `${(h / 24) * 100}%`,
          borderTop: `1px solid ${t.surfaceRaised}`,
          pointerEvents: "none",
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
// Status badge — always visible, color-coded
// ---------------------------------------------------------------------------
function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending;
  const Icon = cfg.icon;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      background: cfg.bg, color: cfg.fg,
      padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
      flexShrink: 0, whiteSpace: "nowrap",
    }}>
      <Icon size={10} color={cfg.fg} />
      {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Bot color dot
// ---------------------------------------------------------------------------
function BotDot({ botId, size = 8 }: { botId: string; size?: number }) {
  const c = botColor(botId);
  return (
    <div style={{
      width: size, height: size, borderRadius: size / 2,
      background: c.dot, flexShrink: 0,
    }} />
  );
}

// ---------------------------------------------------------------------------
// Schedule conflict warning banner
// ---------------------------------------------------------------------------
function ConflictBanner({ warnings }: { warnings: string[] }) {
  const t = useThemeTokens();
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 8,
      padding: "8px 16px 8px 36px",
      background: t.warningSubtle,
      borderLeft: `3px solid ${t.warning}`,
    }}>
      <AlertTriangle size={14} color={t.warning} style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: t.warningMuted, marginBottom: 2 }}>
          Schedule Overlap — Schedules fire within 2 hours of each other
        </div>
        {warnings.map((w, i) => (
          <div key={i} style={{ fontSize: 10, color: t.warningMuted }}>
            {w}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Task card on timeline (Day/Week views) — simplified
// ---------------------------------------------------------------------------
function TaskCard({
  task, isPast, onPress, compact, style: extraStyle,
}: {
  task: TaskItem; isPast: boolean; onPress: () => void; compact?: boolean; style?: React.CSSProperties;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const isVirtual = task.is_virtual;
  const isCancelled = task.status === "cancelled";
  const s = STATUS_CFG[task.status] || STATUS_CFG.pending;
  const Icon = s.icon;
  const isRecurring = !!task.recurrence;
  const time = task.scheduled_at || task.created_at;

  // Theme-aware backgrounds
  const cancelledBg = hovered ? t.surfaceOverlay : t.surface;
  const virtualBg = hovered ? t.surfaceOverlay : t.accentMuted;
  const normalBg = hovered ? t.surfaceOverlay : isPast ? t.inputBg : t.surfaceRaised;
  const bg = isCancelled ? cancelledBg : isVirtual ? virtualBg : normalBg;
  const borderColor = isCancelled
    ? t.surfaceRaised
    : isVirtual
    ? (hovered ? t.accent : t.surfaceBorder)
    : hovered ? t.accent : isPast ? t.surfaceRaised : t.surfaceOverlay;

  return (
    <div
      onClick={onPress}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: compact ? "4px 8px" : "8px 12px", borderRadius: compact ? 6 : 8,
        background: bg,
        border: `1px solid ${borderColor}`,
        borderStyle: isVirtual ? "dashed" : "solid",
        opacity: isCancelled ? 0.4 : isVirtual ? (hovered ? 0.8 : 0.6) : (isPast && !hovered ? 0.5 : 1),
        transition: "opacity 0.15s, box-shadow 0.15s, border-color 0.15s",
        cursor: "pointer",
        boxShadow: hovered ? "0 4px 12px rgba(0,0,0,0.15)" : "none",
        zIndex: hovered ? 100 : undefined,
        ...extraStyle,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: compact ? 4 : 8 }}>
        <Icon size={compact ? 10 : 13} color={s.fg} style={{ flexShrink: 0 }} />
        <span style={{
          fontSize: compact ? 10 : 13, fontWeight: 600,
          color: isCancelled ? t.textDim : t.text,
          textDecoration: isCancelled ? "line-through" : "none",
          flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {displayTitle(task)}
        </span>

        {!compact && <StatusBadge status={task.status} />}

        {isRecurring && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            background: t.warningSubtle, color: t.warning,
            padding: compact ? "0px 5px" : "1px 7px", borderRadius: 10,
            fontSize: compact ? 8 : 10, fontWeight: 700,
            flexShrink: 0,
          }}>
            <RefreshCw size={compact ? 7 : 9} color={t.warning} />
            {task.recurrence}
          </span>
        )}

        {!compact && (
          <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>
            {time ? formatTime(time) : "\u2014"}
          </span>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: compact ? 4 : 6, marginTop: compact ? 2 : 4 }}>
        <BotDot botId={task.bot_id} size={compact ? 6 : 8} />
        <span style={{ fontSize: compact ? 9 : 10, color: t.textDim }}>{task.bot_id}</span>
        {!compact && task.task_type && <TypeBadge type={task.task_type} />}
        {compact && (
          <span style={{ fontSize: 9, color: t.textDim, marginLeft: "auto" }}>
            {time ? formatTime(time) : ""}
          </span>
        )}
      </div>
      {!compact && task.error && (
        <div style={{ fontSize: 10, color: t.danger, marginTop: 4 }}>
          {task.error.substring(0, 100)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day column
// ---------------------------------------------------------------------------
const CARD_HEIGHT_PX = 70;
const CARD_COMPACT_HEIGHT_PX = 46;
const CARD_MIN_GAP = 4;

function DayColumn({ date, tasks, onTaskPress, compact }: { date: Date; tasks: TaskItem[]; onTaskPress: (t: TaskItem) => void; compact?: boolean }) {
  const t = useThemeTokens();
  const now = new Date();
  const showNow = isToday(date);

  const cardHeight = compact ? CARD_COMPACT_HEIGHT_PX : CARD_HEIGHT_PX;

  const positioned = useMemo(() => {
    const sorted = [...tasks].sort((a, b) => getTaskTime(a).getTime() - getTaskTime(b).getTime());
    const items: { task: TaskItem; topPx: number }[] = [];

    for (const t of sorted) {
      const taskTime = getTaskTime(t);
      const minutes = taskTime.getHours() * 60 + taskTime.getMinutes();
      let topPx = minutes;

      for (const prev of items) {
        const prevBottom = prev.topPx + cardHeight + CARD_MIN_GAP;
        if (topPx < prevBottom) {
          topPx = prevBottom;
        }
      }
      items.push({ task: t, topPx });
    }
    return items;
  }, [tasks, cardHeight]);

  return (
    <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
      <div style={{
        padding: "8px 12px", borderBottom: `1px solid ${t.surfaceOverlay}`,
        background: showNow ? t.accentSubtle : "transparent",
        position: "sticky", top: 0, zIndex: 3,
      }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: showNow ? t.accent : t.text }}>
          {formatDate(date)}
        </div>
        <div style={{ fontSize: 10, color: t.textDim }}>
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
            compact={compact}
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
// Schedule view — grouped by bot, with date sub-headers
// ---------------------------------------------------------------------------
function ScheduleView({ tasks, schedules, onTaskPress, bots, statusFilter, conflicts }: {
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

// ---------------------------------------------------------------------------
// List view — simplified with title + bot dot
// ---------------------------------------------------------------------------
function TaskListView({ tasks, schedules, onTaskPress, statusFilter }: {
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
          {activeSchedules.map((tk) => {
            const s = STATUS_CFG[tk.status] || STATUS_CFG.pending;
            const Icon = s.icon;
            const isCancelled = tk.status === "cancelled";
            return (
              <div
                key={tk.id}
                onClick={() => onTaskPress(tk)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 14px", background: t.inputBg, borderRadius: 8,
                  border: `1px solid ${isCancelled ? t.surfaceBorder : t.surfaceRaised}`,
                  cursor: "pointer", marginBottom: 2,
                  opacity: isCancelled ? 0.4 : 1,
                }}
              >
                <Icon size={14} color={s.fg} />
                <BotDot botId={tk.bot_id} />
                <span style={{
                  fontSize: 13, fontWeight: 600,
                  color: isCancelled ? t.textDim : t.text,
                  textDecoration: isCancelled ? "line-through" : "none",
                  flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {displayTitle(tk)}
                </span>
                <StatusBadge status={tk.status} />
                <span style={{ fontSize: 10, color: t.textDim }}>{tk.bot_id}</span>
                {tk.recurrence && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", gap: 3,
                    background: isCancelled ? t.surfaceRaised : t.warningSubtle,
                    color: isCancelled ? t.textDim : t.warning,
                    padding: "1px 7px", borderRadius: 10, fontSize: 10, fontWeight: 700,
                  }}>
                    <RefreshCw size={9} color={isCancelled ? t.textDim : t.warning} />
                    {tk.recurrence}
                  </span>
                )}
                {tk.run_count != null && tk.run_count > 0 && (
                  <span style={{ fontSize: 10, color: t.textDim }}>{tk.run_count} runs</span>
                )}
              </div>
            );
          })}
        </>
      )}

      {/* Date sections */}
      {Object.entries(byDate).map(([dayStr, dayTasks]) => (
        <div key={dayStr}>
          <div style={{ padding: "12px 0 6px", fontSize: 11, fontWeight: 700, color: isToday(new Date(dayStr)) ? t.accent : t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
            {dateSectionLabel(new Date(dayStr))}
          </div>
          {dayTasks.map((tk) => {
            const s = STATUS_CFG[tk.status] || STATUS_CFG.pending;
            const Icon = s.icon;
            const time = tk.scheduled_at || tk.created_at;
            const isPast = getTaskTime(tk) < now && tk.status !== "running";
            const isCancelled = tk.status === "cancelled";
            return (
              <div
                key={tk.id}
                onClick={() => onTaskPress(tk)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 14px", background: t.inputBg, borderRadius: 8,
                  border: `1px solid ${t.surfaceRaised}`, cursor: "pointer", marginBottom: 2,
                  opacity: isCancelled ? 0.35 : isPast ? 0.6 : 1,
                }}
              >
                <Icon size={14} color={s.fg} />
                <BotDot botId={tk.bot_id} />
                <span style={{
                  fontSize: 13, fontWeight: 600,
                  color: isCancelled ? t.textDim : t.text,
                  textDecoration: isCancelled ? "line-through" : "none",
                  flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {displayTitle(tk)}
                </span>
                <StatusBadge status={tk.status} />
                <span style={{ fontSize: 10, color: t.textDim }}>{tk.bot_id}</span>
                {tk.task_type && <TypeBadge type={tk.task_type} />}
                <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>
                  {time ? formatTime(time) : "\u2014"}
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

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

      let t = schedStart;
      if (t < rangeStartMs) {
        const steps = Math.floor((rangeStartMs - t) / intervalMs);
        t += steps * intervalMs;
      }
      if (t > rangeStartMs) {
        const prevT = t - intervalMs;
        if (prevT >= rangeStartMs) t = prevT;
      }

      let count = 0;
      while (t < rangeEndMs && count < 200) {
        if (t >= rangeStartMs) {
          const occDate = new Date(t);
          const dayStr = startOfDay(occDate).toDateString();
          const key = `${sched.id}:${dayStr}`;
          if (!concreteByScheduleDay.has(key)) {
            (map[dayStr] ??= []).push({
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

  const handleTaskPress = (t: TaskItem) => {
    const taskId = t.is_virtual && t._schedule_id ? t._schedule_id : t.id;
    setEditorState({ mode: "edit", taskId });
  };

  const editorOpen = editorState.mode !== "closed";
  const editorTaskId = editorState.mode === "edit" ? editorState.taskId : null;
  const editorCloneFromId = editorState.mode === "clone" ? editorState.cloneFromId : undefined;

  const conflictCount = scheduleConflicts.size;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Tasks"
        subtitle={data ? `${data.total} total` : undefined}
        right={
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <button
              onClick={() => setEditorState({ mode: "create" })}
              title="New Task"
              style={{
                display: "flex", alignItems: "center", gap: 6,
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

            <div style={{ display: "flex", background: t.surfaceRaised, borderRadius: 6, overflow: "hidden" }}>
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
                    display: "flex", alignItems: "center", gap: 4,
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
      {viewMode !== "cron" && <div style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "8px 20px", borderBottom: `1px solid ${t.surfaceRaised}`,
        overflowX: "auto", flexWrap: "wrap",
      }}>
        {/* Type filter pills */}
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 10, color: t.textDim, fontWeight: 600, marginRight: 2 }}>TYPE</span>
          {TASK_TYPE_FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setTypeFilter(f.key)}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
                borderRadius: 12,
                background: typeFilter === f.key ? t.accent : t.surfaceRaised,
                color: typeFilter === f.key ? "#fff" : t.textMuted,
                whiteSpace: "nowrap",
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Separator */}
        <div style={{ width: 1, height: 20, background: t.surfaceOverlay, margin: "0 4px" }} />

        {/* Status filter pills */}
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 10, color: t.textDim, fontWeight: 600, marginRight: 2 }}>STATUS</span>
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key)}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
                borderRadius: 12,
                background: statusFilter === f.key
                  ? (f.key === "cancelled" ? t.surfaceBorder : f.key === "failed" ? t.dangerSubtle : t.accent)
                  : t.surfaceRaised,
                color: statusFilter === f.key
                  ? (f.key === "cancelled" ? t.textMuted : f.key === "failed" ? t.danger : "#fff")
                  : t.textMuted,
                whiteSpace: "nowrap",
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Conflict indicator */}
        {conflictCount > 0 && (
          <>
            <div style={{ width: 1, height: 20, background: t.surfaceOverlay, margin: "0 4px" }} />
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 11, fontWeight: 700, color: t.warningMuted,
              background: t.warningSubtle, padding: "3px 10px", borderRadius: 12,
            }}>
              <AlertTriangle size={11} color={t.warningMuted} />
              {conflictCount} bot{conflictCount !== 1 ? "s" : ""} with overlapping schedules
            </span>
          </>
        )}
      </div>}

      {/* Invalid schedule warning */}
      {invalidSchedules.length > 0 && (
        <div style={{
          display: "flex", alignItems: "flex-start", gap: 8,
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
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color={t.accent} />
        </View>
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
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1" contentContainerStyle={{ minHeight: 1500 }}>
          <div style={{
            display: "flex", flex: 1, minHeight: 1500,
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
    </View>
  );
}
