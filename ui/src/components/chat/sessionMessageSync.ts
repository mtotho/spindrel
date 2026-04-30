import type {
  AssistantTurnBody,
  Message,
  ToolCall,
  ToolResultEnvelope,
} from "../../types/api";
import { buildAssistantTurnBodyItems, buildLegacyAssistantTurnBody } from "./toolTranscriptModel.js";
import { extractDisplayText } from "./messageUtils.js";

const CONTENT_PREFIX_LEN = 120;

function normalizedContentPrefix(raw: unknown): string {
  if (typeof raw !== "string") return "";
  return extractDisplayText(raw).trim().replace(/\s+/g, "").slice(0, CONTENT_PREFIX_LEN);
}

function structuredRenderItemCount(message: Message): number {
  if (message.role !== "assistant") return 0;
  const meta = (message.metadata ?? {}) as Record<string, unknown>;
  const assistantTurnBody = (
    meta.assistant_turn_body as AssistantTurnBody | undefined
  ) ?? buildLegacyAssistantTurnBody({
    displayContent: extractDisplayText(message.content),
    transcriptEntries: meta.transcript_entries as AssistantTurnBody["items"] | undefined,
    toolCalls: message.tool_calls,
  });
  const toolResults = meta.tool_results as (ToolResultEnvelope | undefined)[] | undefined;
  const rootEnvelope = meta.envelope as ToolResultEnvelope | undefined;
  const items = buildAssistantTurnBodyItems({
    assistantTurnBody,
    toolCalls: (message.tool_calls ?? []) as ToolCall[],
    toolResults,
    rootEnvelope,
  });
  return items.filter(
    (item) =>
      item.kind === "widget"
      || item.kind === "rich_result"
      || item.kind === "root_rich_result",
  ).length;
}

function textSize(value: unknown): number {
  if (typeof value !== "string") return 0;
  return value.trim().length;
}

function assistantTurnBodyTextSize(body: AssistantTurnBody | undefined): number {
  if (!body || !Array.isArray(body.items)) return 0;
  let total = 0;
  for (const item of body.items as any[]) {
    if (!item || typeof item !== "object") continue;
    total += textSize(item.text);
    total += textSize(item.content);
    total += textSize(item.previewText);
    total += textSize(item.detail);
  }
  return total;
}

function assistantMessageRichnessScore(message: Message): number {
  if (message.role !== "assistant") return 0;
  const meta = (message.metadata ?? {}) as Record<string, unknown>;
  const assistantTurnBody = meta.assistant_turn_body as AssistantTurnBody | undefined;
  return (
    normalizedContentPrefix(message.content).length
    + textSize(message.content)
    + textSize(meta.thinking)
    + textSize(meta.thinking_content)
    + assistantTurnBodyTextSize(assistantTurnBody)
    + structuredRenderItemCount(message) * 10_000
    + ((message.tool_calls ?? []).length * 1_000)
  );
}

function matchingDbMessages(synthetic: Message, dbMessages: Message[]): Message[] {
  if (synthetic.role !== "assistant") return [];
  if (synthetic.correlation_id) {
    const byCorrelation = dbMessages.filter(
      (message) => message.correlation_id === synthetic.correlation_id,
    );
    if (byCorrelation.length > 0) return byCorrelation;
  }
  const syntheticPrefix = normalizedContentPrefix(synthetic.content);
  if (!syntheticPrefix) return [];
  return dbMessages.filter(
    (message) =>
      message.role === "assistant"
      && normalizedContentPrefix(message.content) === syntheticPrefix,
  );
}

export function shouldKeepSyntheticAssistantMessage(
  synthetic: Message,
  dbMessages: Message[],
): boolean {
  if (!(synthetic.id.startsWith("turn-") || synthetic.id.startsWith("msg-"))) return false;
  if (synthetic.role !== "assistant") return false;

  const matches = matchingDbMessages(synthetic, dbMessages);
  if (matches.length === 0) return true;

  const syntheticStructuredCount = structuredRenderItemCount(synthetic);
  if (syntheticStructuredCount === 0) return false;

  return matches.every(
    (candidate) =>
      structuredRenderItemCount(candidate) < syntheticStructuredCount
      || assistantMessageRichnessScore(candidate) < assistantMessageRichnessScore(synthetic),
  );
}

export function mergePersistedAndSyntheticMessages(
  dbMessages: Message[],
  currentMessages: Message[],
): Message[] {
  const syntheticKeep = currentMessages.filter((message) =>
    shouldKeepSyntheticAssistantMessage(message, dbMessages),
  );
  return [...dbMessages, ...syntheticKeep];
}
