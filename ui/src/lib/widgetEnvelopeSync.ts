import type { ToolResultEnvelope } from "../types/api";

export type SharedEnvelopeUpdateKind = "state_poll" | "tool_result";

export interface SharedEnvelopeUpdate {
  kind: SharedEnvelopeUpdateKind;
  sourceToolName: string;
  sourceSignature: string;
  envelope: ToolResultEnvelope;
}

export type PinnedSharedEnvelopeDecision = "ignore" | "adopt" | "refresh";

function stableSerialize(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(",")}]`;
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, item]) => `${JSON.stringify(key)}:${stableSerialize(item)}`);
  return `{${entries.join(",")}}`;
}

export function buildWidgetSyncSignature(
  toolName: string,
  widgetConfig?: Record<string, unknown> | null,
): string {
  return `${toolName}::${stableSerialize(widgetConfig ?? {})}`;
}

export function decidePinnedSharedEnvelopeUpdate(args: {
  currentToolName: string;
  currentSignature: string;
  currentEnvelope: ToolResultEnvelope | null | undefined;
  incoming: SharedEnvelopeUpdate;
}): PinnedSharedEnvelopeDecision {
  const { currentToolName, currentSignature, currentEnvelope, incoming } = args;

  if (!currentEnvelope) return "ignore";

  if (incoming.sourceSignature === currentSignature) {
    return "adopt";
  }

  if (incoming.kind === "state_poll" && incoming.sourceToolName === currentToolName) {
    return "ignore";
  }

  if (!currentEnvelope.refreshable) return "ignore";

  return "refresh";
}
