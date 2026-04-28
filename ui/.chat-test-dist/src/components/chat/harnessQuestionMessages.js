export function isHarnessQuestionMessage(message) {
    return message.metadata?.kind === "harness_question";
}
export function isHarnessQuestionTransportMessage(message) {
    const meta = message.metadata ?? {};
    return meta.source === "harness_question" || (meta.hidden === true
        && typeof meta.harness_question_id === "string");
}
export function isPendingHarnessQuestionMessage(message, options) {
    const meta = message.metadata ?? {};
    return message.session_id === (options?.sessionId ?? message.session_id)
        && !options?.ignoredIds?.has(message.id)
        && meta.kind === "harness_question"
        && meta.harness_interaction?.status === "pending";
}
export function pendingHarnessQuestionTurnIds(messages) {
    const turnIds = new Set();
    for (const message of messages) {
        if (!isPendingHarnessQuestionMessage(message))
            continue;
        if (message.correlation_id)
            turnIds.add(message.correlation_id);
    }
    return turnIds;
}
