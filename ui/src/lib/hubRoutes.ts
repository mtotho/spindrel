import type { WorkspaceAttentionItem } from "../api/hooks/useWorkspaceAttention";

export const DAILY_HEALTH_HREF = "/hub/daily-health";
export const CONTEXT_BLOAT_HREF = "/hub/context-bloat";
export const MEMORY_CENTER_HREF = "/admin/learning#Memory";

export function attentionHubHref(itemId?: string | null): string {
  if (!itemId) return "/hub/attention";
  return `/hub/attention?item=${encodeURIComponent(itemId)}`;
}

export function attentionItemHref(item: Pick<WorkspaceAttentionItem, "id">): string {
  return attentionHubHref(item.id);
}

export function widgetPinHref(pinId: string): string {
  return `/widgets/pins/${encodeURIComponent(pinId)}`;
}

