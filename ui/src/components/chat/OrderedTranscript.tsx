import { useState } from "react";
import type { ThemeTokens } from "../../theme/tokens";
import { MarkdownContent } from "./MarkdownContent";
import { useDecideApproval, type DecideRequest } from "../../api/hooks/useApprovals";
import { TerminalStreamingToolTranscript } from "./TerminalToolTranscript";
import { DefaultToolRows } from "./ToolBadges";
import { buildLiveToolEntries } from "./toolTranscriptModel";
import type { ToolCall as LiveToolCall, TurnTranscriptEntry } from "../../stores/chat";

export function OrderedTranscript({
  entries,
  toolCalls,
  t,
  chatMode,
}: {
  entries: TurnTranscriptEntry[];
  toolCalls: LiveToolCall[];
  t: ThemeTokens;
  chatMode: "default" | "terminal";
}) {
  const decideApproval = useDecideApproval();
  const [decidingIds, setDecidingIds] = useState<Set<string>>(new Set());
  const [expandedArgs, setExpandedArgs] = useState<Set<string>>(new Set());
  const isTerminalMode = chatMode === "terminal";

  const toolCallById = new Map(toolCalls.map((toolCall) => [toolCall.id, toolCall]));
  let fallbackToolIdx = 0;

  const handleDecide = (approvalId: string, approved: boolean) => {
    setDecidingIds((prev) => new Set(prev).add(approvalId));
    const data: DecideRequest = { approved, decided_by: "web:admin" };
    decideApproval.mutate(
      { approvalId, data },
      {
        onSettled: () => {
          setDecidingIds((prev) => {
            const next = new Set(prev);
            next.delete(approvalId);
            return next;
          });
        },
      },
    );
  };

  const toggleArgs = (toolCallId: string) => {
    setExpandedArgs((prev) => {
      const next = new Set(prev);
      if (next.has(toolCallId)) next.delete(toolCallId);
      else next.add(toolCallId);
      return next;
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {entries.map((entry) => {
        if (entry.kind === "text") {
          if (!entry.text.trim()) return null;
          return (
            <div key={entry.id} style={{ contain: "content" }}>
              <MarkdownContent text={entry.text} t={t} chatMode={chatMode} />
            </div>
          );
        }

        const toolCall = toolCallById.get(entry.toolCallId);
        const orderedFallback = toolCall ?? toolCalls[fallbackToolIdx++];
        if (!orderedFallback) return null;

        if (isTerminalMode) {
          return <TerminalStreamingToolTranscript key={entry.id} toolCalls={[orderedFallback]} t={t} />;
        }

        const liveEntries = buildLiveToolEntries([orderedFallback]);
        if (liveEntries.length === 0) return null;

        return (
          <DefaultToolRows
            key={entry.id}
            entries={liveEntries}
            expandedIdx={expandedArgs.has(orderedFallback.id) ? 0 : null}
            setExpandedIdx={() => toggleArgs(orderedFallback.id)}
            t={t}
            onApproval={handleDecide}
            decidingIds={decidingIds}
          />
        );
      })}
    </div>
  );
}
