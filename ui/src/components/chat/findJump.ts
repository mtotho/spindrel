export type FindJumpStatus = "found" | "exhausted" | "busy";

export interface LoadUntilMessageVisibleOptions {
  findNode: () => HTMLElement | null;
  hasNextPage: () => boolean;
  isFetchingNextPage: () => boolean;
  loadMore: () => Promise<unknown> | void;
  afterLoad?: () => Promise<void> | void;
  maxLoads?: number;
}

export async function loadUntilMessageVisible({
  findNode,
  hasNextPage,
  isFetchingNextPage,
  loadMore,
  afterLoad,
  maxLoads = 20,
}: LoadUntilMessageVisibleOptions): Promise<FindJumpStatus> {
  if (findNode()) return "found";
  for (let i = 0; i < maxLoads; i += 1) {
    if (findNode()) return "found";
    if (!hasNextPage()) return "exhausted";
    if (isFetchingNextPage()) return "busy";
    await loadMore();
    await afterLoad?.();
  }
  return findNode() ? "found" : "exhausted";
}
