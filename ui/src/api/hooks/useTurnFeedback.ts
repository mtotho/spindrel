import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export type FeedbackVote = "up" | "down";

export interface FeedbackResult {
  vote: FeedbackVote;
  comment: string | null;
  updated_at: string;
}

interface RecordArgs {
  messageId: string;
  vote: FeedbackVote;
  comment?: string | null;
  /** Session id is supplied so we can invalidate that session's message cache
   *  on success. The mutation itself only needs the message id. */
  sessionId: string;
}

interface ClearArgs {
  messageId: string;
  sessionId: string;
}

/** POST /api/v1/messages/{id}/feedback. */
export function useRecordTurnFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ messageId, vote, comment }: RecordArgs) =>
      apiFetch<FeedbackResult>(`/api/v1/messages/${messageId}/feedback`, {
        method: "POST",
        body: JSON.stringify({ vote, comment: comment ?? null }),
      }),
    onSuccess: (_data, { sessionId }) => {
      qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
    },
  });
}

/** DELETE /api/v1/messages/{id}/feedback. Idempotent. */
export function useClearTurnFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ messageId }: ClearArgs) =>
      apiFetch<void>(`/api/v1/messages/${messageId}/feedback`, {
        method: "DELETE",
      }),
    onSuccess: (_data, { sessionId }) => {
      qc.invalidateQueries({ queryKey: ["session-messages", sessionId] });
    },
  });
}
