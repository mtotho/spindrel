/**
 * Compatibility wrapper for legacy/persisted tool badge props.
 *
 * The actual row rendering lives in ToolTranscriptRows/TerminalToolTranscript.
 * Keep this file small so transcript UI does not accrete into a god component.
 */

import { useMemo, useState } from "react";
import type { ToolCall, ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { ToolTraceStrip, type TraceTick } from "./ToolTraceStrip";
import { DefaultToolRows } from "./ToolTranscriptRows";
import {
  buildPersistedToolEntries,
  type SharedToolTranscriptEntry,
} from "./toolTranscriptModel";

const TRACE_STRIP_THRESHOLD = 4;

export function ToolBadges({
  toolNames,
  toolCalls,
  toolResults,
  entries,
  sessionId,
  channelId,
  botId,
  chatMode = "default",
  t,
}: {
  toolNames: string[];
  toolCalls?: ToolCall[];
  toolResults?: (ToolResultEnvelope | undefined)[];
  entries?: SharedToolTranscriptEntry[];
  sessionId?: string;
  channelId?: string;
  botId?: string;
  chatMode?: "default" | "terminal";
  compact?: boolean;
  t: ThemeTokens;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [striped, setStriped] = useState<boolean | null>(null);
  const isTerminalMode = chatMode === "terminal";

  const resolvedEntries = useMemo(
    () => entries ?? buildPersistedToolEntries(toolNames, toolCalls, toolResults),
    [entries, toolNames, toolCalls, toolResults],
  );

  const ticks: TraceTick[] = useMemo(
    () => resolvedEntries.map((entry: SharedToolTranscriptEntry) => ({
      toolName: entry.label,
      target: entry.target ?? undefined,
      isError: entry.isError,
    })),
    [resolvedEntries],
  );

  if (resolvedEntries.length === 0) return null;

  const hasApproval = resolvedEntries.some((entry) => !!entry.approval);
  const stripMode = !isTerminalMode && !hasApproval && (striped ?? (resolvedEntries.length >= TRACE_STRIP_THRESHOLD));
  if (stripMode) {
    return <ToolTraceStrip ticks={ticks} onExpand={() => setStriped(false)} t={t} chatMode={chatMode} />;
  }

  return (
    <DefaultToolRows
      entries={resolvedEntries}
      expandedIdx={expandedIdx}
      setExpandedIdx={setExpandedIdx}
      t={t}
      chatMode={chatMode}
      sessionId={sessionId}
      channelId={channelId}
      botId={botId}
    />
  );
}

export { DefaultToolRows } from "./ToolTranscriptRows";
