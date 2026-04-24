import { toast } from "@/src/stores/toast";
import type { SlashCommandFindResultsPayload } from "@/src/types/api";
import { SlashResultPanel } from "./SlashResultPanel";

/** Custom event the chat feed listens for to jump to a message. */
export const SCROLL_TO_MESSAGE_EVENT = "chat:scroll-to-message";

export interface ScrollToMessageDetail {
  messageId: string;
  sessionId?: string;
}

export function requestScrollToMessage(detail: ScrollToMessageDetail): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(SCROLL_TO_MESSAGE_EVENT, { detail }));
}

interface Props {
  payload: SlashCommandFindResultsPayload;
  chatMode?: "default" | "terminal";
}

export function FindResultsRenderer({ payload, chatMode = "default" }: Props) {
  const { query, matches, truncated } = payload;

  const handleClick = (messageId: string, sessionId: string) => {
    // Attempt scroll. If the DOM node isn't mounted (older scroll-back), the
    // listener in ChatMessageArea falls back to a toast — surfaced there so
    // we don't double-toast for mounted rows.
    requestScrollToMessage({ messageId, sessionId });
  };

  const meta =
    matches.length === 0
      ? "No matches"
      : `${matches.length}${truncated ? "+" : ""} match${matches.length === 1 ? "" : "es"}`;

  return (
    <SlashResultPanel
      chatMode={chatMode}
      commandLabel="/find"
      title={query}
      meta={meta}
      footer={truncated ? "More results available — refine the query to see them." : undefined}
    >
      {matches.length === 0 ? (
        <div className="px-3 py-4 text-xs text-text-dim">
          Nothing matched {query ? `"${query}"` : "that query"} in this channel.
          {query && (
            <>
              {" "}
              Try a shorter fragment — search is case-insensitive substring, not semantic.
            </>
          )}
        </div>
      ) : (
        <ul className="divide-y divide-surface-border/40">
          {matches.map((match) => (
            <li key={match.message_id}>
              <button
                type="button"
                onClick={() => handleClick(match.message_id, match.session_id)}
                className="w-full text-left px-3 py-2 hover:bg-surface-overlay/60 transition-colors duration-100 flex items-start gap-3"
              >
                <span className="text-[10px] uppercase tracking-[0.08em] text-text-dim/70 shrink-0 mt-0.5 min-w-[52px]">
                  {match.role}
                </span>
                <span className="text-xs text-text-muted line-clamp-2 flex-1">
                  {match.preview || "(empty message)"}
                </span>
                {match.created_at && (
                  <span className="text-[10px] text-text-dim shrink-0 mt-0.5">
                    {formatRelativeDate(match.created_at)}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </SlashResultPanel>
  );
}

function formatRelativeDate(iso: string): string {
  try {
    const then = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - then.getTime();
    const minutes = Math.round(diff / 60_000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h`;
    const days = Math.round(hours / 24);
    if (days < 7) return `${days}d`;
    return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

/** Imperative fallback shown when the targeted message isn't mounted.
 *  Emitted by ChatMessageArea when it can't find the DOM node.
 */
export function notifyScrollMiss() {
  toast({
    kind: "info",
    message: "Scroll up to load older messages — target isn't in view yet.",
  });
}
