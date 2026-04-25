/**
 * Shared scheduling components for task create/edit pages.
 *
 * Extracted from TaskEditor.tsx and [taskId]/index.tsx to eliminate duplication.
 * Includes: ScheduledAtPicker, RecurrencePicker, EnableToggle, ScheduleSummary.
 */
import { useMemo } from "react";
import { FormRow } from "./FormControls";
import { DateTimePicker } from "./DateTimePicker";
import { SelectDropdown } from "./SelectDropdown";
import { parseRecurrenceMs, isValidRecurrence } from "@/app/(app)/admin/tasks/taskUtils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const UNIT_MS: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000, w: 604_800_000 };
const UNIT_NAMES: Record<string, [string, string]> = {
  s: ["second", "seconds"],
  m: ["minute", "minutes"],
  h: ["hour", "hours"],
  d: ["day", "days"],
  w: ["week", "weeks"],
};

/** Parse "+30m" → { value: 30, unit: "m" } */
function parseRecurrence(rec: string): { value: number; unit: string } | null {
  const m = rec.match(/^\+(\d+)([smhdw])$/);
  if (!m) return null;
  return { value: parseInt(m[1]), unit: m[2] };
}

/** "Every 30 minutes" / "Every 2 hours" / "Every day" / "Every week" */
function humanRecurrence(rec: string): string {
  const p = parseRecurrence(rec);
  if (!p) return rec;
  const [singular, plural] = UNIT_NAMES[p.unit] || [p.unit, p.unit];
  if (p.value === 1) {
    if (p.unit === "d") return "Daily";
    if (p.unit === "w") return "Weekly";
    if (p.unit === "h") return "Hourly";
    return `Every ${singular}`;
  }
  return `Every ${p.value} ${plural}`;
}

/** Resolve a relative offset string to an absolute Date from now. */
function resolveRelative(value: string): Date | null {
  const m = value.match(/^\+(\d+)([smhdw])$/);
  if (!m) return null;
  const ms = parseInt(m[1]) * (UNIT_MS[m[2]] || 0);
  return new Date(Date.now() + ms);
}

// ---------------------------------------------------------------------------
// ScheduledAtPicker
// ---------------------------------------------------------------------------
export function ScheduledAtPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const isNow = !value;

  return (
    <FormRow label="Start">
      <div className="flex flex-row items-center gap-2">
        <button
          onClick={() => onChange("")}
          className={`shrink-0 cursor-pointer rounded-md border border-transparent px-3.5 py-1.5 text-xs font-semibold transition-colors ${
            isNow ? "bg-surface-overlay text-text" : "bg-transparent text-text-muted hover:bg-surface-overlay/45 hover:text-text"
          }`}
        >
          Now
        </button>
        <div className="flex-1">
          <DateTimePicker
            value={value}
            onChange={onChange}
            placeholder="Pick a date & time..."
          />
        </div>
      </div>
    </FormRow>
  );
}

// ---------------------------------------------------------------------------
// RecurrencePicker
// ---------------------------------------------------------------------------
const RECURRENCE_UNITS = [
  { label: "Minutes", value: "m" },
  { label: "Hours", value: "h" },
  { label: "Days", value: "d" },
  { label: "Weeks", value: "w" },
];

export function RecurrencePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const parsed = value ? parseRecurrence(value) : null;
  const hasRecurrence = !!value;
  const isValid = !value || isValidRecurrence(value);

  const numValue = parsed?.value ?? 1;
  const unitValue = parsed?.unit ?? "h";

  const handleToggle = () => {
    if (hasRecurrence) {
      onChange("");
    } else {
      onChange("+1h");
    }
  };

  const handleNumChange = (n: number) => {
    if (n < 1) n = 1;
    onChange(`+${n}${unitValue}`);
  };

  const handleUnitChange = (u: string) => {
    onChange(`+${numValue}${u}`);
  };

  return (
    <FormRow label="Repeat">
      <div className="flex flex-col gap-2">
        <div className="flex flex-row items-center gap-2">
          <button
            onClick={handleToggle}
            className={`shrink-0 cursor-pointer rounded-md border border-transparent px-3.5 py-1.5 text-xs font-semibold transition-colors ${
              hasRecurrence ? "bg-surface-overlay text-text" : "bg-transparent text-text-muted hover:bg-surface-overlay/45 hover:text-text"
            }`}
          >
            {hasRecurrence ? "Repeating" : "No repeat"}
          </button>
          {hasRecurrence && (
            <div className="flex flex-row items-center gap-1.5">
              <span className="text-xs text-text-muted">every</span>
              <input
                type="number"
                min={1}
                value={numValue}
                onChange={(e) => handleNumChange(parseInt(e.target.value) || 1)}
                className={`w-14 rounded-md bg-input px-2 py-1.5 text-center text-[13px] text-text outline-none ring-1 focus:ring-accent/40 ${
                  isValid ? "ring-surface-border" : "ring-danger"
                }`}
              />
              <div className="w-[112px]">
                <SelectDropdown
                  value={unitValue}
                  options={RECURRENCE_UNITS}
                  onChange={handleUnitChange}
                  size="compact"
                  popoverWidth="trigger"
                />
              </div>
            </div>
          )}
        </div>
        {hasRecurrence && !isValid && (
          <span className="text-[10px] text-danger">
            Invalid recurrence value
          </span>
        )}
      </div>
    </FormRow>
  );
}

// ---------------------------------------------------------------------------
// ScheduleSummary — "Every 6 hours, starting in 30 minutes. Next 3 runs: ..."
// ---------------------------------------------------------------------------
export function ScheduleSummary({
  scheduledAt,
  recurrence,
}: {
  scheduledAt: string;
  recurrence: string;
}) {
  const summary = useMemo(() => {
    if (!recurrence && !scheduledAt) return null;

    const parts: string[] = [];

    // Recurrence description
    if (recurrence && isValidRecurrence(recurrence)) {
      parts.push(humanRecurrence(recurrence));
    }

    // Start time description
    if (scheduledAt) {
      const isRel = /^\+\d+[smhdw]$/.test(scheduledAt);
      if (isRel) {
        const p = parseRecurrence(scheduledAt);
        if (p) {
          const [singular, plural] = UNIT_NAMES[p.unit] || [p.unit, p.unit];
          parts.push(`starting in ${p.value} ${p.value === 1 ? singular : plural}`);
        }
      } else {
        const d = new Date(scheduledAt);
        if (!isNaN(d.getTime())) {
          const now = new Date();
          const diffMs = d.getTime() - now.getTime();
          if (diffMs > 0 && diffMs < 86_400_000) {
            parts.push(`starting at ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`);
          } else {
            parts.push(`starting ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} at ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`);
          }
        }
      }
    } else if (recurrence) {
      parts.push("starting now");
    }

    return parts.join(", ");
  }, [scheduledAt, recurrence]);

  // Compute next 3 occurrences for recurring tasks
  const nextRuns = useMemo(() => {
    if (!recurrence || !isValidRecurrence(recurrence)) return [];
    const intervalMs = parseRecurrenceMs(recurrence);
    if (!intervalMs) return [];

    let startMs: number;
    if (!scheduledAt) {
      startMs = Date.now();
    } else if (/^\+\d+[smhdw]$/.test(scheduledAt)) {
      const resolved = resolveRelative(scheduledAt);
      startMs = resolved ? resolved.getTime() : Date.now();
    } else {
      const d = new Date(scheduledAt);
      startMs = isNaN(d.getTime()) ? Date.now() : d.getTime();
    }

    const runs: Date[] = [];
    let cur = startMs;
    const now = Date.now();
    if (cur < now) {
      const steps = Math.ceil((now - cur) / intervalMs);
      cur += steps * intervalMs;
    }
    for (let i = 0; i < 3; i++) {
      runs.push(new Date(cur));
      cur += intervalMs;
    }
    return runs;
  }, [scheduledAt, recurrence]);

  if (!summary && nextRuns.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5 rounded-md bg-surface-raised/40 px-3 py-2.5">
      {summary && (
        <div className="text-xs font-medium text-text">
          {summary}
        </div>
      )}
      {nextRuns.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-text-dim font-semibold uppercase tracking-wider">
            Next runs
          </span>
          {nextRuns.map((d, i) => (
            <div key={i} className="flex flex-row items-center gap-1.5">
              <span className={`w-1 h-1 rounded-full shrink-0 ${i === 0 ? "bg-accent" : "bg-text-dim"}`} />
              <span className="text-[11px] text-text-muted font-mono">
                {d.toLocaleString(undefined, {
                  weekday: "short", month: "short", day: "numeric",
                  hour: "2-digit", minute: "2-digit",
                })}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EnableToggle
// ---------------------------------------------------------------------------
export function EnableToggle({ enabled, onChange, compact }: {
  enabled: boolean;
  onChange: (v: boolean) => void;
  compact?: boolean;
}) {
  return (
    <button
      onClick={() => onChange(!enabled)}
      title={enabled ? "Enabled" : "Disabled"}
      className={`flex flex-row items-center shrink-0 border-none cursor-pointer rounded-md text-xs font-semibold transition-colors ${
        compact ? "gap-0 px-1.5 py-[5px]" : "gap-1.5 px-3 py-[5px]"
      } ${
        enabled ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
      }`}
    >
      <div className={`relative w-7 h-4 rounded-full transition-colors duration-200 ${
        enabled ? "bg-success" : "bg-text-dim"
      }`}>
        <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-[left] duration-200 ${
          enabled ? "left-3.5" : "left-0.5"
        }`} />
      </div>
      {!compact && (enabled ? "Enabled" : "Disabled")}
    </button>
  );
}

// ---------------------------------------------------------------------------
// InfoRow (shared read-only metadata row)
// ---------------------------------------------------------------------------
export function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-row justify-between items-center">
      <span className="text-[11px] text-text-dim">{label}</span>
      <span className="text-[11px] text-text font-mono">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared constants
// ---------------------------------------------------------------------------
export const STATUS_OPTIONS = [
  { label: "Pending", value: "pending" },
  { label: "Active (Schedule)", value: "active" },
  { label: "Running", value: "running" },
  { label: "Complete", value: "complete" },
  { label: "Failed", value: "failed" },
  { label: "Cancelled", value: "cancelled" },
];

export const TASK_TYPE_OPTIONS_FULL = [
  { label: "Scheduled", value: "scheduled" },
  { label: "Heartbeat", value: "heartbeat" },
  { label: "Delegation", value: "delegation" },
  { label: "Exec", value: "exec" },
  { label: "Callback", value: "callback" },
  { label: "API", value: "api" },
  { label: "Workflow", value: "workflow" },
  { label: "Agent", value: "agent" },
];

export const TASK_TYPE_OPTIONS_CREATE = [
  { label: "Scheduled", value: "scheduled" },
  { label: "Delegation", value: "delegation" },
  { label: "Exec", value: "exec" },
  { label: "API", value: "api" },
  { label: "Agent", value: "agent" },
];
