/**
 * Tool badges -- shows tools used on persisted messages with expandable args.
 * Groups same-name tool calls into compact badges with counts.
 *
 * When per-call envelopes are provided (`toolResults`), the expanded panel
 * also renders the rendered tool result body via <RichToolResult>. Envelopes
 * with `display="inline"` auto-expand on first render so file ops feel
 * immediate without forcing the user to click. The user can disable
 * auto-expansion with the per-channel "compact tool results" toggle.
 */

import { useEffect, useState } from "react";
import { Wrench, ChevronRight, ChevronDown } from "lucide-react";
import { formatToolArgs } from "./toolCallUtils";
import { normalizeToolCall } from "../../types/api";
import type { ToolCall, ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { RichToolResult } from "./RichToolResult";

interface ToolItem {
  name: string;
  count: number;
  argsList: (string | undefined)[];
  /** Envelopes for each call in argsList — same length, same order. */
  envelopes: (ToolResultEnvelope | undefined)[];
}

function buildItems(
  toolNames: string[],
  toolCalls?: ToolCall[],
  toolResults?: ToolResultEnvelope[],
): ToolItem[] {
  if (toolCalls && toolCalls.length > 0) {
    // Group consecutive same-name calls
    const items: ToolItem[] = [];
    let envIdx = 0;
    for (const tc of toolCalls) {
      const norm = normalizeToolCall(tc);
      const env = toolResults?.[envIdx];
      envIdx++;
      const last = items[items.length - 1];
      if (last && last.name === norm.name) {
        last.count++;
        last.argsList.push(norm.arguments);
        last.envelopes.push(env);
      } else {
        items.push({
          name: norm.name,
          count: 1,
          argsList: [norm.arguments],
          envelopes: [env],
        });
      }
    }
    return items;
  }
  // Fallback: dedup from toolNames (persisted messages where tool_calls is null).
  // toolResults is in the same order as toolNames, so distribute positionally.
  const counts = new Map<string, number>();
  const envMap = new Map<string, (ToolResultEnvelope | undefined)[]>();
  for (let i = 0; i < toolNames.length; i++) {
    const name = toolNames[i];
    counts.set(name, (counts.get(name) || 0) + 1);
    if (!envMap.has(name)) envMap.set(name, []);
    envMap.get(name)!.push(toolResults?.[i]);
  }
  return Array.from(counts, ([name, count]) => ({
    name,
    count,
    argsList: [],
    envelopes: envMap.get(name) ?? [],
  }));
}

export function ToolBadges({
  toolNames,
  toolCalls,
  toolResults,
  sessionId,
  compact = false,
  t,
}: {
  toolNames: string[];
  toolCalls?: ToolCall[];
  toolResults?: ToolResultEnvelope[];
  sessionId?: string;
  /** When true, ignore the envelope's `display="inline"` hint and require
   *  the user to click to expand any rich body. Wired from the per-channel
   *  "compact tool results" toggle. */
  compact?: boolean;
  t: ThemeTokens;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  // Auto-expand the first tool item that has an inline-display envelope so
  // file ops render their body immediately. Honors `compact`: when the
  // user has compact mode enabled the auto-expand is suppressed.
  useEffect(() => {
    if (compact) return;
    if (expandedIdx !== null) return;
    if (!toolResults || toolResults.length === 0) return;
    const items = buildItems(toolNames, toolCalls, toolResults);
    for (let i = 0; i < items.length; i++) {
      if (items[i].envelopes.some((e) => e?.display === "inline")) {
        setExpandedIdx(i);
        return;
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolNames, toolCalls, toolResults, compact]);
  // Render when EITHER source has data — toolNames is the
  // metadata-derived list (set on persisted turns) and toolCalls is the
  // raw tool_calls field (set during streaming and on freshly persisted
  // assistant rows where meta.tools_used hasn't been backfilled yet).
  // Gating only on toolNames produces an empty-assistant-turn ghost row.
  if (toolNames.length === 0 && (!toolCalls || toolCalls.length === 0)) {
    return null;
  }

  const items = buildItems(toolNames, toolCalls, toolResults);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {items.map((item, idx) => {
          const hasArgs = item.argsList.some(a => !!a);
          const hasEnvelope = item.envelopes.some(e => !!e);
          const expandable = hasArgs || hasEnvelope;
          const isExpanded = expandedIdx === idx;
          return (
            <div key={idx} style={{ display: "flex", flexDirection: "column" }}>
              <div
                onClick={expandable ? () => setExpandedIdx(isExpanded ? null : idx) : undefined}
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
                  cursor: expandable ? "pointer" : "default",
                  transition: "background-color 0.15s",
                }}
              >
                <Wrench size={10} color={t.textDim} />
                <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "'Menlo', monospace" }}>
                  {item.name}{item.count > 1 ? ` \u00d7${item.count}` : ""}
                </span>
                {expandable && (
                  isExpanded
                    ? <ChevronDown size={10} color={t.textDim} />
                    : <ChevronRight size={10} color={t.textDim} />
                )}
              </div>
            </div>
          );
        })}
      </div>
      {expandedIdx !== null && (() => {
        const item = items[expandedIdx];
        if (!item) return null;
        const argsToShow = item.argsList
          .map(a => formatToolArgs(a))
          .filter((a): a is string => a !== null);
        const envelopesToShow = item.envelopes;
        const showAnyArgs = argsToShow.length > 0;
        const showAnyEnvelope = envelopesToShow.some(e => !!e);
        if (!showAnyArgs && !showAnyEnvelope) return null;
        return (
          <div
            style={{
              borderRadius: 6,
              backgroundColor: t.overlayLight,
              border: `1px solid ${t.overlayBorder}`,
              padding: "6px 10px",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {showAnyArgs && (
              <div style={{ maxHeight: 300, overflowY: "auto" }}>
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
            )}
            {showAnyEnvelope && envelopesToShow.map((env, i) => {
              if (!env) return null;
              return (
                <div key={`env-${i}`}>
                  {envelopesToShow.length > 1 && (
                    <div style={{
                      fontSize: 10,
                      color: t.textDim,
                      fontWeight: 600,
                      marginBottom: 2,
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                    }}>
                      Result {i + 1}
                    </div>
                  )}
                  <RichToolResult envelope={env} sessionId={sessionId} t={t} />
                </div>
              );
            })}
          </div>
        );
      })()}
    </div>
  );
}
