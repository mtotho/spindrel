export function buildChatCancelRequest(target) {
    return {
        client_id: target.clientId ?? "",
        bot_id: target.botId,
        ...(target.channelId ? { channel_id: target.channelId } : {}),
        ...(target.sessionId ? { session_id: target.sessionId } : {}),
    };
}
