import type { Message } from "../../types/api";

type MessageLike = Pick<Message, "correlation_id" | "metadata" | "session_id" | "id">;

export function isHarnessQuestionMessage(message: Pick<Message, "metadata">): boolean {
  return message.metadata?.kind === "harness_question";
}

export function isHarnessQuestionTransportMessage(message: Pick<Message, "metadata">): boolean {
  const meta = message.metadata ?? {};
  return meta.source === "harness_question" || meta.hidden === true;
}

export function isPendingHarnessQuestionMessage(
  message: MessageLike,
  options?: {
    sessionId?: string | null;
    ignoredIds?: Set<string>;
  },
): boolean {
  const meta = message.metadata ?? {};
  return message.session_id === (options?.sessionId ?? message.session_id)
    && !options?.ignoredIds?.has(message.id)
    && meta.kind === "harness_question"
    && (meta.harness_interaction as { status?: string } | undefined)?.status === "pending";
}

export function pendingHarnessQuestionTurnIds(messages: MessageLike[]): Set<string> {
  const turnIds = new Set<string>();
  for (const message of messages) {
    if (!isPendingHarnessQuestionMessage(message)) continue;
    if (message.correlation_id) turnIds.add(message.correlation_id);
  }
  return turnIds;
}
