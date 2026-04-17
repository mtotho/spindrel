import { useMemo } from "react";
import { useThemeTokens } from "../../theme/tokens";

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
  const t = useThemeTokens();
  const shape = useMemo(() => parseCronShape(value), [value]);
  const label = useMemo(() => humanLabelFor(value), [value]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        style={{
          background: t.inputBg,
          border: `1px solid ${shape.valid ? t.inputBorder : t.dangerBorder}`,
          borderRadius: 8,
          padding: "8px 12px",
          color: t.inputText,
          fontSize: 14,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          outline: "none",
          width: "100%",
        }}
      />
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, fontSize: 12 }}>
        {!shape.valid && value.trim() ? (
          <span style={{ color: t.danger }}>invalid: {shape.reason}</span>
        ) : label ? (
          <span style={{ color: t.textDim }}>{label}</span>
        ) : shape.valid ? (
          <span style={{ color: t.textDim }}>custom schedule</span>
        ) : (
          <span style={{ color: t.textDim }}>5-field cron (minute hour dom month dow)</span>
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {CRON_PRESETS.map((p) => {
          const active = p.expr === (value ?? "").trim();
          return (
            <button
              key={p.expr}
              type="button"
              onClick={() => onChange(p.expr)}
              style={{
                background: active ? t.accentSubtle : t.surfaceRaised,
                border: `1px solid ${active ? t.accentBorder : t.surfaceBorder}`,
                color: active ? t.accent : t.textMuted,
                borderRadius: 999,
                padding: "3px 10px",
                fontSize: 11,
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              {p.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
