import { memo } from "react";
import { CornerDownRight } from "lucide-react";
import type { Message } from "@/src/types/api";
import { MessageBubble } from "./MessageBubble";

interface Props {
  /** The Message being replied to. Null when the parent has been deleted
   *  (session.parent_message_id went NULL via ON DELETE SET NULL) or was
   *  never populated (Slack-initiated orphan thread). */
  message: Message | null;
}

/** Renders the parent message at the top of a thread view as a ghosted
 *  "Replying to …" anchor bubble. Pure render-time projection — no new
 *  Message rows, no store writes, no SSE. Forces interaction-off (no
 *  hover actions, no nested reply-in-thread button). */
export const ThreadParentAnchor = memo(function ThreadParentAnchor({
  message,
}: Props) {
  if (!message) {
    return (
      <div className="shrink-0 px-4 py-2.5">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-dim">
          <CornerDownRight size={11} />
          <span>Replying to a message that has been deleted</span>
        </div>
      </div>
    );
  }
  return (
    <div className="shrink-0 flex flex-col max-h-[40%] min-h-0">
      <div className="flex items-center gap-1.5 px-4 pt-2 text-[10px] uppercase tracking-wider text-text-dim shrink-0">
        <CornerDownRight size={11} />
        <span>Replying to</span>
      </div>
      <div className="opacity-90 overflow-y-auto min-h-0">
        <MessageBubble
          message={message}
          isGrouped={false}
          canReplyInThread={false}
          compact
        />
      </div>
    </div>
  );
});
