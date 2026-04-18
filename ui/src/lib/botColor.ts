export const BOT_DOT_COLORS = [
  "#3b82f6", "#a855f7", "#ec4899", "#ef4444", "#f97316", "#eab308",
  "#22c55e", "#14b8a6", "#06b6d4", "#6366f1", "#f43f5e", "#84cc16",
];

export function botDotColor(botId: string): string {
  let hash = 0;
  for (let i = 0; i < botId.length; i++) {
    hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
  }
  return BOT_DOT_COLORS[Math.abs(hash) % BOT_DOT_COLORS.length];
}
