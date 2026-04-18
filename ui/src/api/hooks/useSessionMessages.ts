import { useInfiniteQuery } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import { type MessagePage, PAGE_SIZE } from "@/app/(app)/channels/[channelId]/chatUtils";

/**
 * Session-scoped message fetch. Used by:
 *   - `useChannelChat` for the active channel session (indirectly, via its
 *     existing TanStack query — they share the ["session-messages", sid]
 *     cache key so both stay in sync).
 *   - The pipeline run-view modal (Phase 1) to mount ChatMessageArea on a
 *     task's `run_session_id` sub-session.
 *
 * Scoped to exactly ONE session_id — the server filters by
 * `Message.session_id == session_id`, so sub-session rows never leak into a
 * parent-session listing. That invariant is load-bearing for the
 * pipeline-as-chat model (sub-session noise stays inside the modal).
 */
export function useSessionMessages(sessionId: string | null | undefined) {
  return useInfiniteQuery({
    queryKey: ["session-messages", sessionId],
    queryFn: async ({ pageParam }) => {
      if (!sessionId) return { messages: [], has_more: false };
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (pageParam) params.set("before", pageParam);
      return apiFetch<MessagePage>(
        `/sessions/${sessionId}/messages?${params}`,
      );
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more || lastPage.messages.length === 0) return undefined;
      return lastPage.messages[0].id;
    },
    enabled: !!sessionId,
  });
}
