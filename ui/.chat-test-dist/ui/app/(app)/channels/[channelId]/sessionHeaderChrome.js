export function resolveHeaderMetrics(contextBudget, sessionHeaderStats) {
    const total = contextBudget?.total ?? sessionHeaderStats?.totalTokens ?? null;
    const gross = contextBudget?.gross
        ?? sessionHeaderStats?.grossPromptTokens
        ?? sessionHeaderStats?.consumedTokens
        ?? contextBudget?.consumed
        ?? null;
    const current = contextBudget?.current ?? sessionHeaderStats?.currentPromptTokens ?? gross;
    const hasAnyTokenUsage = typeof gross === "number" || typeof current === "number" || typeof total === "number";
    return {
        utilization: contextBudget?.utilization ?? sessionHeaderStats?.utilization ?? null,
        total,
        gross,
        current,
        cached: contextBudget?.cached ?? sessionHeaderStats?.cachedPromptTokens ?? null,
        completion: sessionHeaderStats?.completionTokens ?? null,
        contextProfile: contextBudget?.contextProfile ?? sessionHeaderStats?.contextProfile ?? null,
        turnsInContext: sessionHeaderStats?.turnsInContext ?? null,
        turnsUntilCompaction: sessionHeaderStats?.turnsUntilCompaction ?? null,
        hasTokenMetrics: typeof total === "number" && total > 0 && typeof gross === "number" && gross >= 0,
        hasAnyTokenUsage,
    };
}
function compactSessionTitle(raw) {
    const trimmed = raw?.trim().replace(/\s+/g, " ") || null;
    if (!trimmed)
        return null;
    if (trimmed.length <= 56)
        return trimmed;
    return `${trimmed.slice(0, 53).trimEnd()}...`;
}
export function resolveRouteSessionChrome(isSessionRoute, sessionTitle, lastActiveLabel) {
    const trimmedTitle = compactSessionTitle(sessionTitle);
    const trimmedMeta = lastActiveLabel?.trim() || null;
    if (!isSessionRoute) {
        return {
            modeLabel: "Primary",
            inlineTitle: null,
            inlineMeta: null,
            subtitleIdentity: null,
        };
    }
    return {
        modeLabel: "Session",
        inlineTitle: trimmedTitle,
        inlineMeta: trimmedMeta,
        subtitleIdentity: trimmedTitle || trimmedMeta ? null : "session",
    };
}
