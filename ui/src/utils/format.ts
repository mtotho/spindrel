/** Pretty-print an integration type slug (e.g., "google_workspace" → "Google Workspace"). */
export function prettyIntegrationName(slug: string): string {
  const names: Record<string, string> = {
    slack: "Slack",
    github: "GitHub",
    discord: "Discord",
    gmail: "Gmail",
    frigate: "Frigate",
    arr: "Media Stack",
    bluebubbles: "BlueBubbles",
    ingestion: "Ingestion",
  };
  return names[slug] ?? slug.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const val = bytes / Math.pow(1024, i);
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

/**
 * Short relative timestamp for tiles: "5m", "2h", "3d", "4w".
 * Empty string for null/invalid input or timestamps in the future.
 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const diffMs = Date.now() - t;
  if (diffMs < 0) return "";
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return "now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d`;
  const wk = Math.floor(day / 7);
  if (wk < 52) return `${wk}w`;
  const yr = Math.floor(day / 365);
  return `${yr}y`;
}
