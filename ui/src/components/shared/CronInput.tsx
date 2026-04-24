import { useMemo } from "react";

/** Quick presets — label + 5-field cron expression. */
export const CRON_PRESETS: { label: string; expr: string }[] = [
  { label: "Every 15 min", expr: "*/15 * * * *" },
  { label: "Hourly", expr: "0 * * * *" },
  { label: "Every 6h", expr: "0 */6 * * *" },
  { label: "Daily 2am", expr: "0 2 * * *" },
  { label: "Weekdays 9am", expr: "0 9 * * 1-5" },
  { label: "Weekly Mon 9am", expr: "0 9 * * 1" },
];

/**
 * Lightweight client-side cron validation. We reject anything that isn't
 * 5 space-separated fields; the server re-validates with croniter on save
 * so malformed expressions never persist.
 */
export function parseCronShape(expr: string): { valid: boolean; reason?: string } {
  const trimmed = (expr ?? "").trim();
  if (!trimmed) return { valid: false, reason: "empty" };
  const parts = trimmed.split(/\s+/);
  if (parts.length !== 5) {
    return {
      valid: false,
      reason: `need 5 fields (minute hour dom month dow), got ${parts.length}`,
    };
  }
  // Cheap per-field character whitelist; we delegate real validation to server.
  const fieldRe = /^[0-9*/,\-]+$/;
  const names = ["minute", "hour", "day-of-month", "month", "day-of-week"];
  for (let i = 0; i < 5; i++) {
    if (!fieldRe.test(parts[i])) {
      return { valid: false, reason: `invalid characters in ${names[i]} field` };
    }
  }
  return { valid: true };
}

export function humanLabelFor(expr: string): string | null {
  const trimmed = (expr ?? "").trim();
  const preset = CRON_PRESETS.find((p) => p.expr === trimmed);
  return preset ? preset.label : null;
}

export function CronInput({
  value,
  onChange,
  placeholder = "0 2 * * *",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const shape = useMemo(() => parseCronShape(value), [value]);
  const label = useMemo(() => humanLabelFor(value), [value]);

  return (
    <div className="flex flex-col gap-2">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        className={
          `w-full rounded-md border bg-input px-3 py-2 font-mono text-[14px] text-text outline-none transition-colors ` +
          (shape.valid ? "border-input-border focus:border-accent" : "border-danger/50 focus:border-danger")
        }
      />
      <div className="flex items-center gap-2 text-[12px]">
        {!shape.valid && value.trim() ? (
          <span className="text-danger">invalid: {shape.reason}</span>
        ) : label ? (
          <span className="text-text-dim">{label}</span>
        ) : shape.valid ? (
          <span className="text-text-dim">custom schedule</span>
        ) : (
          <span className="text-text-dim">5-field cron (minute hour dom month dow)</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {CRON_PRESETS.map((p) => {
          const active = p.expr === (value ?? "").trim();
          return (
            <button
              key={p.expr}
              type="button"
              onClick={() => onChange(p.expr)}
              className={
                `rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ` +
                (active ? "bg-accent/10 text-accent" : "bg-surface-raised/50 text-text-muted hover:bg-surface-overlay/60")
              }
            >
              {p.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
