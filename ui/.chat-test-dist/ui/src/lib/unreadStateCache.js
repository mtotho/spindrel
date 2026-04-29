function newerTimestamp(a, b) {
    if (!a)
        return b;
    if (!b)
        return a;
    return Date.parse(a) >= Date.parse(b) ? a : b;
}
export function recomputeUnreadChannels(states) {
    const byChannel = new Map();
    for (const state of states) {
        const key = state.channel_id ?? "__none__";
        const existing = byChannel.get(key);
        if (!existing) {
            byChannel.set(key, {
                channel_id: state.channel_id,
                unread_agent_reply_count: state.unread_agent_reply_count,
                latest_unread_at: state.latest_unread_at,
            });
            continue;
        }
        existing.unread_agent_reply_count += state.unread_agent_reply_count;
        existing.latest_unread_at = newerTimestamp(existing.latest_unread_at, state.latest_unread_at);
    }
    return [...byChannel.values()];
}
export function mergeUnreadStateUpdates(current, updates) {
    if (!current || updates.length === 0)
        return current;
    const bySession = new Map(current.states.map((state) => [state.session_id, state]));
    for (const state of updates)
        bySession.set(state.session_id, state);
    const states = [...bySession.values()].sort((a, b) => {
        const at = Date.parse(a.latest_unread_at ?? a.first_unread_at ?? a.last_read_at ?? "") || 0;
        const bt = Date.parse(b.latest_unread_at ?? b.first_unread_at ?? b.last_read_at ?? "") || 0;
        return bt - at;
    });
    return {
        states,
        channels: recomputeUnreadChannels(states),
    };
}
