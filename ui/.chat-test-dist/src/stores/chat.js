import { create } from "zustand";
const emptyChannel = {
    messages: [],
    turns: {},
    isProcessing: false,
    queuedTaskId: null,
    error: null,
    secretWarning: null,
    contextBudget: null,
};
function makeToolCallId(turnId, existingCount) {
    return `${turnId}:tool:${existingCount + 1}`;
}
function emptyAssistantTurnBody() {
    return { version: 1, items: [] };
}
function cloneAssistantTurnBody(body) {
    if (!body)
        return emptyAssistantTurnBody();
    return {
        version: 1,
        items: body.items.map((item) => ({ ...item })),
    };
}
function appendTextEntry(body, delta) {
    if (!delta)
        return body;
    const next = cloneAssistantTurnBody(body);
    const last = next.items[next.items.length - 1];
    if (last?.kind === "text") {
        next.items[next.items.length - 1] = { ...last, text: last.text + delta };
        return next;
    }
    next.items.push({ id: `text:${next.items.length + 1}`, kind: "text", text: delta });
    return next;
}
function appendToolEntry(body, toolCallId) {
    const next = cloneAssistantTurnBody(body);
    next.items.push({
        id: `tool:${toolCallId}`,
        kind: "tool_call",
        toolCallId,
    });
    return next;
}
function seedAssistantTurnBodyFromToolCalls(toolCalls) {
    return {
        version: 1,
        items: toolCalls.map((toolCall) => ({
            id: `tool:${toolCall.id}`,
            kind: "tool_call",
            toolCallId: toolCall.id,
        })),
    };
}
function toPersistedAssistantTurnBody(body) {
    return body.items.length > 0 ? cloneAssistantTurnBody(body) : undefined;
}
function toPersistedToolCall(toolCall) {
    return {
        id: toolCall.id,
        name: toolCall.name,
        arguments: toolCall.args ?? "{}",
        ...(toolCall.surface ? { surface: toolCall.surface } : {}),
        ...(toolCall.summary ? { summary: toolCall.summary } : {}),
    };
}
export const useChatStore = create()((set, get) => ({
    channels: {},
    getChannel: (channelId) => get().channels[channelId] ?? emptyChannel,
    setMessages: (channelId, messages) => set((s) => ({
        channels: {
            ...s.channels,
            [channelId]: { ...(s.channels[channelId] ?? emptyChannel), messages },
        },
    })),
    addMessage: (channelId, message) => set((s) => {
        const ch = s.channels[channelId] ?? emptyChannel;
        return {
            channels: {
                ...s.channels,
                [channelId]: { ...ch, messages: [...ch.messages, message] },
            },
        };
    }),
    upsertMessage: (channelId, message) => set((s) => {
        const ch = s.channels[channelId] ?? emptyChannel;
        const existingIndex = ch.messages.findIndex((current) => current.id === message.id);
        if (existingIndex < 0) {
            return {
                channels: {
                    ...s.channels,
                    [channelId]: { ...ch, messages: [...ch.messages, message] },
                },
            };
        }
        const nextMessages = [...ch.messages];
        nextMessages[existingIndex] = message;
        return {
            channels: {
                ...s.channels,
                [channelId]: { ...ch, messages: nextMessages },
            },
        };
    }),
    startTurn: (channelId, turnId, botId, botName, isPrimary) => set((s) => {
        const ch = s.channels[channelId] ?? emptyChannel;
        // Idempotent: if a turn with this id already exists (e.g. SSE
        // replay after reconnect), keep the existing slot.
        if (ch.turns[turnId])
            return s;
        return {
            channels: {
                ...s.channels,
                [channelId]: {
                    ...ch,
                    turns: {
                        ...ch.turns,
                        [turnId]: {
                            botId,
                            botName,
                            isPrimary,
                            streamingContent: "",
                            thinkingContent: "",
                            toolCalls: [],
                            assistantTurnBody: emptyAssistantTurnBody(),
                            autoInjectedSkills: [],
                            correlationId: turnId,
                            startedAt: Date.now(),
                            lastEventAt: Date.now(),
                            llmStatus: null,
                        },
                    },
                    // A new turn implies the channel is no longer in the
                    // queued/processing intermediate state.
                    isProcessing: false,
                    queuedTaskId: null,
                    error: null,
                },
            },
        };
    }),
    rehydrateTurn: (channelId, turnId, botId, botName, isPrimary, toolCalls, autoInjectedSkills) => set((s) => {
        const ch = s.channels[channelId] ?? emptyChannel;
        const existing = ch.turns[turnId];
        const hydratedToolCalls = toolCalls.map((toolCall, index) => ({
            ...toolCall,
            id: toolCall.id || makeToolCallId(turnId, index),
        }));
        // Live SSE state wins — a stale snapshot must not overwrite fresher
        // deltas. Only seed if the slot is absent or has no tool/skill state yet.
        if (existing && (existing.toolCalls.length > 0 || existing.autoInjectedSkills.length > 0)) {
            return s;
        }
        return {
            channels: {
                ...s.channels,
                [channelId]: {
                    ...ch,
                    turns: {
                        ...ch.turns,
                        [turnId]: {
                            botId,
                            botName,
                            isPrimary,
                            streamingContent: existing?.streamingContent ?? "",
                            thinkingContent: existing?.thinkingContent ?? "",
                            toolCalls: hydratedToolCalls,
                            assistantTurnBody: existing?.assistantTurnBody.items.length
                                ? existing.assistantTurnBody
                                : seedAssistantTurnBodyFromToolCalls(hydratedToolCalls),
                            autoInjectedSkills,
                            correlationId: turnId,
                            startedAt: existing?.startedAt ?? Date.now(),
                            lastEventAt: existing?.lastEventAt ?? Date.now(),
                            llmStatus: existing?.llmStatus ?? null,
                        },
                    },
                    isProcessing: false,
                    queuedTaskId: null,
                },
            },
        };
    }),
    handleTurnEvent: (channelId, turnId, event) => set((s) => {
        const ch = s.channels[channelId] ?? emptyChannel;
        const turn = ch.turns[turnId];
        if (!turn)
            return s;
        let updated;
        switch (event.event) {
            case "text_delta": {
                const data = event.data;
                const delta = data.delta ?? "";
                updated = {
                    ...turn,
                    streamingContent: turn.streamingContent + delta,
                    assistantTurnBody: appendTextEntry(turn.assistantTurnBody, delta),
                    llmStatus: null, // Clear retry status — actual content is flowing
                };
                break;
            }
            case "thinking": {
                const data = event.data;
                updated = {
                    ...turn,
                    thinkingContent: turn.thinkingContent + (data.delta ?? ""),
                };
                break;
            }
            case "thinking_content": {
                const data = event.data;
                updated = { ...turn, thinkingContent: data.text ?? turn.thinkingContent };
                break;
            }
            case "assistant_text": {
                // Don't replace — text_deltas already accumulated the canonical content.
                const data = event.data;
                const text = data.text || "";
                const shouldSeedTranscript = !turn.streamingContent && text;
                updated = {
                    ...turn,
                    streamingContent: turn.streamingContent || text,
                    assistantTurnBody: shouldSeedTranscript ? appendTextEntry(turn.assistantTurnBody, text) : turn.assistantTurnBody,
                };
                break;
            }
            case "response": {
                // Fallback for non-streaming providers. Don't replace if deltas
                // already populated streamingContent.
                const data = event.data;
                const text = data.text || "";
                const shouldSeedTranscript = !turn.streamingContent && text;
                updated = {
                    ...turn,
                    streamingContent: turn.streamingContent || text,
                    assistantTurnBody: shouldSeedTranscript ? appendTextEntry(turn.assistantTurnBody, text) : turn.assistantTurnBody,
                };
                break;
            }
            case "tool_start": {
                const data = event.data;
                const toolCall = {
                    id: data.tool_call_id || makeToolCallId(turnId, turn.toolCalls.length),
                    name: data.tool ?? "unknown",
                    args: data.args,
                    surface: data.surface,
                    summary: data.summary ?? null,
                    status: "running",
                };
                updated = {
                    ...turn,
                    toolCalls: [...turn.toolCalls, toolCall],
                    assistantTurnBody: appendToolEntry(turn.assistantTurnBody, toolCall.id),
                };
                break;
            }
            case "tool_result": {
                const data = event.data;
                const tcs = [...turn.toolCalls];
                let idx = -1;
                if (data.tool_call_id) {
                    idx = tcs.findIndex((toolCall) => toolCall.id === data.tool_call_id);
                }
                if (idx < 0) {
                    // Legacy fallback for older publishers that didn't include the canonical id.
                    for (let i = tcs.length - 1; i >= 0; i--) {
                        if (tcs[i].status === "running" && (!data.tool || tcs[i].name === data.tool)) {
                            idx = i;
                            break;
                        }
                    }
                }
                if (idx >= 0) {
                    tcs[idx] = {
                        ...tcs[idx],
                        status: "done",
                        isError: data.is_error || tcs[idx].isError,
                        envelope: data.envelope ?? tcs[idx].envelope,
                        surface: data.surface ?? tcs[idx].surface,
                        summary: data.summary ?? tcs[idx].summary ?? null,
                    };
                }
                updated = { ...turn, toolCalls: tcs };
                break;
            }
            case "approval_request": {
                const data = event.data;
                const tcs = [...turn.toolCalls];
                let idx = -1;
                for (let i = tcs.length - 1; i >= 0; i--) {
                    if (tcs[i].status === "running" && (!data.tool || tcs[i].name === data.tool)) {
                        idx = i;
                        break;
                    }
                }
                if (idx >= 0) {
                    tcs[idx] = {
                        ...tcs[idx],
                        status: "awaiting_approval",
                        approvalId: data.approval_id,
                        approvalReason: data.reason ?? undefined,
                        capability: data.capability ?? undefined,
                        tool_type: data.tool_type ?? tcs[idx].tool_type,
                    };
                }
                else {
                    // Approval arrived without a preceding tool_start (capability
                    // approval gates can fire before the call). Synthesize one.
                    const toolCall = {
                        id: makeToolCallId(turnId, tcs.length),
                        name: data.tool ?? "approval",
                        status: "awaiting_approval",
                        approvalId: data.approval_id,
                        approvalReason: data.reason ?? undefined,
                        capability: data.capability ?? undefined,
                        tool_type: data.tool_type,
                    };
                    tcs.push(toolCall);
                    updated = {
                        ...turn,
                        toolCalls: tcs,
                        assistantTurnBody: appendToolEntry(turn.assistantTurnBody, toolCall.id),
                    };
                    break;
                }
                updated = { ...turn, toolCalls: tcs };
                break;
            }
            case "approval_resolved": {
                const data = event.data;
                const verdict = data.verdict ?? data.decision;
                const tcs = [...turn.toolCalls];
                const idx = tcs.findIndex((t) => t.approvalId === data.approval_id);
                if (idx >= 0) {
                    const newStatus = verdict === "approved" ? "running"
                        : verdict === "expired" ? "expired"
                            : "denied";
                    tcs[idx] = { ...tcs[idx], status: newStatus };
                }
                updated = { ...turn, toolCalls: tcs };
                break;
            }
            case "skill_auto_inject": {
                const data = event.data;
                updated = {
                    ...turn,
                    autoInjectedSkills: [
                        ...turn.autoInjectedSkills,
                        {
                            skillId: data.skill_id ?? "",
                            skillName: data.skill_name ?? "Unknown",
                            similarity: data.similarity ?? 0,
                            source: data.source ?? "unknown",
                        },
                    ],
                };
                break;
            }
            case "llm_status": {
                const data = event.data;
                updated = {
                    ...turn,
                    llmStatus: {
                        status: data.status ?? "retry",
                        model: data.model,
                        reason: data.reason,
                        attempt: data.attempt,
                        maxRetries: data.max_retries,
                        waitSeconds: data.wait_seconds,
                        fallbackModel: data.fallback_model,
                        error: data.error,
                    },
                };
                break;
            }
            case "error": {
                const data = event.data;
                updated = { ...turn, error: data.message ?? data.detail ?? "Error" };
                break;
            }
            default:
                return s;
        }
        // SSE activity is proof of life — stamp lastEventAt so the
        // snapshot-reconcile pass in useChannelState won't kill a turn that
        // is still receiving deltas.
        const stamped = { ...updated, lastEventAt: Date.now() };
        return {
            channels: {
                ...s.channels,
                [channelId]: {
                    ...ch,
                    turns: { ...ch.turns, [turnId]: stamped },
                },
            },
        };
    }),
    finishTurn: (channelId, turnId) => set((s) => {
        const ch = s.channels[channelId] ?? emptyChannel;
        const turn = ch.turns[turnId];
        if (!turn)
            return s;
        // Materialize the turn's content as a synthetic message.
        let messages = ch.messages;
        const toolCalls = turn.toolCalls.length > 0
            ? turn.toolCalls.map(toPersistedToolCall)
            : undefined;
        const toolResults = turn.toolCalls.length > 0
            ? turn.toolCalls.map((tc) => tc.envelope)
            : undefined;
        const wasCancelled = turn.error === "cancelled";
        const hasPartialActivity = !!turn.streamingContent ||
            !!turn.thinkingContent ||
            (toolResults?.length ?? 0) > 0 ||
            turn.toolCalls.length > 0 ||
            turn.autoInjectedSkills.length > 0;
        const shouldMaterialize = !!turn.streamingContent ||
            !!turn.thinkingContent ||
            (!!turn.error && !wasCancelled) ||
            (wasCancelled && hasPartialActivity) ||
            (toolResults?.length ?? 0) > 0 ||
            turn.autoInjectedSkills.length > 0;
        if (shouldMaterialize) {
            const content = turn.streamingContent || (!wasCancelled && turn.error ? `Turn failed: ${turn.error}` : "");
            const toolsUsed = turn.toolCalls.length > 0
                ? turn.toolCalls.map((tc) => tc.name)
                : undefined;
            const assistantTurnBody = toPersistedAssistantTurnBody(turn.assistantTurnBody);
            // Carry envelopes from the streaming turn into the synthetic message
            // so the rich tool result UI doesn't blink empty between finishTurn
            // and the session-messages refetch landing.
            const metadata = {
                ...(toolsUsed ? { tools_used: toolsUsed } : {}),
                ...(toolResults && toolResults.length > 0 ? { tool_results: toolResults } : {}),
                ...(assistantTurnBody ? { assistant_turn_body: assistantTurnBody } : {}),
                ...(turn.thinkingContent ? { thinking: turn.thinkingContent } : {}),
                ...(turn.botName ? { sender_display_name: turn.botName } : {}),
                ...(turn.botId ? { sender_id: `bot:${turn.botId}` } : {}),
                ...(turn.isPrimary ? {} : { trigger: "member_mention", sender_type: "bot" }),
                ...(turn.autoInjectedSkills.length > 0 ? { auto_injected_skills: turn.autoInjectedSkills } : {}),
                ...(wasCancelled ? { turn_cancelled: true } : {}),
                ...(turn.error && !wasCancelled ? { turn_error: true, turn_error_message: turn.error } : {}),
            };
            const hasMetadata = Object.keys(metadata).length > 0;
            messages = [
                ...messages,
                {
                    id: `turn-${turnId}`,
                    session_id: "",
                    role: "assistant",
                    content,
                    created_at: new Date().toISOString(),
                    ...(toolCalls ? { tool_calls: toolCalls } : {}),
                    ...(turn.correlationId ? { correlation_id: turn.correlationId } : {}),
                    ...(hasMetadata ? { metadata } : {}),
                },
            ];
        }
        const { [turnId]: _removed, ...remaining } = ch.turns;
        return {
            channels: {
                ...s.channels,
                [channelId]: {
                    ...ch,
                    messages,
                    turns: remaining,
                },
            },
        };
    }),
    clearProcessing: (channelId) => set((s) => ({
        channels: {
            ...s.channels,
            [channelId]: {
                ...(s.channels[channelId] ?? emptyChannel),
                isProcessing: false,
                queuedTaskId: null,
            },
        },
    })),
    setProcessing: (channelId, taskId) => set((s) => ({
        channels: {
            ...s.channels,
            [channelId]: {
                ...(s.channels[channelId] ?? emptyChannel),
                isProcessing: true,
                queuedTaskId: taskId,
            },
        },
    })),
    setError: (channelId, error) => set((s) => ({
        channels: {
            ...s.channels,
            [channelId]: {
                ...(s.channels[channelId] ?? emptyChannel),
                error,
            },
        },
    })),
    setSecretWarning: (channelId, warning) => set((s) => ({
        channels: {
            ...s.channels,
            [channelId]: {
                ...(s.channels[channelId] ?? emptyChannel),
                secretWarning: warning,
            },
        },
    })),
    setContextBudget: (channelId, budget) => set((s) => ({
        channels: {
            ...s.channels,
            [channelId]: {
                ...(s.channels[channelId] ?? emptyChannel),
                contextBudget: budget,
            },
        },
    })),
    deleteChannel: (channelId) => set((s) => {
        const { [channelId]: _, ...rest } = s.channels;
        return { channels: rest };
    }),
}));
/** Convenience selector — true when the channel has at least one in-flight turn. */
export function selectIsStreaming(state) {
    return Object.keys(state.turns).length > 0;
}
