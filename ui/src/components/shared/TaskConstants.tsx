import {
  Clock, AlertCircle, CheckCircle2, Loader2, RefreshCw, XCircle,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Task item interface (shared between admin and channel views)
// ---------------------------------------------------------------------------
export interface TaskItem {
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
  workflow_run_id?: string | null;
  workflow_step_index?: number | null;
  /** For virtual entries, the real schedule ID to open in editor */
  _schedule_id?: string;
}

// ---------------------------------------------------------------------------
// Tasks API response
// ---------------------------------------------------------------------------
export interface TasksResponse {
  tasks: TaskItem[];
  schedules: TaskItem[];
  total: number;
}

// ---------------------------------------------------------------------------
// Color maps
// ---------------------------------------------------------------------------
export const TYPE_BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  scheduled: { bg: "rgba(59,130,246,0.12)", fg: "#3b82f6" },
  heartbeat: { bg: "rgba(234,179,8,0.12)", fg: "#ca8a04" },
  delegation: { bg: "rgba(168,85,247,0.12)", fg: "#9333ea" },
  exec: { bg: "rgba(107,114,128,0.12)", fg: "#6b7280" },
  callback: { bg: "rgba(239,68,68,0.12)", fg: "#dc2626" },
  api: { bg: "rgba(34,197,94,0.12)", fg: "#16a34a" },
  workflow: { bg: "rgba(249,115,22,0.12)", fg: "#ea580c" },
  agent: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af" },
};

export const STATUS_CFG: Record<string, { bg: string; fg: string; icon: any; label: string }> = {
  pending:   { bg: "rgba(107,114,128,0.12)", fg: "#6b7280",  icon: Clock,        label: "Pending" },
  running:   { bg: "rgba(59,130,246,0.12)",  fg: "#3b82f6",  icon: Loader2,      label: "Running" },
  complete:  { bg: "rgba(34,197,94,0.12)",   fg: "#16a34a",  icon: CheckCircle2, label: "Complete" },
  failed:    { bg: "rgba(239,68,68,0.12)",   fg: "#dc2626",  icon: AlertCircle,  label: "Failed" },
  active:    { bg: "rgba(234,179,8,0.12)",   fg: "#ca8a04",  icon: RefreshCw,    label: "Active" },
  upcoming:  { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af",  icon: Clock,        label: "Upcoming" },
  cancelled: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af",  icon: XCircle,      label: "Cancelled" },
};

export const BOT_COLORS = [
  { bg: "rgba(59,130,246,0.12)", border: "#3b82f6", dot: "#3b82f6", fg: "#2563eb" },
  { bg: "rgba(168,85,247,0.12)", border: "#a855f7", dot: "#a855f7", fg: "#9333ea" },
  { bg: "rgba(236,72,153,0.12)", border: "#ec4899", dot: "#ec4899", fg: "#db2777" },
  { bg: "rgba(239,68,68,0.12)",  border: "#ef4444", dot: "#ef4444", fg: "#dc2626" },
  { bg: "rgba(249,115,22,0.12)", border: "#f97316", dot: "#f97316", fg: "#ea580c" },
  { bg: "rgba(234,179,8,0.12)",  border: "#eab308", dot: "#eab308", fg: "#ca8a04" },
  { bg: "rgba(34,197,94,0.12)",  border: "#22c55e", dot: "#22c55e", fg: "#16a34a" },
  { bg: "rgba(20,184,166,0.12)", border: "#14b8a6", dot: "#14b8a6", fg: "#0d9488" },
  { bg: "rgba(6,182,212,0.12)",  border: "#06b6d4", dot: "#06b6d4", fg: "#0891b2" },
  { bg: "rgba(99,102,241,0.12)", border: "#6366f1", dot: "#6366f1", fg: "#4f46e5" },
  { bg: "rgba(244,63,94,0.12)",  border: "#f43f5e", dot: "#f43f5e", fg: "#e11d48" },
  { bg: "rgba(132,204,22,0.12)", border: "#84cc16", dot: "#84cc16", fg: "#65a30d" },
];

export function botColor(botId: string) {
  let hash = 0;
  for (let i = 0; i < botId.length; i++) {
    hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
  }
  return BOT_COLORS[Math.abs(hash) % BOT_COLORS.length];
}

export function displayTitle(task: TaskItem): string {
  if (task.title) return task.title;
  if (!task.prompt) return "(no title)";
  const clean = task.prompt.replace(/\n/g, " ").trim();
  return clean.length > 60 ? clean.substring(0, 57) + "..." : clean;
}

// ---------------------------------------------------------------------------
// Small presentational components
// ---------------------------------------------------------------------------
export function TypeBadge({ type }: { type: string }) {
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

export function TaskStatusBadge({ status }: { status: string }) {
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

export function BotDot({ botId, size = 8 }: { botId: string; size?: number }) {
  const c = botColor(botId);
  return (
    <div style={{
      width: size, height: size, borderRadius: size / 2,
      background: c.dot, flexShrink: 0,
    }} />
  );
}
