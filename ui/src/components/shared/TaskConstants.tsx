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
  last_run_status?: string | null;
  last_run_at?: string | null;
  is_schedule?: boolean;
  is_virtual?: boolean;
  workflow_run_id?: string | null;
  workflow_step_index?: number | null;
  trigger_config?: { type?: string; event_source?: string; [key: string]: any } | null;
  source?: "user" | "system";
  /** For pipeline definitions: number of channels subscribed (Phase 5). */
  subscription_count?: number;
  /** Pipeline step definitions (used by the task editor, surfaced here so
   *  downstream pickers can read step type/id without re-fetching). */
  steps?: any[];
  /** execution_config JSON — surfaced for launchpad param_schema/featured reads. */
  execution_config?: Record<string, any> | null;
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
// Color maps — `fg` is still used by status dots and older inline-style consumers.
// New visible chrome should use the token-backed `tw` / `iconClass` classes.
// ---------------------------------------------------------------------------
export const TYPE_BADGE_COLORS: Record<string, { bg: string; fg: string; tw: string }> = {
  scheduled:  { bg: "rgb(var(--color-accent) / 0.10)",  fg: "rgb(var(--color-accent))", tw: "bg-accent/10 text-accent" },
  heartbeat:  { bg: "rgb(var(--color-warning) / 0.10)", fg: "rgb(var(--color-warning-muted))", tw: "bg-warning/10 text-warning-muted" },
  memory_hygiene: { bg: "rgb(var(--color-purple) / 0.10)", fg: "rgb(var(--color-purple))", tw: "bg-purple/10 text-purple" },
  delegation: { bg: "rgb(var(--color-purple) / 0.10)",  fg: "rgb(var(--color-purple))", tw: "bg-purple/10 text-purple" },
  exec:       { bg: "rgb(var(--color-surface-overlay))", fg: "rgb(var(--color-text-dim))", tw: "bg-surface-overlay text-text-dim" },
  callback:   { bg: "rgb(var(--color-danger) / 0.10)", fg: "rgb(var(--color-danger))", tw: "bg-danger/10 text-danger" },
  api:        { bg: "rgb(var(--color-success) / 0.10)", fg: "rgb(var(--color-success))", tw: "bg-success/10 text-success" },
  workflow:   { bg: "rgb(var(--color-warning) / 0.10)", fg: "rgb(var(--color-warning-muted))", tw: "bg-warning/10 text-warning-muted" },
  agent:      { bg: "rgb(var(--color-surface-overlay))", fg: "rgb(var(--color-text-dim))", tw: "bg-surface-overlay text-text-dim" },
  pipeline:   { bg: "rgb(var(--color-purple) / 0.10)",  fg: "rgb(var(--color-purple))", tw: "bg-purple/10 text-purple" },
};

export const STATUS_CFG: Record<string, { bg: string; fg: string; icon: any; label: string; tw: string; iconClass: string }> = {
  pending:   { bg: "rgb(var(--color-surface-overlay))", fg: "rgb(var(--color-text-dim))", icon: Clock,        label: "Pending",   tw: "bg-surface-overlay text-text-dim", iconClass: "text-text-dim" },
  running:   { bg: "rgb(var(--color-accent) / 0.10)",  fg: "rgb(var(--color-accent))", icon: Loader2,      label: "Running",   tw: "bg-accent/10 text-accent", iconClass: "text-accent" },
  complete:  { bg: "rgb(var(--color-success) / 0.10)", fg: "rgb(var(--color-success))", icon: CheckCircle2, label: "Complete",  tw: "bg-success/10 text-success", iconClass: "text-success" },
  failed:    { bg: "rgb(var(--color-danger) / 0.10)", fg: "rgb(var(--color-danger))", icon: AlertCircle,  label: "Failed",    tw: "bg-danger/10 text-danger", iconClass: "text-danger" },
  active:    { bg: "rgb(var(--color-warning) / 0.10)", fg: "rgb(var(--color-warning-muted))", icon: RefreshCw,    label: "Active",    tw: "bg-warning/10 text-warning-muted", iconClass: "text-warning-muted" },
  upcoming:  { bg: "rgb(var(--color-surface-overlay))", fg: "rgb(var(--color-text-dim))", icon: Clock,        label: "Upcoming",  tw: "bg-surface-overlay text-text-dim", iconClass: "text-text-dim" },
  cancelled: { bg: "rgb(var(--color-surface-overlay))", fg: "rgb(var(--color-text-dim))", icon: XCircle,      label: "Cancelled", tw: "bg-surface-overlay text-text-dim", iconClass: "text-text-dim" },
};

export const BOT_COLORS = [
  { bg: "rgb(var(--color-accent) / 0.10)", border: "rgb(var(--color-accent))", dot: "rgb(var(--color-accent))", fg: "rgb(var(--color-accent))" },
  { bg: "rgb(var(--color-purple) / 0.10)", border: "rgb(var(--color-purple))", dot: "rgb(var(--color-purple))", fg: "rgb(var(--color-purple))" },
  { bg: "rgb(var(--color-success) / 0.10)", border: "rgb(var(--color-success))", dot: "rgb(var(--color-success))", fg: "rgb(var(--color-success))" },
  { bg: "rgb(var(--color-warning) / 0.10)", border: "rgb(var(--color-warning-muted))", dot: "rgb(var(--color-warning-muted))", fg: "rgb(var(--color-warning-muted))" },
  { bg: "rgb(var(--color-danger) / 0.10)", border: "rgb(var(--color-danger))", dot: "rgb(var(--color-danger))", fg: "rgb(var(--color-danger))" },
  { bg: "rgb(var(--color-surface-overlay))", border: "rgb(var(--color-text-dim))", dot: "rgb(var(--color-text-dim))", fg: "rgb(var(--color-text-dim))" },
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
const TYPE_LABELS: Record<string, string> = {
  memory_hygiene: "dreaming",
};

export function TypeBadge({ type }: { type: string }) {
  const c = TYPE_BADGE_COLORS[type] || TYPE_BADGE_COLORS.agent;
  const label = TYPE_LABELS[type] || type;
  return (
    <span className={`inline-block rounded px-1.5 py-px text-[9px] font-semibold uppercase tracking-wider ${c.tw}`}>
      {label}
    </span>
  );
}

export function TaskStatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex shrink-0 flex-row items-center gap-1 whitespace-nowrap rounded px-2 py-0.5 text-[10px] font-semibold ${cfg.tw}`}>
      <Icon size={10} />
      {cfg.label}
    </span>
  );
}

export function BotDot({ botId, size = 8 }: { botId: string; size?: number }) {
  const c = botColor(botId);
  return (
    <div
      className="rounded-full shrink-0"
      style={{ width: size, height: size, background: c.dot }}
    />
  );
}
