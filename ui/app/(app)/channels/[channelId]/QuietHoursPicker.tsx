import { useMemo, useCallback } from "react";
import { RotateCcw } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { FormRow, TextInput, SelectInput, Row, Col } from "@/src/components/shared/FormControls";

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
  const t = useThemeTokens();
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
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Presets */}
      <div style={{ display: "flex", flexDirection: "row", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {QUIET_PRESETS.map((p) => {
          const isActive = activePreset?.label === p.label;
          return (
            <button
              key={p.label}
              onClick={() => applyPreset(p)}
              style={{
                padding: "5px 12px", borderRadius: 6, cursor: "pointer",
                fontSize: 12, fontWeight: isActive ? 700 : 500, minHeight: 36,
                border: `1px solid ${isActive ? t.accent : t.surfaceBorder}`,
                background: isActive ? `${t.accent}18` : t.inputBg,
                color: isActive ? t.accent : t.textMuted,
                transition: "all 0.12s",
              }}
              title={p.description}
            >
              {p.label}
              <span style={{ fontSize: 10, marginLeft: 4, color: isActive ? t.accent : t.textDim, opacity: 0.8 }}>
                {p.description}
              </span>
            </button>
          );
        })}
        {hasValue && (
          <button
            onClick={clear}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "5px 10px", borderRadius: 6, cursor: "pointer",
              fontSize: 11, fontWeight: 600, border: "none",
              background: "none", color: t.textDim,
            }}
            title={inheritedRange ? `Reset to inherited (${inheritedRange})` : "Clear quiet hours"}
          >
            <RotateCcw size={11} />
            {inheritedRange ? "Reset" : "Clear"}
          </button>
        )}
      </div>

      {/* 24h visual bar */}
      {barSegments && (
        <div style={{ position: "relative", height: 28, borderRadius: 6, overflow: "hidden" }}>
          <div style={{
            position: "absolute", inset: 0, borderRadius: 6,
            background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          }} />
          {barSegments.map((seg, i) => (
            <div key={i} style={{
              position: "absolute", top: 0, bottom: 0,
              left: `${seg.left}%`, width: `${seg.width}%`,
              background: `${t.accent}25`, borderLeft: i === 0 && seg.left > 0 ? `2px solid ${t.accent}` : undefined,
              borderRight: `2px solid ${t.accent}`,
            }} />
          ))}
          {[0, 3, 6, 9, 12, 15, 18, 21].map((h) => (
            <span key={h} style={{
              position: "absolute", top: 1, fontSize: 8, color: t.textDim,
              left: `${(h / 24) * 100}%`, transform: "translateX(-50%)",
              userSelect: "none", pointerEvents: "none",
            }}>
              {h === 0 ? "12a" : h === 12 ? "12p" : h < 12 ? `${h}a` : `${h - 12}p`}
            </span>
          ))}
          <span style={{
            position: "absolute", bottom: 2, left: "50%", transform: "translateX(-50%)",
            fontSize: 10, fontWeight: 600, color: t.textMuted, whiteSpace: "nowrap",
            pointerEvents: "none",
          }}>
            {start && end ? `Quiet ${fmtTime12(start)} \u2013 ${fmtTime12(end)}` :
             inheritedRange ? `Inherited: ${inheritedRange}` : ""}
          </span>
        </div>
      )}

      {/* Manual time inputs + timezone */}
      <Row>
        <Col>
          <FormRow label="Start" description="When quiet hours begin">
            <TextInput
              value={start}
              onChangeText={onChangeStart}
              placeholder={inheritedRange ? inheritedRange.split("-")[0] : "HH:MM"}
              type="time"
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow label="End" description="When quiet hours end">
            <TextInput
              value={end}
              onChangeText={onChangeEnd}
              placeholder={inheritedRange ? inheritedRange.split("-")[1] : "HH:MM"}
              type="time"
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
        <div style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>
          Using global default: {inheritedRange}{defaultTimezone ? ` (${defaultTimezone})` : ""}
        </div>
      )}
    </div>
  );
}
