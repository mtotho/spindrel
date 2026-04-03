import type { Message } from "@/src/types/api";

export interface MessagePage {
  messages: Message[];
  has_more: boolean;
}

export const PAGE_SIZE = 50;

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

/** Are two timestamps on different calendar days (local time)? */
export function isDifferentDay(a: string, b: string): boolean {
  const da = new Date(a);
  const db = new Date(b);
  return da.getFullYear() !== db.getFullYear() || da.getMonth() !== db.getMonth() || da.getDate() !== db.getDate();
}
