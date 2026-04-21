import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Message } from "@/src/types/api";
import { apiFetch } from "../client";

interface SpawnThreadRequest {
  message_id: string;
  bot_id?: string;
}

interface SpawnThreadResponse {
  session_id: string;
  parent_message_id: string;
  bot_id: string;
  session_type: "thread";
}

/** Spawn a thread session anchored at a parent message. */
export function useSpawnThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ message_id, bot_id }: SpawnThreadRequest) =>
      apiFetch<SpawnThreadResponse>(
        `/api/v1/messages/${encodeURIComponent(message_id)}/thread`,
        {
          method: "POST",
          body: JSON.stringify(bot_id ? { bot_id } : {}),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["thread-summaries"] });
    },
  });
}

export interface ThreadSummary {
  session_id: string;
  bot_id: string;
  bot_name: string | null;
  reply_count: number;
  last_reply_preview: string | null;
  last_reply_at: string | null;
}

export type ThreadSummaryMap = Record<string, ThreadSummary>;

/** Batched fetch of thread summaries for a set of message ids.
 *
 * Returns a map keyed by message_id. Only messages that have at least one
 * thread session appear in the result, so call sites can render a
 * ThreadAnchor when the map has an entry for the message they're drawing.
 */
export interface ThreadInfo {
  session_id: string;
  bot_id: string;
  bot_name: string | null;
  parent_message_id: string | null;
  parent_channel_id: string | null;
  parent_message_preview: string | null;
  parent_message_role: string | null;
  parent_message: Message | null;
}

/** Lookup thread metadata from a thread session id.
 *
 * Used by the full-screen thread route so a direct URL navigation (bookmark
 * / refresh) can render the "Replying to …" header without the spawn
 * response in memory.
 */
export function useThreadInfo(sessionId: string | undefined) {
  return useQuery<ThreadInfo>({
    queryKey: ["thread-info", sessionId],
    enabled: !!sessionId,
    staleTime: 60_000,
    queryFn: () =>
      apiFetch<ThreadInfo>(
        `/api/v1/messages/thread/${encodeURIComponent(sessionId!)}`,
      ),
  });
}

export function useThreadSummaries(messageIds: string[]) {
  const sortedIds = [...messageIds].sort();
  const key = sortedIds.join(",");
  return useQuery<ThreadSummaryMap>({
    queryKey: ["thread-summaries", key],
    enabled: sortedIds.length > 0,
    staleTime: 15_000,
    queryFn: () =>
      apiFetch<ThreadSummaryMap>(
        `/api/v1/messages/thread-summaries?message_ids=${encodeURIComponent(key)}`,
      ),
  });
}
