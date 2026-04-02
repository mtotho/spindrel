/**
 * Date formatting utilities for MC dashboard.
 * Ported from main UI journal + plan detail pages.
 */

/** "Today", "Yesterday", weekday name, or localized date. */
export function dateLabel(isoDate: string): string {
  const now = new Date();
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const yest = new Date(now);
  yest.setDate(yest.getDate() - 1);
  const yestStr = `${yest.getFullYear()}-${String(yest.getMonth() + 1).padStart(2, "0")}-${String(yest.getDate()).padStart(2, "0")}`;

  if (isoDate === todayStr) return "Today";
  if (isoDate === yestStr) return "Yesterday";

  const d = new Date(isoDate + "T12:00:00");
  const diffMs = now.getTime() - d.getTime();
  const diffDays = Math.round(diffMs / 86_400_000);
  if (diffDays < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** Relative time: "just now", "5m ago", "2h ago", "3d ago". */
export function timeAgo(isoDate: string): string {
  const ms = Date.now() - new Date(isoDate).getTime();
  if (ms < 0) return "just now";
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/** Duration between two ISO timestamps: "42s", "5m", "2m 30s", "1h", "2h 15m". */
export function formatDuration(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (ms < 0) return "";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (minutes < 60) return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}
