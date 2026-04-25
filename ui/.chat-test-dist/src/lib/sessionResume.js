export const SESSION_RESUME_IDLE_MS = 2 * 60 * 60 * 1000;
export function getNewestVisibleMessageAt(messages) {
    let newestMs = Number.NEGATIVE_INFINITY;
    let newest = null;
    for (const message of messages) {
        if (message.role !== "user" && message.role !== "assistant")
            continue;
        const metadata = message.metadata ?? {};
        if (metadata.kind === "task_run" ||
            metadata.kind === "thread_parent_preview" ||
            metadata.kind === "slash_command_result")
            continue;
        if (metadata.synthetic === true || metadata.ui_only === true)
            continue;
        const createdAt = message.created_at;
        if (!createdAt)
            continue;
        const ms = Date.parse(createdAt);
        if (!Number.isFinite(ms))
            continue;
        if (ms > newestMs) {
            newestMs = ms;
            newest = createdAt;
        }
    }
    return newest;
}
export function sessionResumeDismissKey(sessionId, lastVisibleMessageAt) {
    if (!sessionId || !lastVisibleMessageAt)
        return null;
    return `${sessionId}:${lastVisibleMessageAt}`;
}
export function shouldShowSessionResumeCard({ metadata, enabled, dismissed, isActive, nowMs, idleMs = SESSION_RESUME_IDLE_MS, }) {
    if (!enabled || dismissed || isActive || !metadata)
        return false;
    if (!metadata.sessionId || !metadata.lastVisibleMessageAt)
        return false;
    if ((metadata.messageCount ?? 1) <= 0)
        return false;
    const lastMs = Date.parse(metadata.lastVisibleMessageAt);
    if (!Number.isFinite(lastMs))
        return false;
    return nowMs - lastMs >= idleMs;
}
export function formatSessionSurfaceLabel(kind) {
    switch (kind) {
        case "primary":
            return "Primary session";
        case "scratch":
            return "Scratch session";
        case "thread":
            return "Thread session";
        case "channel":
            return "Previous chat";
        default:
            return "Session";
    }
}
export function compactSessionId(sessionId) {
    if (sessionId.length <= 13)
        return sessionId;
    return `${sessionId.slice(0, 8)}...${sessionId.slice(-4)}`;
}
