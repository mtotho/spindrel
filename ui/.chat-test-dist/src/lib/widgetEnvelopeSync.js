function stableSerialize(value) {
    if (value === null || typeof value !== "object") {
        return JSON.stringify(value);
    }
    if (Array.isArray(value)) {
        return `[${value.map((item) => stableSerialize(item)).join(",")}]`;
    }
    const entries = Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => `${JSON.stringify(key)}:${stableSerialize(item)}`);
    return `{${entries.join(",")}}`;
}
export function buildWidgetSyncSignature(toolName, widgetConfig) {
    return `${toolName}::${stableSerialize(widgetConfig ?? {})}`;
}
export function decidePinnedSharedEnvelopeUpdate(args) {
    const { currentToolName, currentSignature, currentEnvelope, incoming } = args;
    if (!currentEnvelope)
        return "ignore";
    if (incoming.sourceSignature === currentSignature) {
        return "adopt";
    }
    if (incoming.kind === "state_poll" && incoming.sourceToolName === currentToolName) {
        return "ignore";
    }
    if (!currentEnvelope.refreshable)
        return "ignore";
    return "refresh";
}
