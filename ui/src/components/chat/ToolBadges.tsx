/**
 * Tool badges — shows tools used on persisted messages with expandable results.
 *
 * Design: unified card per tool group. Badge is the card header, results are
 * the card body. A 2px left accent bar connects them visually (blue for normal,
 * red for errors). Only the latest bot message auto-expands; older messages
 * render collapsed pill badges with a result count.
 *
 * Within an expanded card, individual results are collapsible — latest expanded,
 * older collapsed. Large results fade at max-height with a "Show all" affordance.
 */

import { useEffect, useState, useCallback } from "react";
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
  envelopes: (ToolResultEnvelope | undefined)[];
}

/** Check if an envelope represents an error result. */
function isErrorEnvelope(env: ToolResultEnvelope | undefined): boolean {
  if (!env) return false;
  const body = env.body ?? env.plain_body ?? "";
  if (!body) return false;
  try {
    const parsed = JSON.parse(body);
    return typeof parsed === "object" && parsed !== null && "error" in parsed;
  } catch {
    return false;
  }
}

/** Check if ANY envelope in the group is an error. */
function groupHasError(envelopes: (ToolResultEnvelope | undefined)[]): boolean {
  return envelopes.some(isErrorEnvelope);
}

/** Extract a compact summary for a result header line. */
function resultSummary(env: ToolResultEnvelope | undefined): string {
  if (!env) return "";
  if (isErrorEnvelope(env)) {
    try {
      const parsed = JSON.parse(env.body ?? env.plain_body ?? "");
      const msg = parsed.error;
      return typeof msg === "string" ? msg.slice(0, 80) : "error";
    } catch {
      return "error";
    }
  }
  // For diffs, show a compact stat if plain_body mentions it
  const pb = env.plain_body ?? "";
  if (pb && pb.length < 120) return pb;
  if (env.byte_size > 0) return `${(env.byte_size / 1024).toFixed(1)} KB`;
  return "";
}

function buildItems(
  toolNames: string[],
  toolCalls?: ToolCall[],
  toolResults?: ToolResultEnvelope[],
): ToolItem[] {
  if (toolCalls && toolCalls.length > 0) {
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
  autoExpand = false,
  t,
}: {
  toolNames: string[];
  toolCalls?: ToolCall[];
  toolResults?: ToolResultEnvelope[];
  sessionId?: string;
  compact?: boolean;
  /** When true, auto-expand inline-display envelopes (only set on the latest
   *  bot message). When false, everything renders collapsed. */
  autoExpand?: boolean;
  t: ThemeTokens;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  // Track which individual results within the expanded card are open.
  // Key: "resultIdx", value: true if open.
  const [openResults, setOpenResults] = useState<Record<number, boolean>>({});
  // Track which result panels have been "uncapped" (max-height removed).
  const [uncappedResults, setUncappedResults] = useState<Record<number, boolean>>({});

  const toggleResult = useCallback((i: number) => {
    setOpenResults((prev) => ({ ...prev, [i]: !prev[i] }));
  }, []);

  const uncapResult = useCallback((i: number) => {
    setUncappedResults((prev) => ({ ...prev, [i]: true }));
  }, []);

  // Auto-expand: only when autoExpand=true and not compact
  useEffect(() => {
    if (compact || !autoExpand) return;
    if (expandedIdx !== null) return;
    if (!toolResults || toolResults.length === 0) return;
    const items = buildItems(toolNames, toolCalls, toolResults);
    for (let i = 0; i < items.length; i++) {
      if (items[i].envelopes.some((e) => e?.display === "inline")) {
        setExpandedIdx(i);
        // Auto-open the last result within the group
        const lastEnvIdx = items[i].envelopes.length - 1;
        if (lastEnvIdx >= 0) {
          setOpenResults({ [lastEnvIdx]: true });
        }
        return;
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolNames, toolCalls, toolResults, compact, autoExpand]);

  if (toolNames.length === 0 && (!toolCalls || toolCalls.length === 0)) {
    return null;
  }

  const items = buildItems(toolNames, toolCalls, toolResults);

  const handleExpand = (idx: number) => {
    if (expandedIdx === idx) {
      setExpandedIdx(null);
      setOpenResults({});
      setUncappedResults({});
    } else {
      setExpandedIdx(idx);
      // Auto-open the last result
      const item = items[idx];
      const lastEnvIdx = item.envelopes.length - 1;
      setOpenResults(lastEnvIdx >= 0 ? { [lastEnvIdx]: true } : {});
      setUncappedResults({});
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
      {items.map((item, idx) => {
        const hasArgs = item.argsList.some((a) => !!a);
        const hasEnvelope = item.envelopes.some((e) => !!e);
        const expandable = hasArgs || hasEnvelope;
        const isExpanded = expandedIdx === idx;
        const hasError = groupHasError(item.envelopes);
        const envCount = item.envelopes.filter((e) => !!e).length;
        const accentColor = hasError ? t.danger : t.accent;
        const accentBorder = hasError ? t.dangerBorder : t.accentBorder;
        const accentSubtle = hasError ? t.dangerSubtle : t.accentSubtle;

        return (
          <div key={idx} style={{ display: "flex", flexDirection: "column" }}>
            {/* ── Badge / card header ── */}
            <div
              onClick={expandable ? () => handleExpand(idx) : undefined}
              style={{
                display: "inline-flex",
                alignItems: "center",
                alignSelf: "flex-start",
                gap: 5,
                padding: "4px 10px 4px 8px",
                borderRadius: isExpanded ? "6px 6px 0 0" : 6,
                backgroundColor: isExpanded ? accentSubtle : t.overlayLight,
                border: `1px solid ${isExpanded ? accentBorder : t.overlayBorder}`,
                borderBottom: isExpanded ? `1px solid transparent` : undefined,
                cursor: expandable ? "pointer" : "default",
                transition: "all 0.15s ease",
                position: "relative",
                zIndex: 1,
              }}
            >
              <Wrench size={11} color={isExpanded ? accentColor : t.textDim} />
              <span
                style={{
                  fontSize: 11,
                  color: isExpanded ? accentColor : t.textMuted,
                  fontFamily: "'Menlo', monospace",
                  fontWeight: isExpanded ? 600 : 400,
                }}
              >
                {item.name}
                {item.count > 1 ? ` \u00d7${item.count}` : ""}
              </span>
              {envCount > 0 && !isExpanded && (
                <span
                  style={{
                    fontSize: 10,
                    color: hasError ? t.danger : t.textDim,
                    fontFamily: "'Menlo', monospace",
                  }}
                >
                  \u00b7 {envCount} {envCount === 1 ? "result" : "results"}
                </span>
              )}
              {expandable &&
                (isExpanded ? (
                  <ChevronDown size={11} color={isExpanded ? accentColor : t.textDim} />
                ) : (
                  <ChevronRight size={11} color={t.textDim} />
                ))}
            </div>

            {/* ── Expanded card body ── */}
            {isExpanded && (
              <div
                style={{
                  borderLeft: `2px solid ${accentColor}`,
                  borderRight: `1px solid ${accentBorder}`,
                  borderBottom: `1px solid ${accentBorder}`,
                  borderRadius: "0 0 6px 6px",
                  backgroundColor: t.overlayLight,
                  marginLeft: 0,
                  marginTop: -1,
                  padding: "8px 0",
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                }}
              >
                {/* Args section (if any) */}
                {hasArgs && (() => {
                  const argsToShow = item.argsList
                    .map((a) => formatToolArgs(a))
                    .filter((a): a is string => a !== null);
                  if (argsToShow.length === 0) return null;
                  return (
                    <div
                      style={{
                        maxHeight: 200,
                        overflowY: "auto",
                        padding: "0 12px",
                        marginBottom: 4,
                      }}
                    >
                      {argsToShow.map((formatted, i) => (
                        <div key={i}>
                          {argsToShow.length > 1 && (
                            <div
                              style={{
                                fontSize: 10,
                                color: t.textDim,
                                fontWeight: 600,
                                marginTop: i > 0 ? 6 : 0,
                                marginBottom: 2,
                                textTransform: "uppercase",
                                letterSpacing: 0.5,
                              }}
                            >
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

                {/* Results section */}
                {item.envelopes.map((env, i) => {
                  if (!env) return null;
                  const isError = isErrorEnvelope(env);
                  const isOpen = openResults[i] ?? false;
                  const isCapped = !uncappedResults[i];
                  const summary = resultSummary(env);
                  const singleResult = item.envelopes.filter((e) => !!e).length === 1;

                  return (
                    <div key={`env-${i}`}>
                      {/* Result header — clickable to toggle */}
                      <div
                        onClick={() => toggleResult(i)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          padding: "4px 12px",
                          cursor: "pointer",
                          transition: "background-color 0.1s",
                          borderTop: i > 0 ? `1px solid ${t.surfaceBorder}` : undefined,
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.backgroundColor = t.surfaceOverlay;
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.backgroundColor = "transparent";
                        }}
                      >
                        {isOpen ? (
                          <ChevronDown size={10} color={t.textDim} />
                        ) : (
                          <ChevronRight size={10} color={t.textDim} />
                        )}
                        {!singleResult && (
                          <span
                            style={{
                              fontSize: 10,
                              color: t.textDim,
                              fontWeight: 600,
                              textTransform: "uppercase",
                              letterSpacing: 0.5,
                              flexShrink: 0,
                            }}
                          >
                            Result {i + 1}
                          </span>
                        )}
                        {isError && (
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 600,
                              color: t.danger,
                              background: t.dangerSubtle,
                              border: `1px solid ${t.dangerBorder}`,
                              borderRadius: 3,
                              padding: "0 4px",
                              flexShrink: 0,
                            }}
                          >
                            error
                          </span>
                        )}
                        {summary && !isOpen && (
                          <span
                            style={{
                              fontSize: 11,
                              color: isError ? t.dangerMuted : t.textDim,
                              fontFamily: "'Menlo', monospace",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              flex: 1,
                              minWidth: 0,
                            }}
                          >
                            {summary}
                          </span>
                        )}
                      </div>

                      {/* Result body */}
                      {isOpen && (
                        <div
                          style={{
                            position: "relative",
                            margin: "0 12px 4px",
                            maxHeight: isCapped ? 400 : undefined,
                            overflow: isCapped ? "hidden" : undefined,
                          }}
                        >
                          {isError ? (
                            <ErrorResult env={env} t={t} sessionId={sessionId} />
                          ) : (
                            <RichToolResult envelope={env} sessionId={sessionId} t={t} />
                          )}
                          {/* Fade + "Show all" for capped content */}
                          {isCapped && (env.byte_size > 2000 || (env.body ?? "").length > 1500) && (
                            <div
                              style={{
                                position: "absolute",
                                bottom: 0,
                                left: 0,
                                right: 0,
                                height: 60,
                                background: `linear-gradient(transparent, ${t.overlayLight})`,
                                display: "flex",
                                alignItems: "flex-end",
                                justifyContent: "center",
                                paddingBottom: 6,
                              }}
                            >
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  uncapResult(i);
                                }}
                                style={{
                                  fontSize: 11,
                                  color: t.accent,
                                  background: t.surfaceRaised,
                                  border: `1px solid ${t.accentBorder}`,
                                  borderRadius: 4,
                                  padding: "2px 10px",
                                  cursor: "pointer",
                                }}
                              >
                                Show all
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Compact error result — extracts the error message and renders it with
 *  danger styling instead of dumping the raw JSON. */
function ErrorResult({
  env,
  t,
  sessionId,
}: {
  env: ToolResultEnvelope;
  t: ThemeTokens;
  sessionId?: string;
}) {
  const body = env.body ?? env.plain_body ?? "";
  let errorMsg = body;
  try {
    const parsed = JSON.parse(body);
    if (typeof parsed?.error === "string") {
      errorMsg = parsed.error;
    } else if (typeof parsed?.error === "object") {
      errorMsg = JSON.stringify(parsed.error, null, 2);
    }
  } catch {
    // use raw body
  }

  // If the error message is very short, render inline. Otherwise use the
  // standard renderer with danger border.
  if (errorMsg.length < 200 && !errorMsg.includes("\n")) {
    return (
      <div
        style={{
          padding: "6px 10px",
          borderRadius: 4,
          background: t.dangerSubtle,
          borderLeft: `2px solid ${t.danger}`,
          fontSize: 12,
          fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
          color: t.dangerMuted,
          lineHeight: 1.5,
        }}
      >
        {errorMsg}
      </div>
    );
  }

  // Longer error — fall back to RichToolResult with a danger wrapper
  return (
    <div
      style={{
        borderLeft: `2px solid ${t.danger}`,
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      <RichToolResult envelope={env} sessionId={sessionId} t={t} />
    </div>
  );
}
