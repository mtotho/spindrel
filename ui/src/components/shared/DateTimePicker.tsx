/**
 * DateTimePicker — custom calendar popover with quick-pick presets and time inputs.
 * Value format: "YYYY-MM-DDTHH:MM" (same as datetime-local).
 */
import { Calendar, X, ChevronLeft, ChevronRight } from "lucide-react";
import { useRef, useState, useMemo, useEffect, useCallback } from "react";

interface Props {
  value: string; // "YYYY-MM-DDTHH:MM" or ""
  onChange: (v: string) => void;
  placeholder?: string;
}

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDisplay(value: string): string {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const isTomorrow = d.toDateString() === tomorrow.toDateString();

  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (isToday) return `Today at ${time}`;
  if (isTomorrow) return `Tomorrow at ${time}`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() !== now.getFullYear() ? "numeric" : undefined }) + ` at ${time}`;
}

// ---------------------------------------------------------------------------
// Quick pick presets
// ---------------------------------------------------------------------------

const QUICK_PICKS = [
  { label: "Now", mins: 0 },
  { label: "In 5m", mins: 5 },
  { label: "In 30m", mins: 30 },
  { label: "In 1h", mins: 60 },
  { label: "In 6h", mins: 360 },
  { label: "Tomorrow 9am", mins: -1 },
  { label: "Next Mon 9am", mins: -2 },
];

function quickPickDate(mins: number): string {
  if (mins === 0) return toLocalInput(new Date());
  if (mins === -1) {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(9, 0, 0, 0);
    return toLocalInput(d);
  }
  if (mins === -2) {
    const d = new Date();
    const day = d.getDay(); // 0=Sun
    const daysUntilMon = day === 0 ? 1 : day === 1 ? 7 : 8 - day;
    d.setDate(d.getDate() + daysUntilMon);
    d.setHours(9, 0, 0, 0);
    return toLocalInput(d);
  }
  return toLocalInput(new Date(Date.now() + mins * 60_000));
}

// ---------------------------------------------------------------------------
// Calendar helpers
// ---------------------------------------------------------------------------

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

interface CalendarDay {
  date: Date;
  isCurrentMonth: boolean;
}

function getCalendarDays(year: number, month: number): CalendarDay[] {
  const firstOfMonth = new Date(year, month, 1);
  const startDay = firstOfMonth.getDay(); // 0=Sun
  const days: CalendarDay[] = [];

  // Fill in days from previous month
  for (let i = startDay - 1; i >= 0; i--) {
    const d = new Date(year, month, -i);
    days.push({ date: d, isCurrentMonth: false });
  }

  // Current month days
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  for (let d = 1; d <= daysInMonth; d++) {
    days.push({ date: new Date(year, month, d), isCurrentMonth: true });
  }

  // Fill to 42 (6 rows)
  while (days.length < 42) {
    const d = new Date(year, month + 1, days.length - startDay - daysInMonth + 1);
    days.push({ date: d, isCurrentMonth: false });
  }

  return days;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function DateTimePicker({ value, onChange, placeholder = "Pick a date & time..." }: Props) {
  const [open, setOpen] = useState(false);
  const [flipUp, setFlipUp] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const display = useMemo(() => formatDisplay(value), [value]);

  // Flip popover upward if it would overflow the viewport bottom
  useEffect(() => {
    if (!open || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const popoverHeight = 420; // approximate max height
    const spaceBelow = window.innerHeight - rect.bottom;
    setFlipUp(spaceBelow < popoverHeight && rect.top > popoverHeight);
  }, [open]);

  // Calendar view state
  const now = new Date();
  const selectedDate = value ? new Date(value) : null;
  const [viewYear, setViewYear] = useState(() => selectedDate?.getFullYear() ?? now.getFullYear());
  const [viewMonth, setViewMonth] = useState(() => selectedDate?.getMonth() ?? now.getMonth());

  // Time state (derived from value, editable independently)
  const hours = selectedDate ? selectedDate.getHours() : now.getHours();
  const minutes = selectedDate ? selectedDate.getMinutes() : 0;

  // Sync view month when value changes externally
  useEffect(() => {
    if (selectedDate) {
      setViewYear(selectedDate.getFullYear());
      setViewMonth(selectedDate.getMonth());
    }
  }, [value]);

  // Click outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const calendarDays = useMemo(() => getCalendarDays(viewYear, viewMonth), [viewYear, viewMonth]);

  const prevMonth = useCallback(() => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(viewYear - 1); }
    else setViewMonth(viewMonth - 1);
  }, [viewMonth, viewYear]);

  const nextMonth = useCallback(() => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(viewYear + 1); }
    else setViewMonth(viewMonth + 1);
  }, [viewMonth, viewYear]);

  const selectDay = useCallback((day: Date) => {
    const h = selectedDate ? selectedDate.getHours() : now.getHours();
    const m = selectedDate ? selectedDate.getMinutes() : 0;
    const combined = new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m);
    onChange(toLocalInput(combined));
  }, [selectedDate, onChange]);

  const setTime = useCallback((h: number, m: number) => {
    const base = selectedDate ?? now;
    const combined = new Date(base.getFullYear(), base.getMonth(), base.getDate(), h, m);
    onChange(toLocalInput(combined));
  }, [selectedDate, onChange]);

  const handleQuickPick = useCallback((mins: number) => {
    onChange(quickPickDate(mins));
    setOpen(false);
  }, [onChange]);

  return (
    <div ref={ref} className="relative w-full">
      {/* Trigger button */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`w-full flex flex-row items-center gap-2 bg-input border rounded-lg py-2 px-3 text-[13px] text-left cursor-pointer transition-colors ${
          open ? "border-accent" : "border-input-border hover:border-accent/40"
        }`}
      >
        <Calendar size={14} className="text-text-muted shrink-0" />
        <span className={`flex-1 truncate ${value ? "text-text" : "text-text-dim"}`}>
          {display || placeholder}
        </span>
        {value && (
          <span
            onClick={(e) => { e.stopPropagation(); onChange(""); }}
            className="text-text-dim hover:text-text cursor-pointer p-0.5"
          >
            <X size={13} />
          </span>
        )}
      </button>

      {/* Popover */}
      {open && (
        <div className={`absolute left-0 z-50 bg-surface border border-surface-border rounded-xl shadow-xl w-[280px] max-sm:w-[calc(100vw-32px)] max-sm:left-auto max-sm:right-0 ${
          flipUp ? "bottom-full mb-1.5" : "top-full mt-1.5"
        }`}>
          {/* Quick picks */}
          <div className="flex flex-row gap-1 flex-wrap p-2.5 pb-2 border-b border-surface-border/50">
            {QUICK_PICKS.map((qp) => (
              <button
                key={qp.label}
                type="button"
                onClick={() => handleQuickPick(qp.mins)}
                className="px-2 py-1 text-[10px] font-medium rounded-md border border-surface-border bg-surface-raised text-text-muted cursor-pointer hover:border-accent/40 hover:text-accent transition-colors"
              >
                {qp.label}
              </button>
            ))}
          </div>

          {/* Calendar */}
          <div className="p-2.5">
            {/* Month nav */}
            <div className="flex flex-row items-center justify-between mb-2">
              <button
                type="button"
                onClick={prevMonth}
                className="p-1 rounded-md bg-transparent border-none cursor-pointer text-text-muted hover:text-text hover:bg-surface-overlay transition-colors"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="text-xs font-semibold text-text">
                {MONTH_NAMES[viewMonth]} {viewYear}
              </span>
              <button
                type="button"
                onClick={nextMonth}
                className="p-1 rounded-md bg-transparent border-none cursor-pointer text-text-muted hover:text-text hover:bg-surface-overlay transition-colors"
              >
                <ChevronRight size={14} />
              </button>
            </div>

            {/* Weekday headers */}
            <div className="grid grid-cols-7 mb-0.5">
              {WEEKDAYS.map((wd) => (
                <div key={wd} className="text-center text-[10px] font-medium text-text-dim py-1">
                  {wd}
                </div>
              ))}
            </div>

            {/* Day grid */}
            <div className="grid grid-cols-7 gap-px">
              {calendarDays.map((cd, i) => {
                const isToday = sameDay(cd.date, now);
                const isSelected = selectedDate ? sameDay(cd.date, selectedDate) : false;
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => selectDay(cd.date)}
                    className={`w-full aspect-square flex items-center justify-center text-[11px] rounded-md border-none cursor-pointer transition-colors ${
                      isSelected
                        ? "bg-accent text-white font-semibold"
                        : isToday
                          ? "ring-1 ring-accent/50 text-accent font-semibold bg-transparent hover:bg-accent/10"
                          : cd.isCurrentMonth
                            ? "text-text bg-transparent hover:bg-surface-overlay"
                            : "text-text-dim/30 bg-transparent hover:bg-surface-overlay/50"
                    }`}
                  >
                    {cd.date.getDate()}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Time inputs */}
          <div className="flex flex-row items-center gap-2 px-2.5 pb-2.5 border-t border-surface-border/50 pt-2">
            <span className="text-[10px] text-text-dim font-semibold uppercase tracking-wider shrink-0">Time</span>
            <div className="flex flex-row items-center gap-1">
              <input
                type="number"
                min={0}
                max={23}
                value={hours}
                onChange={(e) => {
                  let h = parseInt(e.target.value) || 0;
                  if (h < 0) h = 0;
                  if (h > 23) h = 23;
                  setTime(h, minutes);
                }}
                className="w-11 px-1.5 py-1 text-xs text-center bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent font-mono"
              />
              <span className="text-text-dim font-bold text-xs">:</span>
              <input
                type="number"
                min={0}
                max={59}
                value={String(minutes).padStart(2, "0")}
                onChange={(e) => {
                  let m = parseInt(e.target.value) || 0;
                  if (m < 0) m = 0;
                  if (m > 59) m = 59;
                  setTime(hours, m);
                }}
                className="w-11 px-1.5 py-1 text-xs text-center bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent font-mono"
              />
            </div>
            {selectedDate && (
              <span className="text-[10px] text-text-dim ml-auto">
                {selectedDate.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
