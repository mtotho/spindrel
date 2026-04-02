/**
 * Hash-based bot/channel color assignment.
 * Ported from ui/src/components/mission-control/botColors.ts.
 */

const BOT_COLORS = [
  { bg: "rgba(59,130,246,0.12)", dot: "#3b82f6" },
  { bg: "rgba(168,85,247,0.12)", dot: "#a855f7" },
  { bg: "rgba(236,72,153,0.12)", dot: "#ec4899" },
  { bg: "rgba(34,197,94,0.12)", dot: "#22c55e" },
  { bg: "rgba(6,182,212,0.12)", dot: "#06b6d4" },
  { bg: "rgba(99,102,241,0.12)", dot: "#6366f1" },
  { bg: "rgba(243,63,94,0.12)", dot: "#f43f5e" },
  { bg: "rgba(132,204,22,0.12)", dot: "#84cc16" },
  { bg: "rgba(249,115,22,0.12)", dot: "#f97316" },
  { bg: "rgba(234,179,8,0.12)", dot: "#eab308" },
];

function hashString(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash + s.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/** Full color entry (bg + dot) for a bot ID. */
export function botColor(botId: string) {
  return BOT_COLORS[hashString(botId) % BOT_COLORS.length];
}

/** Just the dot color for a bot ID. */
export function botDotColor(botId: string): string {
  return BOT_COLORS[hashString(botId) % BOT_COLORS.length].dot;
}

/** Dot color for a channel ID. */
export function channelColor(channelId: string): string {
  return BOT_COLORS[hashString(channelId) % BOT_COLORS.length].dot;
}
