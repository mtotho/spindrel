/**
 * Centralized time formatting utilities.
 *
 * All display functions convert UTC server timestamps to the browser's local timezone.
 * All "send to server" functions include the browser's timezone offset so the server
 * doesn't have to guess.
 */

/** Format a time for display — e.g. "2:30 PM EST" */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/** Format a compact time for chat — includes date context for older messages.
 *  Today: "2:30 PM", Yesterday: "Yesterday 2:30 PM", Older: "Mar 26, 2:30 PM" */
export function formatTimeShort(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = today.getTime() - msgDay.getTime();
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (diff === 0) return time;
  if (diff === 86400000) return `Yesterday ${time}`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + `, ${time}`;
}

/** Format a datetime for display — e.g. "Mar 26, 2:30 PM EST" */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/** Format a date only — e.g. "Wed, Mar 26" */
export function formatDate(d: Date): string {
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** Get the browser's timezone abbreviation — e.g. "EST", "PDT" */
export function getTimezoneAbbr(): string {
  return (
    new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
      .formatToParts(new Date())
      .find((p) => p.type === "timeZoneName")?.value || ""
  );
}

/**
 * Convert a naive `datetime-local` input value to an ISO string WITH the browser's
 * timezone offset, so the server parses it correctly regardless of server TIMEZONE setting.
 *
 * Pass-through for relative offsets (+30m, +1d) and empty strings.
 *
 * "2025-03-26T14:30" → "2025-03-26T14:30:00-04:00" (if browser is in EDT)
 */
export function localInputToISO(value: string): string {
  if (!value || /^\+\d+[smhd]$/.test(value)) return value;
  // datetime-local gives "YYYY-MM-DDTHH:MM" — parse it as local time
  const d = new Date(value);
  if (isNaN(d.getTime())) return value; // unparseable, pass through
  const offset = -d.getTimezoneOffset(); // minutes east of UTC
  const sign = offset >= 0 ? "+" : "-";
  const hh = String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0");
  const mm = String(Math.abs(offset) % 60).padStart(2, "0");
  return `${value}:00${sign}${hh}:${mm}`;
}

/**
 * Convert a UTC ISO string to a `datetime-local` compatible value in the browser's
 * local timezone. Used when loading server timestamps into datetime-local inputs.
 *
 * "2025-03-26T18:30:00+00:00" → "2025-03-26T14:30" (if browser is in EDT)
 */
/** Format time with seconds — e.g. "2:30:15 PM" (no timezone, for log entries) */
export function formatTimeCompact(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Format a short date — e.g. "Mar 26" */
export function formatDateShort(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
}

/** Format a duration in ms — e.g. "1.2s" or "450ms" */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Format a token count — e.g. "1.2k" or "450" */
export function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${mo}-${da}T${h}:${mi}`;
}
