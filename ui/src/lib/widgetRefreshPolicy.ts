import type { ToolResultEnvelope, WidgetContract } from "../types/api";

export interface WidgetRefreshPolicyInput {
  refreshCapable: boolean;
  collapsed?: boolean;
  documentVisible?: boolean;
  elementVisible?: boolean;
  skipHtmlAutoRefresh?: boolean;
}

export interface PinnedWidgetLoadShellInput {
  hasRenderableBody: boolean;
  awaitingFirstPollForRefreshable?: boolean;
}

export interface PinnedWidgetRefreshOverlayInput {
  hasRenderableBody: boolean;
  awaitingFirstPollForRefreshable?: boolean;
}

export interface PinnedInitialRefreshInput {
  widgetId: string;
  refreshedForWidgetId: string | null;
  shouldRefreshOnMount: boolean;
}

export interface PinnedWidgetIframeSkeletonInput {
  isHtmlInteractive: boolean;
  iframeReady: boolean;
  preloadElapsedMs: number;
  preloadWatchdogMs: number;
}

export interface PinnedInteractiveIframeMountInput {
  isHtmlInteractive: boolean;
  hasEverBeenVisible: boolean;
}

export function isWidgetRefreshCapable(
  envelope: Pick<ToolResultEnvelope, "refreshable"> | null | undefined,
  contract?: Pick<WidgetContract, "refresh_model"> | null,
): boolean {
  return envelope?.refreshable === true || contract?.refresh_model === "state_poll";
}

export function shouldRunWidgetAutoRefresh(input: WidgetRefreshPolicyInput): boolean {
  if (!input.refreshCapable) return false;
  if (input.collapsed) return false;
  if (input.skipHtmlAutoRefresh) return false;
  if (input.documentVisible === false) return false;
  if (input.elementVisible === false) return false;
  return true;
}

export function shouldRenderPinnedWidgetLoadShell(input: PinnedWidgetLoadShellInput): boolean {
  return !input.hasRenderableBody;
}

export function shouldShowPinnedWidgetRefreshOverlay(input: PinnedWidgetRefreshOverlayInput): boolean {
  return !input.hasRenderableBody && !!input.awaitingFirstPollForRefreshable;
}

export function shouldSchedulePinnedInitialRefresh(input: PinnedInitialRefreshInput): boolean {
  return input.shouldRefreshOnMount && input.refreshedForWidgetId !== input.widgetId;
}

export function shouldShowPinnedWidgetIframeSkeleton(input: PinnedWidgetIframeSkeletonInput): boolean {
  if (!input.isHtmlInteractive) return false;
  if (input.iframeReady) return false;
  return input.preloadElapsedMs < input.preloadWatchdogMs;
}

export function shouldMountPinnedInteractiveIframe(input: PinnedInteractiveIframeMountInput): boolean {
  if (!input.isHtmlInteractive) return true;
  return input.hasEverBeenVisible;
}

export function widgetRefreshJitterMs(key: string, maxMs = 1_500): number {
  if (maxMs <= 0) return 0;
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % maxMs;
}
