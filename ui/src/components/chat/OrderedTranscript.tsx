import { useMemo, useState } from "react";
import type { ThemeTokens } from "../../theme/tokens";
import { MarkdownContent } from "./MarkdownContent";
import { useDecideApproval, type DecideRequest } from "../../api/hooks/useApprovals";
import { DefaultToolRows } from "./ToolTranscriptRows";
import { WidgetCard } from "./WidgetCard";
import { RichToolResult } from "./RichToolResult";
import type { ToolResultEnvelope } from "../../types/api";
import type { OrderedTurnBodyItem } from "./toolTranscriptModel";
import { groupAdjacentTranscriptItems } from "./orderedTranscriptGrouping";

export function isTightRichEnvelope(envelope: ToolResultEnvelope | undefined) {
  return envelope?.view_key === "compaction_run"
    || envelope?.content_type === "application/vnd.spindrel.diff+text"
    || envelope?.content_type === "application/vnd.spindrel.file-listing+json";
}

export function OrderedTranscript({
  items,
  t,
  chatMode,
  sessionId,
  channelId,
  botId,
  isLatestBotMessage = false,
  onPin,
  sourceLabel,
}: {
  items: OrderedTurnBodyItem[];
  t: ThemeTokens;
  chatMode: "default" | "terminal";
  sessionId?: string;
  channelId?: string;
  botId?: string;
  isLatestBotMessage?: boolean;
  onPin?: (info: { widgetId: string; envelope: ToolResultEnvelope; toolName: string; channelId: string; botId: string | null }) => void | Promise<void>;
  sourceLabel?: string;
}) {
  const decideApproval = useDecideApproval();
  const [decidingIds, setDecidingIds] = useState<Set<string>>(new Set());
  const [decidedApprovalIds, setDecidedApprovalIds] = useState<Set<string>>(new Set());
  const [expandedItems, setExpandedItems] = useState<Map<string, number>>(new Map());
  const isTerminalMode = chatMode === "terminal";
  const groupedItems = useMemo(() => groupAdjacentTranscriptItems(items), [items]);

  const handleDecide = (
    approvalId: string,
    approved: boolean,
    options?: { bypassRestOfTurn?: boolean },
  ) => {
    setDecidingIds((prev) => new Set(prev).add(approvalId));
    const data: DecideRequest = {
      approved,
      decided_by: "web:admin",
      ...(options?.bypassRestOfTurn ? { bypass_rest_of_turn: true } : {}),
    };
    decideApproval.mutate(
      { approvalId, data },
      {
        onSuccess: () => {
          setDecidedApprovalIds((prev) => new Set(prev).add(approvalId));
        },
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {groupedItems.map((item, index) => {
        if (item.kind === "text") {
          return (
            <div key={item.key} style={{ contain: "content" }}>
              <MarkdownContent text={item.text} t={t} chatMode={chatMode} />
            </div>
          );
        }

        if (item.kind === "transcript") {
          const visibleEntries = item.entries.filter(
            (entry) => !entry.approval || !decidedApprovalIds.has(entry.approval.approvalId),
          );
          if (visibleEntries.length === 0) return null;
          return (
            <DefaultToolRows
              key={item.key}
              entries={visibleEntries}
              expandedIdx={expandedItems.get(item.key) ?? null}
              setExpandedIdx={(value) => {
                setExpandedItems((prev) => {
                  const next = new Map(prev);
                  if (value == null) next.delete(item.key);
                  else next.set(item.key, value);
                  return next;
                });
              }}
              sessionId={sessionId}
              channelId={channelId}
              botId={botId}
              t={t}
              chatMode={chatMode}
              onApproval={handleDecide}
              decidingIds={decidingIds}
            />
          );
        }

        if (item.kind === "widget") {
          const nextItem = groupedItems[index + 1];
          const defaultCollapsed = nextItem?.kind === "widget" && nextItem.widget.toolName === item.widget.toolName;
          return (
            <WidgetCard
              key={item.key}
              envelope={item.widget.envelope}
              toolName={item.widget.toolName}
              sessionId={sessionId}
              channelId={channelId}
              botId={botId}
              widgetId={item.widget.recordId}
              t={t}
              chatMode={chatMode}
              isLatestBotMessage={isLatestBotMessage}
              defaultCollapsed={defaultCollapsed}
              onPin={onPin}
            />
          );
        }

        const envelope = item.envelope;
        if (isTerminalMode) {
          return (
            <div key={item.key} style={{ marginTop: 8 }}>
              <RichToolResult
                envelope={envelope}
                sessionId={sessionId}
                channelId={channelId}
                botId={botId}
                rendererVariant="terminal-chat"
                chromeMode="embedded"
                summary={"summary" in item ? item.summary : null}
                t={t}
              />
            </div>
          );
        }

        if (isTightRichEnvelope(envelope)) {
          return (
            <div key={item.key} className="mt-2">
              <RichToolResult
                envelope={envelope}
                sessionId={sessionId}
                channelId={channelId}
                botId={botId}
                rendererVariant="default-chat"
                chromeMode="standalone"
                summary={"summary" in item ? item.summary : null}
                t={t}
              />
            </div>
          );
        }

        return (
          <div
            key={item.key}
            className={`rounded-lg border overflow-hidden ${item.kind === "root_rich_result" ? "mt-1.5" : "mt-2"}`}
            style={{ borderColor: t.surfaceBorder, backgroundColor: t.surfaceRaised }}
          >
            {item.kind === "root_rich_result" && (
              <div className="px-3 pt-2 pb-0.5">
                <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: t.textDim }}>
                  {sourceLabel || "event"}
                </span>
              </div>
            )}
            <div className={item.kind === "root_rich_result" ? (isTightRichEnvelope(envelope) ? "px-1 pb-1.5" : "px-3 pb-2") : "px-3 py-2"}>
              <RichToolResult
                envelope={envelope}
                sessionId={sessionId}
                channelId={channelId}
                botId={botId}
                rendererVariant="default-chat"
                chromeMode="embedded"
                summary={"summary" in item ? item.summary : null}
                t={t}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
