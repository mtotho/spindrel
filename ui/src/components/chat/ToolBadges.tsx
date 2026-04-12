/**
 * Tool badges — shows tools used on persisted messages with expandable results.
 *
 * Design: badge pill is the toggle. Expanded state renders a clean card below
 * with per-result rows. Only the latest bot message auto-expands; older
 * messages render collapsed pill badges with a result count hint.
 *
 * Within an expanded card, individual results are independently expandable.
 * The latest result auto-opens; older ones show a one-line summary.
 */

import { useEffect, useState, useCallback } from "react";
import { Wrench, ChevronRight, ChevronDown, AlertCircle, CheckCircle2 } from "lucide-react";
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
  autoExpand?: boolean;
  t: ThemeTokens;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [openResults, setOpenResults] = useState<Record<number, boolean>>({});
  const [uncappedResults, setUncappedResults] = useState<Record<number, boolean>>({});

  const toggleResult = useCallback((i: number) => {
    setOpenResults((prev) => ({ ...prev, [i]: !prev[i] }));
  }, []);

  const uncapResult = useCallback((i: number) => {
    setUncappedResults((prev) => ({ ...prev, [i]: true }));
  }, []);

  useEffect(() => {
    if (compact || !autoExpand) return;
    if (expandedIdx !== null) return;
    if (!toolResults || toolResults.length === 0) return;
    const items = buildItems(toolNames, toolCalls, toolResults);
    for (let i = 0; i < items.length; i++) {
      if (items[i].envelopes.some((e) => e?.display === "inline")) {
        setExpandedIdx(i);
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
        const errorCount = item.envelopes.filter(isErrorEnvelope).length;
        const successCount = envCount - errorCount;

        return (
          <div key={idx} style={{ display: "flex", flexDirection: "column" }}>
            {/* ── Badge pill ── */}
            <div
              onClick={expandable ? () => handleExpand(idx) : undefined}
              style={{
                display: "inline-flex",
                alignItems: "center",
                alignSelf: "flex-start",
                gap: 5,
                padding: "4px 10px 4px 8px",
                borderRadius: isExpanded ? "4px 4px 0 0" : 4,
                backgroundColor: t.overlayLight,
                border: `1px solid ${isExpanded ? t.surfaceBorder : t.overlayBorder}`,
                borderBottom: isExpanded ? "none" : undefined,
                cursor: expandable ? "pointer" : "default",
                transition: "background-color 0.15s, border-color 0.15s",
              }}
              onMouseEnter={expandable ? (e) => {
                if (!isExpanded) e.currentTarget.style.backgroundColor = t.surfaceOverlay;
              } : undefined}
              onMouseLeave={expandable ? (e) => {
                if (!isExpanded) e.currentTarget.style.backgroundColor = t.overlayLight;
              } : undefined}
            >
              <Wrench size={11} color={t.textDim} />
              <span
                style={{
                  fontSize: 11,
                  color: t.textMuted,
                  fontFamily: "'Menlo', monospace",
                }}
              >
                {item.name}
                {item.count > 1 ? ` \u00d7${item.count}` : ""}
              </span>
              {/* Status dots — compact success/error indicator */}
              {envCount > 0 && !isExpanded && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                  {errorCount > 0 && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
                      <span style={{
                        width: 6, height: 6, borderRadius: "50%",
                        backgroundColor: t.danger, display: "inline-block",
                      }} />
                      {errorCount > 1 && (
                        <span style={{ fontSize: 10, color: t.danger, fontFamily: "'Menlo', monospace" }}>
                          {errorCount}
                        </span>
                      )}
                    </span>
                  )}
                  {successCount > 0 && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
                      <span style={{
                        width: 6, height: 6, borderRadius: "50%",
                        backgroundColor: t.success, display: "inline-block",
                      }} />
                      {successCount > 1 && (
                        <span style={{ fontSize: 10, color: t.success, fontFamily: "'Menlo', monospace" }}>
                          {successCount}
                        </span>
                      )}
                    </span>
                  )}
                </span>
              )}
              {expandable &&
                (isExpanded ? (
                  <ChevronDown size={11} color={t.textDim} />
                ) : (
                  <ChevronRight size={11} color={t.textDim} />
                ))}
            </div>

            {/* ── Expanded panel ── */}
            {isExpanded && (
              <div
                style={{
                  border: `1px solid ${t.surfaceBorder}`,
                  borderTop: "none",
                  borderRadius: "0 8px 8px 8px",
                  backgroundColor: t.surfaceRaised,
                  overflow: "hidden",
                }}
              >
                {/* Args section */}
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
                        padding: "8px 12px",
                        borderBottom: `1px solid ${t.surfaceBorder}`,
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

                {/* Results list */}
                {item.envelopes.map((env, i) => {
                  if (!env) return null;
                  const isError = isErrorEnvelope(env);
                  const isOpen = openResults[i] ?? false;
                  // Don't cap truncated results — RichToolResult has its own
                  // "Show full output" affordance for those.
                  const isCapped = !uncappedResults[i] && !env.truncated;
                  const summary = resultSummary(env);
                  const singleResult = item.envelopes.filter((e) => !!e).length === 1;

                  return (
                    <div key={`env-${i}`}>
                      {/* Result row header */}
                      <div
                        onClick={() => toggleResult(i)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          padding: "6px 12px",
                          cursor: "pointer",
                          transition: "background-color 0.1s",
                          borderTop: i > 0 ? `1px solid ${t.surfaceBorder}` : undefined,
                          backgroundColor: isOpen ? t.surfaceOverlay : "transparent",
                        }}
                        onMouseEnter={(e) => {
                          if (!isOpen) e.currentTarget.style.backgroundColor = t.surfaceOverlay;
                        }}
                        onMouseLeave={(e) => {
                          if (!isOpen) e.currentTarget.style.backgroundColor = "transparent";
                        }}
                      >
                        {isOpen ? (
                          <ChevronDown size={10} color={t.textDim} />
                        ) : (
                          <ChevronRight size={10} color={t.textDim} />
                        )}
                        {/* Status icon */}
                        {isError ? (
                          <AlertCircle size={12} color={t.danger} />
                        ) : (
                          <CheckCircle2 size={12} color={t.success} style={{ opacity: 0.7 }} />
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
                        {summary && !isOpen && (
                          <span
                            style={{
                              fontSize: 11,
                              color: isError ? t.dangerMuted : t.textMuted,
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
                            padding: "4px 12px 8px",
                            maxHeight: isCapped ? 400 : undefined,
                            overflow: isCapped ? "hidden" : undefined,
                            backgroundColor: t.surfaceOverlay,
                          }}
                        >
                          {isError ? (
                            <ErrorResult env={env} t={t} sessionId={sessionId} />
                          ) : (
                            <RichToolResult envelope={env} sessionId={sessionId} t={t} />
                          )}
                          {isCapped && (env.byte_size > 2000 || (env.body ?? "").length > 1500) && (
                            <div
                              style={{
                                position: "absolute",
                                bottom: 0,
                                left: 0,
                                right: 0,
                                height: 48,
                                background: `linear-gradient(transparent, ${t.surfaceOverlay})`,
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
                                  color: t.textMuted,
                                  background: t.surfaceRaised,
                                  border: `1px solid ${t.surfaceBorder}`,
                                  borderRadius: 4,
                                  padding: "2px 10px",
                                  cursor: "pointer",
                                  transition: "color 0.1s",
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.color = t.text; }}
                                onMouseLeave={(e) => { e.currentTarget.style.color = t.textMuted; }}
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

/** Compact error result — extracts the error message and shows it cleanly. */
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

  if (errorMsg.length < 200 && !errorMsg.includes("\n")) {
    return (
      <div
        style={{
          padding: "6px 10px",
          borderRadius: 6,
          background: t.dangerSubtle,
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

  return <RichToolResult envelope={env} sessionId={sessionId} t={t} />;
}
