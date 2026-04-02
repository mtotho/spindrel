/** Pretty-print an integration type slug (e.g., "mission_control" → "Mission Control"). */
export function prettyIntegrationName(slug: string): string {
  const names: Record<string, string> = {
    slack: "Slack",
    github: "GitHub",
    discord: "Discord",
    gmail: "Gmail",
    frigate: "Frigate",
    mission_control: "Mission Control",
    arr: "Media Stack",
    claude_code: "Claude Code",
    bluebubbles: "BlueBubbles",
    ingestion: "Ingestion",
  };
  return names[slug] ?? slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const val = bytes / Math.pow(1024, i);
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}
