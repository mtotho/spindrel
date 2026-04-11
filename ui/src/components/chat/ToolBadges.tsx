/**
 * Tool badges -- shows tools used on persisted messages with expandable args.
 * Groups same-name tool calls into compact badges with counts.
 */

import { useState } from "react";
import { Wrench, ChevronRight, ChevronDown } from "lucide-react";
import { formatToolArgs } from "./toolCallUtils";
import { normalizeToolCall } from "../../types/api";
import type { ToolCall } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";

interface ToolItem {
  name: string;
  count: number;
  argsList: (string | undefined)[];
}

function buildItems(toolNames: string[], toolCalls?: ToolCall[]): ToolItem[] {
  if (toolCalls && toolCalls.length > 0) {
    // Group consecutive same-name calls
    const items: ToolItem[] = [];
    for (const tc of toolCalls) {
      const norm = normalizeToolCall(tc);
      const last = items[items.length - 1];
      if (last && last.name === norm.name) {
        last.count++;
        last.argsList.push(norm.arguments);
      } else {
        items.push({ name: norm.name, count: 1, argsList: [norm.arguments] });
      }
    }
    return items;
  }
  // Fallback: dedup from toolNames
  const counts = new Map<string, number>();
  for (const name of toolNames) {
    counts.set(name, (counts.get(name) || 0) + 1);
  }
  return Array.from(counts, ([name, count]) => ({ name, count, argsList: [] }));
}

export function ToolBadges({
  toolNames,
  toolCalls,
  t,
}: {
  toolNames: string[];
  toolCalls?: ToolCall[];
  t: ThemeTokens;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  // Render when EITHER source has data — toolNames is the
  // metadata-derived list (set on persisted turns) and toolCalls is the
  // raw tool_calls field (set during streaming and on freshly persisted
  // assistant rows where meta.tools_used hasn't been backfilled yet).
  // Gating only on toolNames produces an empty-assistant-turn ghost row.
  if (toolNames.length === 0 && (!toolCalls || toolCalls.length === 0)) {
    return null;
  }

  const items = buildItems(toolNames, toolCalls);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {items.map((item, idx) => {
          const hasArgs = item.argsList.some(a => !!a);
          const isExpanded = expandedIdx === idx;
          return (
            <div key={idx} style={{ display: "flex", flexDirection: "column" }}>
              <div
                onClick={hasArgs ? () => setExpandedIdx(isExpanded ? null : idx) : undefined}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  paddingLeft: 6,
                  paddingRight: 8,
                  paddingTop: 3,
                  paddingBottom: 3,
                  borderRadius: 4,
                  backgroundColor: isExpanded ? t.surfaceBorder : t.overlayLight,
                  border: `1px solid ${t.overlayBorder}`,
                  cursor: hasArgs ? "pointer" : "default",
                  transition: "background-color 0.15s",
                }}
              >
                <Wrench size={10} color={t.textDim} />
                <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "'Menlo', monospace" }}>
                  {item.name}{item.count > 1 ? ` \u00d7${item.count}` : ""}
                </span>
                {hasArgs && (
                  isExpanded
                    ? <ChevronDown size={10} color={t.textDim} />
                    : <ChevronRight size={10} color={t.textDim} />
                )}
              </div>
            </div>
          );
        })}
      </div>
      {expandedIdx !== null && items[expandedIdx]?.argsList.length > 0 && (() => {
        const item = items[expandedIdx];
        // For grouped calls, show each set of args
        const argsToShow = item.argsList
          .map(a => formatToolArgs(a))
          .filter((a): a is string => a !== null);
        if (argsToShow.length === 0) return null;
        return (
          <div
            style={{
              borderRadius: 6,
              backgroundColor: t.overlayLight,
              border: `1px solid ${t.overlayBorder}`,
              padding: "6px 10px",
              maxHeight: 300,
              overflowY: "auto",
            }}
          >
            {argsToShow.map((formatted, i) => (
              <div key={i}>
                {argsToShow.length > 1 && (
                  <div style={{
                    fontSize: 10,
                    color: t.textDim,
                    fontWeight: 600,
                    marginTop: i > 0 ? 8 : 0,
                    marginBottom: 2,
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                  }}>
                    Call {i + 1}
                  </div>
                )}
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11,
                    fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
                    color: t.textMuted,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    lineHeight: "1.4",
                  }}
                >
                  {formatted}
                </pre>
              </div>
            ))}
          </div>
        );
      })()}
    </div>
  );
}
