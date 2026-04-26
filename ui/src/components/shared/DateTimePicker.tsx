/**
 * DateTimePicker — custom calendar popover with quick-pick presets and time inputs.
 * Value format: "YYYY-MM-DDTHH:MM" (same as datetime-local).
 */
import { Calendar, X, ChevronLeft, ChevronRight, Clock } from "lucide-react";
import { useRef, useState, useMemo, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { SelectDropdown, type SelectDropdownOption } from "./SelectDropdown";

interface Props {
  value: string; // "YYYY-MM-DDTHH:MM" or ""
  onChange: (v: string) => void;
  placeholder?: string;
}

interface TimePickerProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
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

function formatTime12(hhmm: string): string {
  const [rawH, rawM] = hhmm.split(":").map(Number);
  if (!Number.isFinite(rawH)) return hhmm;
  const minutes = Number.isFinite(rawM) ? rawM : 0;
  const suffix = rawH >= 12 ? "PM" : "AM";
  const hour = rawH === 0 ? 12 : rawH > 12 ? rawH - 12 : rawH;
  return `${hour}:${String(minutes).padStart(2, "0")} ${suffix}`;
}

const TIME_OPTIONS: SelectDropdownOption[] = Array.from({ length: 96 }, (_, index) => {
  const totalMinutes = index * 15;
  const hour = Math.floor(totalMinutes / 60);
  const minute = totalMinutes % 60;
  const value = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  return {
    value,
    label: formatTime12(value),
    meta: value,
    group: hour < 6 ? "night" : hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening",
    groupLabel: hour < 6 ? "Night" : hour < 12 ? "Morning" : hour < 18 ? "Afternoon" : "Evening",
    searchText: `${value} ${formatTime12(value)}`,
  };
});

export function TimePicker({ value, onChange, placeholder = "Select time...", disabled = false }: TimePickerProps) {
  return (
    <SelectDropdown
      value={value || null}
      options={TIME_OPTIONS}
      onChange={onChange}
      placeholder={placeholder}
      disabled={disabled}
      searchable
      searchPlaceholder="Search time..."
      emptyLabel="No matching time"
      size="md"
      popoverWidth="content"
      maxHeight={320}
      leadingIcon={<Clock size={14} className="shrink-0 text-text-dim" />}
      renderValue={(option) => (
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-text">{option.label}</span>
          <span className="font-mono text-[11px] text-text-dim">{option.value}</span>
        </span>
      )}
    />
  );
}

// ---------------------------------------------------------------------------
// Quick pick presets
// ---------------------------------------------------------------------------

const QUICK_PICKS = [
  { label: "Now", detail: "current time", mins: 0 },
  { label: "5m", detail: "from now", mins: 5 },
  { label: "30m", detail: "from now", mins: 30 },
  { label: "1h", detail: "from now", mins: 60 },
  { label: "6h", detail: "from now", mins: 360 },
  { label: "Tomorrow", detail: "9:00 AM", mins: -1 },
  { label: "Next Mon", detail: "9:00 AM", mins: -2 },
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
  const [pos, setPos] = useState({ top: 0, left: 0, width: 390, bottom: 0, anchor: "bottom" as "bottom" | "top" });
  const ref = useRef<HTMLDivElement>(null);
  const display = useMemo(() => formatDisplay(value), [value]);

  const updatePosition = useCallback(() => {
    if (!ref.current || typeof window === "undefined") return;
    const rect = ref.current.getBoundingClientRect();
    const width = Math.min(390, window.innerWidth - 24);
    const left = Math.min(Math.max(12, rect.left), Math.max(12, window.innerWidth - width - 12));
    const popoverHeight = window.innerWidth < 640 ? 560 : 420;
    const spaceBelow = window.innerHeight - rect.bottom;
    const anchor = spaceBelow < Math.min(popoverHeight, window.innerHeight - 24) && rect.top > spaceBelow ? "top" : "bottom";
    setPos({
      top: rect.bottom + 6,
      left,
      width,
      bottom: window.innerHeight - rect.top + 6,
      anchor,
    });
  }, []);

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
    updatePosition();
    const onResize = () => updatePosition();
    const onScroll = () => updatePosition();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, updatePosition]);

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

  const selectedDateLabel = selectedDate
    ? selectedDate.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
    : "No date";
  const selectedTimeLabel = selectedDate ? formatTime12(toLocalInput(selectedDate).slice(11, 16)) : "No time";

  return (
    <div ref={ref} className="relative w-full">
      {/* Trigger button */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`w-full flex flex-row items-center gap-2 bg-input border rounded-md py-2 px-3 text-[13px] text-left cursor-pointer transition-colors ${
          open ? "border-accent/45 bg-surface-raised/70" : "border-input-border hover:border-surface-border"
        }`}
      >
        <Calendar size={14} className="text-text-dim shrink-0" />
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

      {open && typeof document !== "undefined" && createPortal(
        <>
          <div
            aria-hidden
            className="fixed inset-0"
            style={{ zIndex: 50000 }}
            onMouseDown={() => setOpen(false)}
          />
          <div
            className="fixed max-h-[calc(100dvh-24px)] overflow-x-hidden overflow-y-auto rounded-md border border-surface-border bg-surface-raised ring-1 ring-black/10"
            style={{
              ...(pos.anchor === "top"
                ? { bottom: pos.bottom, left: pos.left, width: pos.width }
                : { top: pos.top, left: pos.left, width: pos.width }),
              maxWidth: "calc(100vw - 24px)",
              zIndex: 50001,
            }}
            onMouseDown={(event) => event.stopPropagation()}
          >
          <div className="flex items-start justify-between gap-3 border-b border-surface-border/50 px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">Selected</div>
              <div className="mt-1 flex min-w-0 items-baseline gap-2">
                <span className="truncate text-[13px] font-semibold text-text">{selectedDateLabel}</span>
                <span className="shrink-0 font-mono text-[12px] text-text-muted">{selectedTimeLabel}</span>
              </div>
            </div>
            {value && (
              <button
                type="button"
                onClick={() => onChange("")}
                className="rounded-md bg-transparent px-2 py-1 text-[11px] font-medium text-text-dim transition-colors hover:bg-surface-overlay/45 hover:text-text"
              >
                Clear
              </button>
            )}
          </div>

          <div className="grid grid-cols-[1fr_112px] gap-0 max-sm:grid-cols-1">
            <div className="p-3">
              <div className="mb-2 flex flex-row items-center justify-between">
                <button
                  type="button"
                  onClick={prevMonth}
                  className="rounded-md bg-transparent p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
                >
                  <ChevronLeft size={14} />
                </button>
                <span className="text-xs font-semibold text-text">
                  {MONTH_NAMES[viewMonth]} {viewYear}
                </span>
                <button
                  type="button"
                  onClick={nextMonth}
                  className="rounded-md bg-transparent p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
                >
                  <ChevronRight size={14} />
                </button>
              </div>

              <div className="mb-0.5 grid grid-cols-7">
                {WEEKDAYS.map((wd) => (
                  <div key={wd} className="py-1 text-center text-[10px] font-medium text-text-dim">
                    {wd}
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-7 gap-px">
                {calendarDays.map((cd, i) => {
                  const isToday = sameDay(cd.date, now);
                  const isSelected = selectedDate ? sameDay(cd.date, selectedDate) : false;
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => selectDay(cd.date)}
                      className={`flex aspect-square w-full items-center justify-center rounded-md text-[11px] transition-colors ${
                        isSelected
                          ? "bg-accent/[0.10] text-accent font-semibold"
                          : isToday
                            ? "bg-transparent text-accent ring-1 ring-accent/45 hover:bg-accent/10"
                            : cd.isCurrentMonth
                              ? "bg-transparent text-text hover:bg-surface-overlay"
                              : "bg-transparent text-text-dim/30 hover:bg-surface-overlay/50"
                      }`}
                    >
                      {cd.date.getDate()}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="border-l border-surface-border/50 p-2.5 max-sm:border-l-0 max-sm:border-t">
              <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">Quick</div>
              <div className="flex flex-col gap-1">
                {QUICK_PICKS.map((qp) => (
                  <button
                    key={qp.label}
                    type="button"
                    onClick={() => handleQuickPick(qp.mins)}
                    className="rounded-md bg-transparent px-2 py-1.5 text-left transition-colors hover:bg-surface-overlay/45"
                  >
                    <span className="block text-[11px] font-semibold text-text-muted">{qp.label}</span>
                    <span className="block text-[9px] text-text-dim">{qp.detail}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex flex-row items-center gap-2 border-t border-surface-border/50 px-3 py-2.5">
            <Clock size={13} className="shrink-0 text-text-dim" />
            <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">Time</span>
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
              className="w-12 rounded-md border border-surface-border bg-input px-1.5 py-1 text-center font-mono text-xs text-text outline-none focus:border-accent/40"
            />
            <span className="text-xs font-bold text-text-dim">:</span>
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
              className="w-12 rounded-md border border-surface-border bg-input px-1.5 py-1 text-center font-mono text-xs text-text outline-none focus:border-accent/40"
            />
            <span className="ml-auto text-[11px] text-text-dim">{selectedTimeLabel}</span>
          </div>
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}
