/**
 * Format tool call arguments for display.
 * Accepts a JSON string and returns a pretty-printed version,
 * or null if there's nothing meaningful to show.
 */
export function formatToolArgs(args: string | undefined | null): string | null {
  if (!args) return null;
  try {
    const parsed = JSON.parse(args);
    if (typeof parsed === "object" && parsed !== null && Object.keys(parsed).length === 0) {
      return null;
    }
    return JSON.stringify(parsed, null, 2);
  } catch {
    // Not valid JSON — show raw if non-empty
    const trimmed = args.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
}
