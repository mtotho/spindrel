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

import { useEffect, useState, useCallback, useMemo } from "react";
import { Wrench, ChevronRight, ChevronDown, AlertCircle, CheckCircle2 } from "lucide-react";
import { formatToolArgs } from "./toolCallUtils";
import { normalizeToolCall } from "../../types/api";
import type { ToolCall, ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { RichToolResult } from "./RichToolResult";
import { ToolTraceStrip, type TraceTick } from "./ToolTraceStrip";

/** Threshold for collapsing a tool-call sequence into a trace strip. */
const TRACE_STRIP_THRESHOLD = 4;

interface ToolItem {
  name: string;
  count: number;
  argsList: (string | undefined)[];
  envelopes: (ToolResultEnvelope | undefined)[];
}

function envelopeBodyText(env: ToolResultEnvelope | undefined): string {
  if (!env) return "";
  if (typeof env.body === "string") return env.body;
  return env.plain_body ?? "";
}

function envelopeBodyLength(env: ToolResultEnvelope | undefined): number {
  if (!env) return 0;
  if (typeof env.body === "string") return env.body.length;
  if (env.body && typeof env.body === "object") return JSON.stringify(env.body).length;
  return (env.plain_body ?? "").length;
}

/**
 * For introspection tools (`get_tool_info`, `get_skill`) pull the target name
 * out of the arguments so it renders inline on the pill — answers "which tool
 * / skill is being inspected" without needing to expand the badge.
 */
function introspectionTarget(name: string, argsList: (string | undefined)[]): string | null {
  const short = name.includes("-") ? name.slice(name.lastIndexOf("-") + 1) : name;
  if (short !== "get_tool_info" && short !== "get_skill") return null;
  for (const raw of argsList) {
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw);
      const target = parsed?.tool_name ?? parsed?.skill_id;
      if (typeof target === "string" && target) return target;
    } catch {
      // ignore malformed args
    }
  }
  return null;
}

function summaryLabel(tc: ToolCall | undefined): string | null {
  const label = tc?.summary?.target_label;
  return typeof label === "string" && label.trim() ? label.trim() : null;
}

/** Check if an envelope represents an error result. */
function isErrorEnvelope(env: ToolResultEnvelope | undefined): boolean {
  if (!env) return false;
  const body = envelopeBodyText(env);
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
      const parsed = JSON.parse(envelopeBodyText(env));
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
      const displayName = tc?.summary?.label || norm.name;
      const last = items[items.length - 1];
      if (last && last.name === displayName) {
        last.count++;
        last.argsList.push(norm.arguments);
        last.envelopes.push(env);
      } else {
        items.push({
          name: displayName,
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
  channelId,
  botId,
  compact = false,
  autoExpand = false,
  t,
}: {
  toolNames: string[];
  toolCalls?: ToolCall[];
  toolResults?: ToolResultEnvelope[];
  sessionId?: string;
  channelId?: string;
  botId?: string;
  compact?: boolean;
  autoExpand?: boolean;
  t: ThemeTokens;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [openResults, setOpenResults] = useState<Record<number, boolean>>({});
  const [uncappedResults, setUncappedResults] = useState<Record<number, boolean>>({});
  const [striped, setStriped] = useState<boolean | null>(null);

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

  // Build items + per-call ticks BEFORE any early return so the hook order
  // is stable across renders. useMemo avoids recomputing on state changes.
  const items = useMemo(
    () => buildItems(toolNames, toolCalls, toolResults),
    [toolNames, toolCalls, toolResults],
  );
  const ticks: TraceTick[] = useMemo(() => {
    const out: TraceTick[] = [];
    for (const item of items) {
      for (let i = 0; i < item.count; i++) {
        const env = item.envelopes[i];
        out.push({
          toolName: item.name,
          target: summaryLabel(toolCalls?.find((tc) => normalizeToolCall(tc).name === item.name)) || introspectionTarget(item.name, [item.argsList[i]]),
          isError: isErrorEnvelope(env),
        });
      }
    }
    return out;
  }, [items]);

  if (toolNames.length === 0 && (!toolCalls || toolCalls.length === 0)) {
    return null;
  }

  // Default to strip mode when there are 4+ tool items in this turn. The user
  // can click the strip to reveal the full badge stack. Once toggled, we
  // remember their choice for this component's lifetime.
  const stripMode = striped ?? (items.length >= TRACE_STRIP_THRESHOLD);
  if (stripMode) {
    return <ToolTraceStrip ticks={ticks} onExpand={() => setStriped(false)} t={t} />;
  }

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
    <div className="flex flex-col gap-1.5 mt-1.5">
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
          <div key={idx} className="flex flex-col">
            {/* ── Badge pill ── */}
            <div
              role={expandable ? "button" : undefined}
              tabIndex={expandable ? 0 : undefined}
              aria-expanded={expandable ? isExpanded : undefined}
              onClick={expandable ? () => handleExpand(idx) : undefined}
              onKeyDown={expandable ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleExpand(idx);
                }
              } : undefined}
              className={`inline-flex items-center self-start gap-1.5 px-2.5 py-1 transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-offset-1 ${expandable ? "cursor-pointer" : "cursor-default"} ${isExpanded ? "rounded-t-lg border border-b-0" : "rounded-lg border"}`}
              style={{
                backgroundColor: t.surfaceRaised,
                borderColor: t.surfaceBorder,
              }}
              onMouseEnter={expandable ? (e) => {
                if (!isExpanded) e.currentTarget.style.backgroundColor = `${t.surfaceRaised}`;
                e.currentTarget.style.borderColor = t.textDim;
              } : undefined}
              onMouseLeave={expandable ? (e) => {
                e.currentTarget.style.backgroundColor = t.surfaceRaised;
                e.currentTarget.style.borderColor = t.surfaceBorder;
              } : undefined}
              onFocus={expandable ? (e) => {
                e.currentTarget.style.borderColor = t.textDim;
              } : undefined}
              onBlur={expandable ? (e) => {
                e.currentTarget.style.borderColor = t.surfaceBorder;
              } : undefined}
            >
              <Wrench size={11} style={{ color: t.textDim, flexShrink: 0 }} />
              <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: t.textDim }}>
                {item.name}
                {item.count > 1 ? ` \u00d7${item.count}` : ""}
              </span>
              {(() => {
                const target = introspectionTarget(item.name, item.argsList);
                return target ? (
                  <span
                    className="text-[10px] font-mono normal-case"
                    style={{ color: t.textMuted, opacity: 0.85 }}
                  >
                    {"\u2192"} {target}
                  </span>
                ) : null;
              })()}
              {/* Status dots — compact success/error indicator */}
              {envCount > 0 && !isExpanded && (
                <span className="inline-flex items-center gap-1">
                  {errorCount > 0 && (
                    <span className="inline-flex items-center gap-0.5">
                      <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: t.danger }} />
                      {errorCount > 1 && (
                        <span className="text-[10px]" style={{ color: t.danger }}>{errorCount}</span>
                      )}
                    </span>
                  )}
                  {successCount > 0 && (
                    <span className="inline-flex items-center gap-0.5">
                      <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: t.success }} />
                      {successCount > 1 && (
                        <span className="text-[10px]" style={{ color: t.success }}>{successCount}</span>
                      )}
                    </span>
                  )}
                </span>
              )}
              {expandable &&
                (isExpanded ? (
                  <ChevronDown size={11} style={{ color: t.textDim }} />
                ) : (
                  <ChevronRight size={11} style={{ color: t.textDim }} />
                ))}
            </div>

            {/* ── Expanded panel ── */}
            {isExpanded && (
              <div
                className="rounded-b-lg border border-t-0 overflow-hidden"
                style={{
                  borderColor: t.surfaceBorder,
                  backgroundColor: t.surfaceRaised,
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
                      className="max-h-[200px] overflow-y-auto px-3 py-2 border-b"
                      style={{ borderColor: t.surfaceBorder }}
                    >
                      {argsToShow.map((formatted, i) => (
                        <div key={i}>
                          {argsToShow.length > 1 && (
                            <div className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${i > 0 ? "mt-1.5" : ""}`} style={{ color: t.textDim }}>
                              Call {i + 1}
                            </div>
                          )}
                          <pre className="m-0 text-[11px] font-mono whitespace-pre-wrap break-words leading-relaxed" style={{ color: t.textMuted }}>
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
                        className="flex items-center gap-1.5 px-3 py-1.5 cursor-pointer transition-colors duration-100 hover:bg-white/[0.02]"
                        style={{
                          borderTop: i > 0 ? `1px solid ${t.surfaceBorder}` : undefined,
                          backgroundColor: isOpen ? "rgba(255,255,255,0.02)" : "transparent",
                        }}
                      >
                        {isOpen ? (
                          <ChevronDown size={10} style={{ color: t.textDim }} />
                        ) : (
                          <ChevronRight size={10} style={{ color: t.textDim }} />
                        )}
                        {/* Status icon */}
                        {isError ? (
                          <AlertCircle size={12} style={{ color: t.danger }} />
                        ) : (
                          <CheckCircle2 size={12} style={{ color: t.success, opacity: 0.7 }} />
                        )}
                        {!singleResult && (
                          <span className="text-[10px] font-semibold uppercase tracking-wider flex-shrink-0" style={{ color: t.textDim }}>
                            Result {i + 1}
                          </span>
                        )}
                        {summary && !isOpen && (
                          <span
                            className="text-[11px] overflow-hidden text-ellipsis whitespace-nowrap flex-1 min-w-0"
                            style={{ color: isError ? t.dangerMuted : t.textMuted }}
                          >
                            {summary}
                          </span>
                        )}
                      </div>

                      {/* Result body */}
                      {isOpen && (
                        <div
                          className="relative px-3 py-1 pb-2"
                          style={{
                            maxHeight: isCapped ? 400 : undefined,
                            overflow: isCapped ? "hidden" : undefined,
                          }}
                        >
                          {isError ? (
                            <ErrorResult env={env} t={t} sessionId={sessionId} channelId={channelId} botId={botId} />
                          ) : (
                            <RichToolResult envelope={env} sessionId={sessionId} channelId={channelId} botId={botId} t={t} />
                          )}
                          {isCapped && (env.byte_size > 2000 || envelopeBodyLength(env) > 1500) && (
                            <div
                              className="absolute bottom-0 left-0 right-0 h-12 flex items-end justify-center pb-1.5"
                              style={{ background: `linear-gradient(transparent, ${t.surfaceRaised})` }}
                            >
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  uncapResult(i);
                                }}
                                className="text-[11px] rounded px-2.5 py-0.5 cursor-pointer transition-colors duration-100 border bg-transparent hover:opacity-80"
                                style={{
                                  color: t.textMuted,
                                  borderColor: t.surfaceBorder,
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

/** Compact error result — extracts the error message and shows it cleanly. */
function ErrorResult({
  env,
  t,
  sessionId,
  channelId,
  botId,
}: {
  env: ToolResultEnvelope;
  t: ThemeTokens;
  sessionId?: string;
  channelId?: string;
  botId?: string;
}) {
  const body = envelopeBodyText(env);
  let errorMsg: string = body;
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

  return <RichToolResult envelope={env} sessionId={sessionId} channelId={channelId} botId={botId} t={t} />;
}
