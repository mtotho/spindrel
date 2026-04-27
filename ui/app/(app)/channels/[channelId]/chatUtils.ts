import { extractDisplayText } from "@/src/components/chat/messageUtils";
import type { Message } from "@/src/types/api";

export interface MessagePage {
  messages: Message[];
  has_more: boolean;
}

export const PAGE_SIZE = 100;

/** Should this message be grouped (compact, no avatar) with the previous? */
export function shouldGroup(current: Message, prev: Message | undefined): boolean {
  if (!prev) return false;
  if (current.role !== prev.role) return false;
  // Don't group bot response with preceding trigger card
  if (prev.role === "user" && (prev.metadata as any)?.trigger) return false;
  // Don't group across different senders (e.g. two different bots)
  const curSender = current.metadata?.sender_id ?? current.role;
  const prevSender = prev.metadata?.sender_id ?? prev.role;
  if (curSender !== prevSender) return false;
  const dt = new Date(current.created_at).getTime() - new Date(prev.created_at).getTime();
  return Math.abs(dt) < 5 * 60 * 1000; // 5 minutes
}

/** Format a date for the day separator: "Today", "Yesterday", or "Wed, Mar 26" */
export function formatDateSeparator(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = today.getTime() - msgDay.getTime();
  if (diff === 0) return "Today";
  if (diff === 86400000) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

/**
 * Collect the full text of a bot "turn" starting at the given index in inverted
 * (newest-first) data.  Returns undefined when the turn is a single message
 * (no concatenation needed).  For a multi-segment turn, the text is returned in
 * chronological (oldest-first) order.
 *
 * `index` should point at the turn header (non-grouped message with avatar).
 */
export function getTurnText(
  invertedData: Message[],
  index: number,
): string | undefined {
  const messages = getTurnMessages(invertedData, index);
  if (!messages || messages.length < 2) return undefined;
  return messages.map((message) => extractDisplayText(message.content)).join("\n\n");
}

/** Are two timestamps on different calendar days (local time)? */
export function isDifferentDay(a: string, b: string): boolean {
  const da = new Date(a);
  const db = new Date(b);
  return da.getFullYear() !== db.getFullYear() || da.getMonth() !== db.getMonth() || da.getDate() !== db.getDate();
}

/** Collect the grouped assistant rows for the response bundle at `index`.
 * Returns rows in chronological order (oldest-first), matching `getTurnText`. */
export function getTurnMessages(
  invertedData: Message[],
  index: number,
): Message[] | undefined {
  const header = invertedData[index];
  if (!header) return undefined;
  if (header.role !== "assistant") return undefined;
  const messages = [header];
  for (let i = index - 1; i >= 0; i--) {
    const msg = invertedData[i];
    if (!shouldGroup(msg, invertedData[i + 1])) break;
    messages.push(msg);
  }
  return messages;
}

export function stringifyTurnMessages(messages: Message[] | undefined): string | undefined {
  if (!messages?.length) return undefined;
  return JSON.stringify(messages, null, 2);
}
