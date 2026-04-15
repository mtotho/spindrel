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
const SCHEDULE_PRESETS = [
  { label: "+30m", value: "+30m" },
  { label: "+1h", value: "+1h" },
  { label: "+2h", value: "+2h" },
  { label: "+6h", value: "+6h" },
  { label: "+1d", value: "+1d" },
  { label: "+7d", value: "+7d" },
];

const RECURRENCE_PRESETS = [
  { label: "None", value: "" },
  { label: "30 min", value: "+30m" },
  { label: "1 hour", value: "+1h" },
  { label: "2 hours", value: "+2h" },
  { label: "6 hours", value: "+6h" },
  { label: "12 hours", value: "+12h" },
  { label: "Daily", value: "+1d" },
  { label: "Weekly", value: "+1w" },
];

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
  const isRelative = /^\+\d+[smhdw]$/.test(value);

  const resolvedTime = useMemo(() => {
    if (!isRelative) return null;
    return resolveRelative(value);
  }, [value, isRelative]);

  return (
    <FormRow label="Scheduled At">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
          <PillButton
            active={!value}
            onClick={() => onChange("")}
            label="Now"
            t={t}
          />
          {SCHEDULE_PRESETS.map((p) => (
            <PillButton
              key={p.value}
              active={value === p.value}
              onClick={() => onChange(p.value)}
              label={p.label}
              t={t}
            />
          ))}
        </div>
        <DateTimePicker
          value={isRelative ? "" : value}
          onChange={onChange}
          placeholder="Pick a date & time..."
        />
        {isRelative && resolvedTime && (
          <div style={{ fontSize: 11, color: t.textDim, display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
            <span style={{ color: t.accent, fontWeight: 600 }}>{value}</span>
            <span>&rarr;</span>
            <span style={{ fontFamily: "monospace" }}>
              {resolvedTime.toLocaleString(undefined, {
                month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
              })}
            </span>
          </div>
        )}
      </div>
    </FormRow>
  );
}

// ---------------------------------------------------------------------------
// RecurrencePicker
// ---------------------------------------------------------------------------
export function RecurrencePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = useThemeTokens();
  const isPreset = RECURRENCE_PRESETS.some((p) => p.value === value);
  const showCustom = !!value && !isPreset;
  const isValid = !value || isValidRecurrence(value);

  return (
    <FormRow label="Recurrence">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {RECURRENCE_PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => onChange(p.value)}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
                borderRadius: 6,
                background: value === p.value ? (p.value ? t.warningSubtle : t.surfaceBorder) : t.surfaceRaised,
                color: value === p.value ? (p.value ? t.warning : t.text) : t.textMuted,
              }}
            >
              {p.label}
            </button>
          ))}
          <button
            onClick={() => { if (!showCustom) onChange("+3h"); }}
            style={{
              padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 6,
              background: showCustom ? t.warningSubtle : t.surfaceRaised,
              color: showCustom ? t.warning : t.textMuted,
            }}
          >
            Custom
          </button>
        </div>
        {showCustom && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <input
              type="text"
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder="+3h, +45m, +2d, etc."
              style={{
                background: t.inputBg,
                border: `1px solid ${isValid ? t.surfaceBorder : t.danger}`,
                borderRadius: 8,
                padding: "7px 12px", color: t.text, fontSize: 13, outline: "none",
                maxWidth: 200,
              }}
            />
            {!isValid && (
              <span style={{ fontSize: 10, color: t.danger }}>
                Format: +NUMBER[s|m|h|d|w] (e.g. +30m, +2h, +1d)
              </span>
            )}
          </div>
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

// ---------------------------------------------------------------------------
// Internal: pill button
// ---------------------------------------------------------------------------
function PillButton({ active, onClick, label, t }: {
  active: boolean;
  onClick: () => void;
  label: string;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
        borderRadius: 6,
        background: active ? t.accent : t.surfaceRaised,
        color: active ? "#fff" : t.textMuted,
      }}
    >
      {label}
    </button>
  );
}
