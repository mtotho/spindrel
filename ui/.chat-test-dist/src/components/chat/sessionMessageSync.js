import { buildAssistantTurnBodyItems, buildLegacyAssistantTurnBody } from "./toolTranscriptModel.js";
import { extractDisplayText } from "./messageUtils.js";
const CONTENT_PREFIX_LEN = 120;
function normalizedContentPrefix(raw) {
    if (typeof raw !== "string")
        return "";
    return extractDisplayText(raw).trim().replace(/\s+/g, "").slice(0, CONTENT_PREFIX_LEN);
}
function structuredRenderItemCount(message) {
    if (message.role !== "assistant")
        return 0;
    const meta = (message.metadata ?? {});
    const assistantTurnBody = meta.assistant_turn_body ?? buildLegacyAssistantTurnBody({
        displayContent: extractDisplayText(message.content),
        transcriptEntries: meta.transcript_entries,
        toolCalls: message.tool_calls,
    });
    const toolResults = meta.tool_results;
    const rootEnvelope = meta.envelope;
    const items = buildAssistantTurnBodyItems({
        assistantTurnBody,
        toolCalls: (message.tool_calls ?? []),
        toolResults,
        rootEnvelope,
    });
    return items.filter((item) => item.kind === "widget"
        || item.kind === "rich_result"
        || item.kind === "root_rich_result").length;
}
function matchingDbMessages(synthetic, dbMessages) {
    if (synthetic.role !== "assistant")
        return [];
    if (synthetic.correlation_id) {
        const byCorrelation = dbMessages.filter((message) => message.correlation_id === synthetic.correlation_id);
        if (byCorrelation.length > 0)
            return byCorrelation;
    }
    const syntheticPrefix = normalizedContentPrefix(synthetic.content);
    if (!syntheticPrefix)
        return [];
    return dbMessages.filter((message) => message.role === "assistant"
        && normalizedContentPrefix(message.content) === syntheticPrefix);
}
export function shouldKeepSyntheticAssistantMessage(synthetic, dbMessages) {
    if (!(synthetic.id.startsWith("turn-") || synthetic.id.startsWith("msg-")))
        return false;
    if (synthetic.role !== "assistant")
        return false;
    const matches = matchingDbMessages(synthetic, dbMessages);
    if (matches.length === 0)
        return true;
    const syntheticStructuredCount = structuredRenderItemCount(synthetic);
    if (syntheticStructuredCount === 0)
        return false;
    return matches.every((candidate) => structuredRenderItemCount(candidate) < syntheticStructuredCount);
}
export function mergePersistedAndSyntheticMessages(dbMessages, currentMessages) {
    const syntheticKeep = currentMessages.filter((message) => shouldKeepSyntheticAssistantMessage(message, dbMessages));
    return [...dbMessages, ...syntheticKeep];
}
