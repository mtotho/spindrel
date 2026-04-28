import type { Message } from "../../types/api.js";

export function preserveReverseScrollPositionOnBottomGrowth({
  scrollTop,
  previousBottomHeight,
  nextBottomHeight,
  atBottomThreshold = 4,
}: {
  scrollTop: number;
  previousBottomHeight: number;
  nextBottomHeight: number;
  atBottomThreshold?: number;
}): number {
  const delta = nextBottomHeight - previousBottomHeight;
  if (delta <= 0) return scrollTop;
  if (Math.abs(scrollTop) <= atBottomThreshold) return scrollTop;
  return scrollTop - delta;
}

export function localUserMessageScrollKey(message: Pick<Message, "id" | "role" | "metadata"> | null | undefined): string | null {
  if (!message || message.role !== "user") return null;
  const meta = message.metadata ?? {};
  const clientLocalId = typeof meta.client_local_id === "string" ? meta.client_local_id : null;
  if (clientLocalId) return clientLocalId;

  const localStatus = typeof meta.local_status === "string" ? meta.local_status : null;
  if (localStatus === "sending" || localStatus === "queued") return message.id;

  if (meta.source === "web" && meta.sender_type === "human") return message.id;
  return null;
}
