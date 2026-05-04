import { memo, useCallback, useEffect, useRef, useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import type { FeedbackBlock } from "../../types/api";
import { useThemeTokens } from "../../theme/tokens";
import {
  useClearTurnFeedback,
  useRecordTurnFeedback,
  type FeedbackVote,
} from "../../api/hooks/useTurnFeedback";

interface Props {
  messageId: string;
  sessionId: string;
  feedback?: FeedbackBlock | null;
  /** Hide the affordance entirely. The channel toggle
   *  ``show_message_feedback === false`` flows in here. */
  hidden?: boolean;
}

/** Subtle hover-revealed thumbs up/down affordance.
 *
 * Layout note: the icon row is always rendered into the DOM so its width
 * doesn't shift layout when revealed. Opacity is the only thing that
 * changes on hover/focus, matching the rest of the meta strip.
 */
export const TurnFeedbackControls = memo(function TurnFeedbackControls({
  messageId,
  sessionId,
  feedback,
  hidden = false,
}: Props) {
  const t = useThemeTokens();
  const [optimistic, setOptimistic] = useState<FeedbackVote | null | undefined>(undefined);
  const [showComment, setShowComment] = useState(false);
  const [commentDraft, setCommentDraft] = useState("");
  const recordMutation = useRecordTurnFeedback();
  const clearMutation = useClearTurnFeedback();
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Reset optimistic state when the server-confirmed `mine` value catches up.
  useEffect(() => {
    if (feedback?.mine === optimistic) setOptimistic(undefined);
  }, [feedback?.mine, optimistic]);

  // Keep the comment draft in sync with the persisted comment when
  // the bubble re-renders after a successful save.
  useEffect(() => {
    if (!showComment) {
      setCommentDraft(feedback?.comment_mine ?? "");
    }
  }, [feedback?.comment_mine, showComment]);

  const effectiveMine = optimistic === undefined ? feedback?.mine ?? null : optimistic;

  const handleVote = useCallback(
    (next: FeedbackVote) => {
      if (effectiveMine === next) {
        setOptimistic(null);
        clearMutation.mutate(
          { messageId, sessionId },
          { onError: () => setOptimistic(undefined) },
        );
        setShowComment(false);
        setCommentDraft("");
        return;
      }
      setOptimistic(next);
      setShowComment(true);
      setCommentDraft(feedback?.comment_mine ?? "");
      recordMutation.mutate(
        { messageId, sessionId, vote: next, comment: feedback?.comment_mine ?? null },
        { onError: () => setOptimistic(undefined) },
      );
    },
    [clearMutation, effectiveMine, feedback?.comment_mine, messageId, recordMutation, sessionId],
  );

  const submitComment = useCallback(() => {
    if (!effectiveMine) return;
    const trimmed = commentDraft.trim();
    recordMutation.mutate({
      messageId,
      sessionId,
      vote: effectiveMine,
      comment: trimmed.length === 0 ? null : trimmed,
    });
    setShowComment(false);
  }, [commentDraft, effectiveMine, messageId, recordMutation, sessionId]);

  const cancelComment = useCallback(() => {
    setShowComment(false);
    setCommentDraft(feedback?.comment_mine ?? "");
  }, [feedback?.comment_mine]);

  if (hidden) return null;

  const baseColor = t.textMuted;
  const activeColor = t.text;

  const iconButton = (vote: FeedbackVote) => {
    const Icon = vote === "up" ? ThumbsUp : ThumbsDown;
    const isActive = effectiveMine === vote;
    const label = vote === "up"
      ? (isActive ? "Remove thumbs-up" : "Thumbs up")
      : (isActive ? "Remove thumbs-down" : "Thumbs down");
    return (
      <button
        type="button"
        aria-label={label}
        aria-pressed={isActive}
        onClick={(e) => {
          e.stopPropagation();
          handleVote(vote);
        }}
        className="inline-flex items-center justify-center rounded-sm transition-colors"
        style={{
          width: 18,
          height: 18,
          color: isActive ? activeColor : baseColor,
          background: "transparent",
          border: "none",
          cursor: "pointer",
          opacity: isActive ? 1 : undefined,
        }}
      >
        <Icon
          size={12}
          fill={isActive ? "currentColor" : "transparent"}
          strokeWidth={isActive ? 2 : 1.75}
        />
      </button>
    );
  };

  const placeholder = effectiveMine === "up" ? "what made this good?" : "what went wrong?";

  return (
    <span
      className="turn-feedback-controls inline-flex items-center"
      onClick={(e) => e.stopPropagation()}
    >
      <span className="inline-flex items-center gap-0.5">
        {iconButton("up")}
        {iconButton("down")}
      </span>
      {showComment && effectiveMine && (
        <span
          className="ml-2 inline-flex items-center gap-1"
          style={{ fontSize: 11 }}
        >
          <input
            ref={inputRef}
            type="text"
            autoFocus
            value={commentDraft}
            onChange={(e) => setCommentDraft(e.target.value)}
            placeholder={placeholder}
            maxLength={500}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submitComment();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancelComment();
              }
            }}
            onBlur={() => {
              // Save on blur if the value has changed; cheap UX, no extra button.
              if ((commentDraft.trim() || null) !== (feedback?.comment_mine ?? null)) {
                submitComment();
              } else {
                cancelComment();
              }
            }}
            style={{
              padding: "1px 6px",
              minWidth: 160,
              maxWidth: 280,
              background: "transparent",
              color: t.text,
              border: `1px solid ${t.overlayBorder}`,
              borderRadius: 4,
              outline: "none",
              fontSize: 11,
            }}
          />
        </span>
      )}
    </span>
  );
});
