import { useMemo, useCallback } from "react";
import { RotateCcw } from "lucide-react";
import { FormRow, SelectInput, Row, Col } from "@/src/components/shared/FormControls";
import { ActionButton } from "@/src/components/shared/SettingsControls";
import { TimePicker } from "@/src/components/shared/DateTimePicker";

const QUIET_PRESETS: ReadonlyArray<{
  label: string; start: string; end: string; description: string;
}> = [
  { label: "Overnight",   start: "22:00", end: "06:30", description: "10 PM \u2013 6:30 AM" },
  { label: "Late Night",  start: "23:00", end: "07:00", description: "11 PM \u2013 7 AM" },
  { label: "Sleep In",    start: "00:00", end: "09:00", description: "Midnight \u2013 9 AM" },
  { label: "Work Hours",  start: "09:00", end: "17:00", description: "9 AM \u2013 5 PM" },
];

const COMMON_TIMEZONES = [
  { label: "Eastern (America/New_York)", value: "America/New_York" },
  { label: "Central (America/Chicago)", value: "America/Chicago" },
  { label: "Mountain (America/Denver)", value: "America/Denver" },
  { label: "Pacific (America/Los_Angeles)", value: "America/Los_Angeles" },
  { label: "UTC", value: "UTC" },
  { label: "London (Europe/London)", value: "Europe/London" },
  { label: "Berlin (Europe/Berlin)", value: "Europe/Berlin" },
  { label: "Tokyo (Asia/Tokyo)", value: "Asia/Tokyo" },
  { label: "Sydney (Australia/Sydney)", value: "Australia/Sydney" },
];

/** Parse "HH:MM" to fractional hours (e.g. "22:30" -> 22.5) */
function timeToHours(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return (h || 0) + (m || 0) / 60;
}

/** Format "HH:MM" to human-readable (e.g. "22:00" -> "10 PM") */
function fmtTime12(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  if (isNaN(h)) return "";
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return m ? `${h12}:${String(m).padStart(2, "0")} ${ampm}` : `${h12} ${ampm}`;
}

export function QuietHoursPicker({ start, end, timezone, onChangeStart, onChangeEnd, onChangeTimezone, inheritedRange, defaultTimezone }: {
  start: string;
  end: string;
  timezone: string;
  onChangeStart: (v: string) => void;
  onChangeEnd: (v: string) => void;
  onChangeTimezone: (v: string) => void;
  inheritedRange?: string | null;
  defaultTimezone?: string | null;
}) {
  const hasValue = !!(start || end);

  const activePreset = QUIET_PRESETS.find(p => p.start === start && p.end === end);

  const barSegments = useMemo(() => {
    const s = start || (inheritedRange ? inheritedRange.split("-")[0] : "");
    const e = end || (inheritedRange ? inheritedRange.split("-")[1] : "");
    if (!s || !e) return null;
    const startH = timeToHours(s);
    const endH = timeToHours(e);
    if (startH > endH) {
      return [
        { left: (startH / 24) * 100, width: ((24 - startH) / 24) * 100 },
        { left: 0, width: (endH / 24) * 100 },
      ];
    }
    return [{ left: (startH / 24) * 100, width: ((endH - startH) / 24) * 100 }];
  }, [start, end, inheritedRange]);

  const applyPreset = useCallback((p: typeof QUIET_PRESETS[number]) => {
    onChangeStart(p.start);
    onChangeEnd(p.end);
  }, [onChangeStart, onChangeEnd]);

  const clear = useCallback(() => {
    onChangeStart("");
    onChangeEnd("");
    onChangeTimezone("");
  }, [onChangeStart, onChangeEnd, onChangeTimezone]);

  return (
    <div className="flex flex-col gap-2.5">
      {/* Presets */}
      <div className="flex flex-wrap items-center gap-1.5">
        {QUIET_PRESETS.map((p) => {
          const isActive = activePreset?.label === p.label;
          return (
            <button
              type="button"
              key={p.label}
              onClick={() => applyPreset(p)}
              className={
                `min-h-[36px] rounded-md px-3 py-1 text-xs transition-colors ` +
                `${isActive ? "bg-accent/10 font-bold text-accent" : "bg-surface-raised/40 font-medium text-text-muted hover:bg-surface-overlay/45 hover:text-text"}`
              }
              title={p.description}
            >
              {p.label}
              <span className={`ml-1 text-[10px] ${isActive ? "text-accent/80" : "text-text-dim"}`}>
                {p.description}
              </span>
            </button>
          );
        })}
        {hasValue && (
          <ActionButton
            label={inheritedRange ? "Reset" : "Clear"}
            onPress={clear}
            icon={<RotateCcw size={11} />}
            variant="ghost"
            size="small"
          />
        )}
      </div>

      {/* 24h visual bar */}
      {barSegments && (
        <div className="relative h-7 overflow-hidden rounded-md bg-surface/80">
          {barSegments.map((seg, i) => (
            <div
              key={i}
              className="absolute bottom-0 top-0 bg-accent/15"
              style={{
                left: `${seg.left}%`,
                width: `${seg.width}%`,
                borderLeft: i === 0 && seg.left > 0 ? "2px solid rgb(var(--color-accent))" : undefined,
                borderRight: "2px solid rgb(var(--color-accent))",
              }}
            />
          ))}
          {[0, 3, 6, 9, 12, 15, 18, 21].map((h) => (
            <span
              key={h}
              className="pointer-events-none absolute top-px select-none text-[8px] text-text-dim"
              style={{ left: `${(h / 24) * 100}%`, transform: "translateX(-50%)" }}
            >
              {h === 0 ? "12a" : h === 12 ? "12p" : h < 12 ? `${h}a` : `${h - 12}p`}
            </span>
          ))}
          <span className="pointer-events-none absolute bottom-0.5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] font-semibold text-text-muted">
            {start && end ? `Quiet ${fmtTime12(start)} \u2013 ${fmtTime12(end)}` :
             inheritedRange ? `Inherited: ${inheritedRange}` : ""}
          </span>
        </div>
      )}

      {/* Manual time inputs + timezone */}
      <Row>
        <Col>
          <FormRow label="Start" description="When quiet hours begin">
            <TimePicker
              value={start}
              onChange={onChangeStart}
              placeholder={inheritedRange ? `Inherit ${inheritedRange.split("-")[0]}` : "Start time"}
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow label="End" description="When quiet hours end">
            <TimePicker
              value={end}
              onChange={onChangeEnd}
              placeholder={inheritedRange ? `Inherit ${inheritedRange.split("-")[1]}` : "End time"}
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow label="Timezone">
            <SelectInput
              value={timezone}
              onChange={onChangeTimezone}
              options={[
                { label: defaultTimezone ? `Inherit (${defaultTimezone})` : "Server default", value: "" },
                ...COMMON_TIMEZONES,
              ]}
            />
          </FormRow>
        </Col>
      </Row>

      {!hasValue && inheritedRange && (
        <div className="text-[10px] italic text-text-dim">
          Using global default: {inheritedRange}{defaultTimezone ? ` (${defaultTimezone})` : ""}
        </div>
      )}
    </div>
  );
}
