import type { TaskItem } from "@/src/components/shared/TaskConstants";

// ---------------------------------------------------------------------------
// Type aliases
// ---------------------------------------------------------------------------
export type ViewMode = "definitions" | "schedule" | "day" | "week" | "list" | "cron";
export type TaskTypeFilter = "all" | "scheduled" | "delegation" | "exec" | "api" | "pipeline";
export type StatusFilter = "active" | "all" | "cancelled" | "failed";

export type EditorState =
  | { mode: "closed" }
  | { mode: "create" }
  | { mode: "edit"; taskId: string }
  | { mode: "clone"; cloneFromId: string };

// ---------------------------------------------------------------------------
// Filter constants
// ---------------------------------------------------------------------------
export const TASK_TYPE_FILTERS: { key: TaskTypeFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "scheduled", label: "Scheduled" },
  { key: "delegation", label: "Delegation" },
  { key: "exec", label: "Exec" },
  { key: "api", label: "API" },
  { key: "pipeline", label: "Pipeline" },
];

export const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "all", label: "All Statuses" },
  { key: "cancelled", label: "Cancelled" },
  { key: "failed", label: "Failed" },
];

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------
const UNIT_MS: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000, w: 604_800_000 };

export function parseRecurrenceMs(recurrence: string): number | null {
  const m = recurrence.match(/^\+(\d+)([smhdw])$/);
  if (!m) return null;
  return parseInt(m[1]) * (UNIT_MS[m[2]] || 0);
}

export function isValidRecurrence(recurrence: string): boolean {
  return /^\+\d+[smhdw]$/.test(recurrence);
}

/** Find active schedules with unparseable recurrence values. */
export function detectInvalidSchedules(schedules: TaskItem[]): TaskItem[] {
  return schedules.filter(
    s => s.status === "active" && s.recurrence && !isValidRecurrence(s.recurrence)
  );
}

export function startOfDay(d: Date) {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}

export function addDays(d: Date, n: number) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

export function getTaskTime(t: TaskItem): Date {
  return new Date(t.scheduled_at || t.created_at || Date.now());
}

export function isToday(d: Date) {
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

export function isTomorrow(d: Date) {
  const tom = addDays(new Date(), 1);
  return d.getFullYear() === tom.getFullYear() && d.getMonth() === tom.getMonth() && d.getDate() === tom.getDate();
}

export function dateSectionLabel(d: Date): string {
  if (isToday(d)) return "Today";
  if (isTomorrow(d)) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

// ---------------------------------------------------------------------------
// Status filter helper
// ---------------------------------------------------------------------------
export function passesStatusFilter(task: TaskItem, filter: StatusFilter): boolean {
  if (filter === "all") return true;
  if (filter === "active") return task.status !== "cancelled";
  if (filter === "cancelled") return task.status === "cancelled";
  if (filter === "failed") return task.status === "failed";
  return true;
}

// ---------------------------------------------------------------------------
// Schedule conflict detection
// ---------------------------------------------------------------------------
export function detectScheduleConflicts(schedules: TaskItem[]): Map<string, string[]> {
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
