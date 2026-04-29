export function resolveChatModeFromStyleResult(result) {
    if (result.command_id !== "style")
        return null;
    const payload = result.payload ?? {};
    const direct = typeof payload.chat_mode === "string"
        ? payload.chat_mode
        : typeof payload.style === "string"
            ? payload.style
            : null;
    const source = direct ?? `${payload.title ?? ""} ${payload.detail ?? ""} ${result.fallback_text ?? ""}`;
    const match = source.match(/\b(default|terminal)\b/i);
    if (!match)
        return null;
    const mode = match[1].toLowerCase();
    return mode === "default" || mode === "terminal" ? mode : null;
}
export function applyChatStyleSideEffect(queryClient, channelId, result) {
    if (!channelId)
        return;
    const mode = resolveChatModeFromStyleResult(result);
    if (!mode) {
        queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
        queryClient.invalidateQueries({ queryKey: ["channels"] });
        return;
    }
    queryClient.setQueryData(["channels", channelId], (old) => {
        if (!old)
            return old;
        const config = { ...(old.config ?? {}) };
        if (mode === "default") {
            delete config.chat_mode;
        }
        else {
            config.chat_mode = mode;
        }
        return { ...old, config };
    });
    queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
    queryClient.invalidateQueries({ queryKey: ["channels"] });
}
