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

/** Format a compact time — e.g. "2:30 PM" (no timezone, for tight spaces like chat) */
export function formatTimeShort(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
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
