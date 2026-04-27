export interface ChatCancelTarget {
  botId: string;
  channelId?: string | null;
  clientId?: string | null;
  sessionId?: string | null;
}

export interface ChatCancelRequest {
  client_id: string;
  bot_id: string;
  channel_id?: string;
  session_id?: string;
}

export function buildChatCancelRequest(target: ChatCancelTarget): ChatCancelRequest {
  return {
    client_id: target.clientId ?? "",
    bot_id: target.botId,
    ...(target.channelId ? { channel_id: target.channelId } : {}),
    ...(target.sessionId ? { session_id: target.sessionId } : {}),
  };
}
