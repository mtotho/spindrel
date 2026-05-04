import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export type FeedbackVote = "up" | "down";

export interface FeedbackReviewRow {
  correlation_id: string;
  channel_id: string;
  channel_name?: string | null;
  session_id: string;
  bot_id?: string | null;
  vote: FeedbackVote;
  comment?: string | null;
  source_integration: string;
  source_user_ref?: string | null;
  anonymous: boolean;
  user_id?: string | null;
  anchor_excerpt?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FeedbackReviewResponse {
  row_count: number;
  rows: FeedbackReviewRow[];
}

export interface FeedbackReviewParams {
  vote?: FeedbackVote | "";
  since_hours?: number;
  limit?: number;
}

export function useFeedbackReview(params: FeedbackReviewParams) {
  const qs = new URLSearchParams();
  if (params.vote) qs.set("vote", params.vote);
  if (params.since_hours) qs.set("since_hours", String(params.since_hours));
  if (params.limit) qs.set("limit", String(params.limit));
  const query = qs.toString();

  return useQuery({
    queryKey: ["admin-feedback-review", params],
    queryFn: () =>
      apiFetch<FeedbackReviewResponse>(`/api/v1/messages/feedback${query ? `?${query}` : ""}`),
  });
}
