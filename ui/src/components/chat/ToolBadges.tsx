/**
 * Tool badges -- shows tools used on persisted messages with expandable args.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useState } from "react";
import { Wrench, ChevronRight, ChevronDown } from "lucide-react";
import { formatToolArgs } from "./toolCallUtils";
import { normalizeToolCall } from "../../types/api";
import type { ToolCall } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";

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
  if (toolNames.length === 0) return null;

  // Build display list: if we have full tool_calls, use them (preserves order + args).
  // Otherwise fall back to toolNames with dedup/count.
  const items: { name: string; count: number; args?: string }[] = [];
  if (toolCalls && toolCalls.length > 0) {
    for (const tc of toolCalls) {
      const norm = normalizeToolCall(tc);
      items.push({ name: norm.name, count: 1, args: norm.arguments });
    }
  } else {
    const counts = new Map<string, number>();
    for (const name of toolNames) {
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    for (const [name, count] of counts) {
      items.push({ name, count });
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {items.map((item, idx) => {
          const hasArgs = !!item.args;
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
                  {item.name}{item.count > 1 ? ` x${item.count}` : ""}
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
      {expandedIdx !== null && items[expandedIdx]?.args && (() => {
        const formatted = formatToolArgs(items[expandedIdx].args);
        if (!formatted) return null;
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
        );
      })()}
    </div>
  );
}
