/**
 * Custom DateTimePicker — replaces the awful native <input type="datetime-local">.
 * Uses a portal + fixed positioning so the dropdown escapes any ScrollView/overflow parent.
 * Value format: "YYYY-MM-DDTHH:MM" (same as datetime-local).
 */
import { useState, useRef, useEffect, useCallback, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Calendar, X } from "lucide-react";
import { useThemeTokens, type ThemeTokens } from "../../theme/tokens";

interface Props {
  value: string; // "YYYY-MM-DDTHH:MM" or ""
  onChange: (v: string) => void;
  placeholder?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function pad(n: number) { return n.toString().padStart(2, "0"); }

function daysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}

function startDayOfMonth(year: number, month: number) {
  return new Date(year, month, 1).getDay();
}

function parseValue(v: string): { year: number; month: number; day: number; hour: number; minute: number } | null {
  if (!v) return null;
  const m = v.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return null;
  return { year: +m[1], month: +m[2] - 1, day: +m[3], hour: +m[4], minute: +m[5] };
}

function formatValue(year: number, month: number, day: number, hour: number, minute: number) {
  return `${year}-${pad(month + 1)}-${pad(day)}T${pad(hour)}:${pad(minute)}`;
}

function formatDisplay(v: string): string {
  const p = parseValue(v);
  if (!p) return "";
  const d = new Date(p.year, p.month, p.day, p.hour, p.minute);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

const DROPDOWN_WIDTH = 280;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function DateTimePicker({ value, onChange, placeholder = "Select date & time..." }: Props) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const parsed = parseValue(value);

  // Dropdown position (fixed to viewport)
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });

  // Calendar view state — defaults to selected date or today
  const now = new Date();
  const [viewYear, setViewYear] = useState(parsed?.year ?? now.getFullYear());
  const [viewMonth, setViewMonth] = useState(parsed?.month ?? now.getMonth());
  const [hour, setHour] = useState(parsed?.hour ?? now.getHours());
  const [minute, setMinute] = useState(parsed?.minute ?? 0);

  // Sync view when value changes externally
  useEffect(() => {
    const p = parseValue(value);
    if (p) {
      setViewYear(p.year);
      setViewMonth(p.month);
      setHour(p.hour);
      setMinute(p.minute);
    }
  }, [value]);

  // Calculate position when opening
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const dropdownHeight = 380; // approximate
    const viewH = window.innerHeight;
    const viewW = window.innerWidth;

    // Prefer below, flip above if no room
    let top = rect.bottom + 4;
    if (top + dropdownHeight > viewH && rect.top - dropdownHeight - 4 > 0) {
      top = rect.top - dropdownHeight - 4;
    }

    // Align left with trigger, but clamp to viewport
    let left = rect.left;
    if (left + DROPDOWN_WIDTH > viewW - 8) {
      left = viewW - DROPDOWN_WIDTH - 8;
    }
    if (left < 8) left = 8;

    setPos({ top, left });
  }, [open]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (dropdownRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  const selectDay = useCallback((day: number) => {
    onChange(formatValue(viewYear, viewMonth, day, hour, minute));
  }, [viewYear, viewMonth, hour, minute, onChange]);

  const updateTime = useCallback((h: number, m: number) => {
    setHour(h);
    setMinute(m);
    if (parsed) {
      onChange(formatValue(parsed.year, parsed.month, parsed.day, h, m));
    }
  }, [parsed, onChange]);

  const setNow = useCallback(() => {
    const n = new Date();
    const y = n.getFullYear(), mo = n.getMonth(), d = n.getDate(), h = n.getHours(), mi = n.getMinutes();
    setViewYear(y); setViewMonth(mo); setHour(h); setMinute(mi);
    onChange(formatValue(y, mo, d, h, mi));
  }, [onChange]);

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(viewYear - 1); }
    else setViewMonth(viewMonth - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(viewYear + 1); }
    else setViewMonth(viewMonth + 1);
  };

  // Build calendar grid
  const totalDays = daysInMonth(viewYear, viewMonth);
  const startDay = startDayOfMonth(viewYear, viewMonth);
  const weeks: (number | null)[][] = [];
  let week: (number | null)[] = Array(startDay).fill(null);
  for (let d = 1; d <= totalDays; d++) {
    week.push(d);
    if (week.length === 7) { weeks.push(week); week = []; }
  }
  if (week.length > 0) {
    while (week.length < 7) week.push(null);
    weeks.push(week);
  }

  const today = new Date();
  const isToday = (d: number) =>
    viewYear === today.getFullYear() && viewMonth === today.getMonth() && d === today.getDate();
  const isSelected = (d: number) =>
    parsed != null && viewYear === parsed.year && viewMonth === parsed.month && d === parsed.day;

  return (
    <>
      {/* Trigger button */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", alignItems: "center", gap: 8, width: "100%",
          background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8,
          padding: "8px 12px", color: value ? t.inputText : t.textDim, fontSize: 13,
          cursor: "pointer", outline: "none", textAlign: "left",
        }}
      >
        <Calendar size={14} color={t.textMuted} style={{ flexShrink: 0 }} />
        <span style={{ flex: 1 }}>{value ? formatDisplay(value) : placeholder}</span>
        {value && (
          <span
            onClick={(e) => { e.stopPropagation(); onChange(""); }}
            style={{ padding: 2, cursor: "pointer", lineHeight: 0 }}
          >
            <X size={13} color={t.textDim} />
          </span>
        )}
      </button>

      {/* Portal dropdown — renders at document.body so it escapes overflow:hidden/scroll */}
      {open && createPortal(
        <div
          ref={dropdownRef}
          style={{
            position: "fixed", top: pos.top, left: pos.left, zIndex: 9999,
            background: t.surface, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 10, boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
            padding: 12, width: DROPDOWN_WIDTH, userSelect: "none",
          }}
        >
          {/* Month / year nav */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <NavBtn onClick={prevMonth} t={t}><ChevronLeft size={14} /></NavBtn>
            <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
              {MONTHS[viewMonth]} {viewYear}
            </span>
            <NavBtn onClick={nextMonth} t={t}><ChevronRight size={14} /></NavBtn>
          </div>

          {/* Day-of-week header */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 0, marginBottom: 2 }}>
            {DAYS.map((d) => (
              <div key={d} style={{
                textAlign: "center", fontSize: 10, fontWeight: 600,
                color: t.textDim, padding: "4px 0",
              }}>
                {d}
              </div>
            ))}
          </div>

          {/* Calendar grid */}
          {weeks.map((w, wi) => (
            <div key={wi} style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 0 }}>
              {w.map((day, di) => (
                <div key={di} style={{ display: "flex", justifyContent: "center", padding: 1 }}>
                  {day != null ? (
                    <button
                      type="button"
                      onClick={() => selectDay(day)}
                      style={{
                        width: 32, height: 32, borderRadius: 8, border: "none",
                        fontSize: 12, fontWeight: isSelected(day) ? 700 : 400,
                        cursor: "pointer",
                        background: isSelected(day) ? t.accent : "transparent",
                        color: isSelected(day) ? "#fff" : isToday(day) ? t.accent : t.text,
                        outline: isToday(day) && !isSelected(day) ? `1px solid ${t.accent}` : "none",
                      }}
                    >
                      {day}
                    </button>
                  ) : <div style={{ width: 32, height: 32 }} />}
                </div>
              ))}
            </div>
          ))}

          {/* Time row */}
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            marginTop: 10, paddingTop: 10,
            borderTop: `1px solid ${t.surfaceBorder}`,
          }}>
            <span style={{ fontSize: 11, color: t.textMuted, fontWeight: 500 }}>Time</span>
            <TimeSelect value={hour} max={23} onChange={(h) => updateTime(h, minute)} t={t} />
            <span style={{ color: t.textDim, fontWeight: 700 }}>:</span>
            <TimeSelect value={minute} max={59} step={5} onChange={(m) => updateTime(hour, m)} t={t} />
            <div style={{ flex: 1 }} />
            <button
              type="button"
              onClick={() => { setNow(); setOpen(false); }}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                border: `1px solid ${t.accent}`, borderRadius: 6,
                background: "transparent", color: t.accent, cursor: "pointer",
              }}
            >
              Now
            </button>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Small sub-components
// ---------------------------------------------------------------------------
function NavBtn({ onClick, t, children }: { onClick: () => void; t: ThemeTokens; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: "transparent", border: "none", cursor: "pointer",
        color: t.textMuted, padding: 4, borderRadius: 6,
        display: "flex", alignItems: "center",
      }}
    >
      {children}
    </button>
  );
}

function TimeSelect({ value, max, step = 1, onChange, t }: {
  value: number; max: number; step?: number; onChange: (v: number) => void; t: ThemeTokens;
}) {
  const options: number[] = [];
  for (let i = 0; i <= max; i += step) options.push(i);
  // Ensure current value is in options even if not on step boundary
  if (!options.includes(value)) {
    options.push(value);
    options.sort((a, b) => a - b);
  }
  return (
    <select
      value={value}
      onChange={(e) => onChange(+e.target.value)}
      style={{
        background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
        padding: "4px 6px", color: t.text, fontSize: 12,
        cursor: "pointer", outline: "none",
      }}
    >
      {options.map((o) => (
        <option key={o} value={o}>{pad(o)}</option>
      ))}
    </select>
  );
}
