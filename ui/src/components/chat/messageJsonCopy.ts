import type { Message, ToolResultEnvelope } from "../../types/api";

const MAX_INLINE_BODY_CHARS = 1200;

function compactEnvelopeForCopy(envelope: ToolResultEnvelope): ToolResultEnvelope & {
  body_omitted?: boolean;
  body_preview?: string;
} {
  const body = typeof envelope.body === "string" ? envelope.body : null;
  const isBulkyHtml = envelope.content_type === "application/vnd.spindrel.html+interactive";
  const isLargeBody = !!body && body.length > MAX_INLINE_BODY_CHARS;
  if (!body || (!isBulkyHtml && !isLargeBody)) return envelope;

  const { body: _body, ...rest } = envelope;
  return {
    ...rest,
    body: null,
    body_omitted: true,
    body_preview: body.slice(0, 240),
  };
}

function compactMetadataForCopy(metadata: Message["metadata"]): Message["metadata"] {
  if (!metadata) return metadata;
  const toolResults = metadata.tool_results;
  if (!Array.isArray(toolResults)) return metadata;
  return {
    ...metadata,
    tool_results: toolResults.map((result) =>
      result && typeof result === "object"
        ? compactEnvelopeForCopy(result as ToolResultEnvelope)
        : result,
    ),
  };
}

export function compactMessagesForJsonCopy(messages: Message[]): Message[] {
  return messages.map((message) => ({
    ...message,
    metadata: compactMetadataForCopy(message.metadata),
  }));
}

export function stringifyMessagesForJsonCopy(messages: Message[]): string {
  return JSON.stringify(compactMessagesForJsonCopy(messages), null, 2);
}
