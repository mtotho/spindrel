export function buildSlashCommandExecuteBody({ commandId, surface, channelId, sessionId, args = [], }) {
    if (surface === "channel") {
        if (!channelId)
            return null;
        return {
            command_id: commandId,
            channel_id: channelId,
            session_id: null,
            surface: "web",
            args,
        };
    }
    if (!sessionId)
        return null;
    return {
        command_id: commandId,
        channel_id: null,
        session_id: sessionId,
        surface: "web",
        args,
    };
}
