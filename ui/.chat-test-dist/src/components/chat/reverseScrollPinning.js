export function preserveReverseScrollPositionOnBottomGrowth({ scrollTop, previousBottomHeight, nextBottomHeight, atBottomThreshold = 4, }) {
    const delta = nextBottomHeight - previousBottomHeight;
    if (delta <= 0)
        return scrollTop;
    if (Math.abs(scrollTop) <= atBottomThreshold)
        return scrollTop;
    return scrollTop - delta;
}
export function localUserMessageScrollKey(message) {
    if (!message || message.role !== "user")
        return null;
    const meta = message.metadata ?? {};
    const clientLocalId = typeof meta.client_local_id === "string" ? meta.client_local_id : null;
    if (clientLocalId)
        return clientLocalId;
    const localStatus = typeof meta.local_status === "string" ? meta.local_status : null;
    if (localStatus === "sending" || localStatus === "queued")
        return message.id;
    if (meta.source === "web" && meta.sender_type === "human")
        return message.id;
    return null;
}
