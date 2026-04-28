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
export function widgetRefreshJitterMs(key, maxMs = 1_500) {
    if (maxMs <= 0)
        return 0;
    let hash = 0;
    for (let i = 0; i < key.length; i += 1) {
        hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0;
    }
    return Math.abs(hash) % maxMs;
}
