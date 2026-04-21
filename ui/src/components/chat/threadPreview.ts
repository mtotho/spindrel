import type { Message } from "@/src/types/api";

const THREAD_PARENT_PREVIEW_KIND = "thread_parent_preview";

export function isThreadParentPreviewMessage(message: Message): boolean {
  const meta = (message.metadata ?? {}) as Record<string, unknown>;
  return meta.kind === THREAD_PARENT_PREVIEW_KIND;
}

export function getThreadParentPreviewMessage(message: Message): Message | null {
  const meta = (message.metadata ?? {}) as Record<string, unknown>;
  const parent = meta.parent_message;
  if (!parent || typeof parent !== "object") return null;
  return parent as Message;
}

export function buildThreadParentPreviewRow(
  sessionId: string,
  parentMessage: Message | null,
): Message {
  const createdAt = parentMessage?.created_at ?? new Date(0).toISOString();
  return {
    id: `thread-parent-preview:${parentMessage?.id ?? "deleted"}`,
    session_id: sessionId,
    role: "system",
    content: "",
    created_at: createdAt,
    metadata: {
      kind: THREAD_PARENT_PREVIEW_KIND,
      ui_only: true,
      parent_message: parentMessage,
    },
  };
}
