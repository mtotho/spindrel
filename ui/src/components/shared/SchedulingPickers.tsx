/**
 * Shared scheduling components for task create/edit pages.
 *
 * Extracted from TaskEditor.tsx and [taskId]/index.tsx to eliminate duplication.
 * Includes: ScheduledAtPicker, RecurrencePicker, EnableToggle, ScheduleSummary.
 */
import { useMemo } from "react";
import { useThemeTokens } from "../../theme/tokens";
import { FormRow } from "./FormControls";
import { DateTimePicker } from "./DateTimePicker";
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
  const t = useThemeTokens();
  const isNow = !value;

  return (
    <FormRow label="Start">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <button
            onClick={() => onChange("")}
            style={{
              padding: "6px 14px", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 6, flexShrink: 0,
              background: isNow ? t.accent : t.surfaceRaised,
              color: isNow ? "#fff" : t.textMuted,
            }}
          >
            Now
          </button>
          <div style={{ flex: 1 }}>
            <DateTimePicker
              value={value}
              onChange={onChange}
              placeholder="Pick a date & time..."
            />
          </div>
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
  const t = useThemeTokens();
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
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <button
            onClick={handleToggle}
            style={{
              padding: "6px 14px", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 6, flexShrink: 0,
              background: !hasRecurrence ? t.surfaceRaised : t.warningSubtle,
              color: !hasRecurrence ? t.textMuted : t.warning,
            }}
          >
            {hasRecurrence ? "Repeating" : "No repeat"}
          </button>
          {hasRecurrence && (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 12, color: t.textMuted }}>every</span>
              <input
                type="number"
                min={1}
                value={numValue}
                onChange={(e) => handleNumChange(parseInt(e.target.value) || 1)}
                style={{
                  width: 56, padding: "6px 8px", fontSize: 13, textAlign: "center",
                  background: t.inputBg, border: `1px solid ${isValid ? t.surfaceBorder : t.danger}`,
                  borderRadius: 6, color: t.text, outline: "none",
                }}
              />
              <select
                value={unitValue}
                onChange={(e) => handleUnitChange(e.target.value)}
                style={{
                  padding: "6px 8px", fontSize: 13,
                  background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 6, color: t.text, outline: "none", cursor: "pointer",
                }}
              >
                {RECURRENCE_UNITS.map((u) => (
                  <option key={u.value} value={u.value}>{u.label}</option>
                ))}
              </select>
            </div>
          )}
        </div>
        {hasRecurrence && !isValid && (
          <span style={{ fontSize: 10, color: t.danger }}>
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
  const t = useThemeTokens();

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
    let t = startMs;
    // If start is in the past, advance to next occurrence
    const now = Date.now();
    if (t < now) {
      const steps = Math.ceil((now - t) / intervalMs);
      t += steps * intervalMs;
    }
    for (let i = 0; i < 3; i++) {
      runs.push(new Date(t));
      t += intervalMs;
    }
    return runs;
  }, [scheduledAt, recurrence]);

  if (!summary && nextRuns.length === 0) return null;

  return (
    <div style={{
      padding: "10px 12px", borderRadius: 8,
      background: t.surfaceRaised,
      border: `1px solid ${t.surfaceBorder}`,
      display: "flex", flexDirection: "column", gap: 6,
    }}>
      {summary && (
        <div style={{ fontSize: 12, color: t.text, fontWeight: 500 }}>
          {summary}
        </div>
      )}
      {nextRuns.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 10, color: t.textDim, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Next runs
          </span>
          {nextRuns.map((d, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
              <span style={{
                width: 4, height: 4, borderRadius: 2,
                background: i === 0 ? t.accent : t.textDim,
                flexShrink: 0,
              }} />
              <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
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
  const t = useThemeTokens();
  return (
    <button
      onClick={() => onChange(!enabled)}
      title={enabled ? "Enabled" : "Disabled"}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: compact ? 0 : 6,
        padding: compact ? "5px 6px" : "5px 12px", fontSize: 12, fontWeight: 600,
        border: "none", cursor: "pointer", borderRadius: 6, flexShrink: 0,
        background: enabled ? t.successSubtle : t.dangerSubtle,
        color: enabled ? t.success : t.danger,
      }}
    >
      <div style={{
        width: 28, height: 16, borderRadius: 8, position: "relative",
        background: enabled ? t.success : t.textDim,
        transition: "background 0.2s",
      }}>
        <div style={{
          width: 12, height: 12, borderRadius: 6, background: "#fff",
          position: "absolute", top: 2,
          left: enabled ? 14 : 2,
          transition: "left 0.2s",
        }} />
      </div>
      {!compact && (enabled ? "Enabled" : "Disabled")}
    </button>
  );
}

// ---------------------------------------------------------------------------
// InfoRow (shared read-only metadata row)
// ---------------------------------------------------------------------------
export function InfoRow({ label, value }: { label: string; value: string }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: t.textDim }}>{label}</span>
      <span style={{ fontSize: 11, color: t.text, fontFamily: "monospace" }}>{value}</span>
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

