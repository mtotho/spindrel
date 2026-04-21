import { memo } from "react";
import { MessageCircle, ChevronRight } from "lucide-react";
import { cn } from "@/src/lib/cn";
import type { ThreadSummary } from "@/src/api/hooks/useThreads";

export interface ThreadAnchorProps {
  summary: ThreadSummary;
  onOpen: () => void;
}

/**
 * Compact card rendered beneath a parent message when a thread has been
 * spawned on it. Mirrors the look of ``SubSessionAnchor`` so every
 * "there's a side conversation here" affordance reads the same.
 */
export const ThreadAnchor = memo(function ThreadAnchor({
  summary,
  onOpen,
}: ThreadAnchorProps) {
  const { reply_count, bot_name, last_reply_preview } = summary;
  const plural = reply_count === 1 ? "reply" : "replies";

  return (
    <div className="mx-5 my-1.5">
      <button
        onClick={onOpen}
        className={cn(
          "group w-full flex items-center gap-3 px-3.5 py-2.5 rounded-lg",
          "bg-surface-raised border border-surface-border",
          "hover:border-accent/40 hover:bg-surface-raised/80 transition-colors",
          "text-left",
        )}
      >
        <MessageCircle size={14} className="text-accent shrink-0" />
        <span className="flex-1 min-w-0 flex items-center gap-2">
          <span className="text-xs font-semibold text-text shrink-0">
            Thread
          </span>
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-text-dim shrink-0">
            <span>
              {reply_count} {plural}
            </span>
            {bot_name && <span>· @{bot_name}</span>}
          </span>
          {last_reply_preview && (
            <span className="truncate text-[11px] text-text-muted italic">
              {last_reply_preview}
            </span>
          )}
        </span>
        <span className="shrink-0 inline-flex items-center gap-1 text-[11px] font-medium text-accent/80 group-hover:text-accent">
          Open
          <ChevronRight
            size={12}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </button>
    </div>
  );
});
