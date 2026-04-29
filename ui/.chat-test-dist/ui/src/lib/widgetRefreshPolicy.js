export function isWidgetRefreshCapable(envelope, contract) {
    return envelope?.refreshable === true || contract?.refresh_model === "state_poll";
}
export function shouldRunWidgetAutoRefresh(input) {
    if (!input.refreshCapable)
        return false;
    if (input.collapsed)
        return false;
    if (input.skipHtmlAutoRefresh)
        return false;
    if (input.documentVisible === false)
        return false;
    if (input.elementVisible === false)
        return false;
    return true;
}
export function shouldRenderPinnedWidgetLoadShell(input) {
    return !input.hasRenderableBody;
}
export function shouldShowPinnedWidgetRefreshOverlay(input) {
    return !input.hasRenderableBody && !!input.awaitingFirstPollForRefreshable;
}
export function shouldSchedulePinnedInitialRefresh(input) {
    return input.shouldRefreshOnMount && input.refreshedForWidgetId !== input.widgetId;
}
export function shouldShowPinnedWidgetIframeSkeleton(input) {
    if (!input.isHtmlInteractive)
        return false;
    if (input.iframeReady)
        return false;
    return input.preloadElapsedMs < input.preloadWatchdogMs;
}
export function widgetRefreshJitterMs(key, maxMs = 1_500) {
    if (maxMs <= 0)
        return 0;
    let hash = 0;
    for (let i = 0; i < key.length; i += 1) {
        hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0;
    }
    return Math.abs(hash) % maxMs;
}
