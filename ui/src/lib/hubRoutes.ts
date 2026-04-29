import type { AttentionTargetKind, WorkspaceAttentionItem } from "../api/hooks/useWorkspaceAttention";

export const DAILY_HEALTH_HREF = "/hub/daily-health";
export const CONTEXT_BLOAT_HREF = "/hub/context-bloat";
export const MEMORY_CENTER_HREF = "/admin/learning#Memory";
export const ATTENTION_COMMAND_DECK_HREF = "/hub/attention";
export const COMMAND_CENTER_HREF = ATTENTION_COMMAND_DECK_HREF;

export type AttentionDeckMode = "review" | "inbox" | "runs" | "cleared";

export interface AttentionDeckHrefOptions {
  itemId?: string | null;
  channelId?: string | null;
  mode?: AttentionDeckMode | null;
  targetKind?: AttentionTargetKind | null;
  targetId?: string | null;
}

export function attentionDeckHref(options: AttentionDeckHrefOptions = {}): string {
  const params = new URLSearchParams();
  if (options.itemId) params.set("item", options.itemId);
  if (options.channelId) params.set("channel", options.channelId);
  if (options.mode) params.set("mode", options.mode);
  if (options.targetKind) params.set("target_kind", options.targetKind);
  if (options.targetId) params.set("target_id", options.targetId);
  const query = params.toString();
  return query ? `${ATTENTION_COMMAND_DECK_HREF}?${query}` : ATTENTION_COMMAND_DECK_HREF;
}

export function attentionHubHref(itemId?: string | null): string {
  return attentionDeckHref({ itemId });
}

export function attentionItemHref(item: Pick<WorkspaceAttentionItem, "id">): string {
  return attentionHubHref(item.id);
}

export function widgetPinHref(pinId: string): string {
  return `/widgets/pins/${encodeURIComponent(pinId)}`;
}
