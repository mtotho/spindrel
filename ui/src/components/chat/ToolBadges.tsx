/**
 * Tool badges — persisted tool activity for default chat mode.
 *
 * New persisted rows prefer the normalized `tool_call.summary` contract.
 * Legacy rows still fall back to raw tool names + envelopes so historical
 * messages keep rendering.
 */

import { useMemo, useState } from "react";
import { Wrench, ChevronRight, ChevronDown, AlertCircle, CheckCircle2 } from "lucide-react";
import { formatToolArgs } from "./toolCallUtils";
import type { ToolCall, ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { RichToolResult } from "./RichToolResult";
import { ToolTraceStrip, type TraceTick } from "./ToolTraceStrip";
import {
  buildPersistedToolEntries,
  detailRows,
  envelopeBodyText,
  envelopeBodyLength,
  resultSummary,
  type SharedToolTranscriptEntry,
} from "./toolTranscriptModel";

const TRACE_STRIP_THRESHOLD = 4;
const CODE_FONT_STACK = "'Menlo', 'Monaco', 'Consolas', monospace";
const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

function toneColor(isError: boolean, t: ThemeTokens): string {
  return isError ? t.dangerMuted : t.textMuted;
}

function renderDiffTitle(label: string | null | undefined, metaLabel: string | null | undefined, t: ThemeTokens) {
  if (!label?.trim()) return null;
  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "baseline",
        gap: 4,
        margin: "8px 0 4px 10px",
        fontFamily: TERMINAL_FONT_STACK,
        fontSize: 11.5,
        lineHeight: 1.4,
        color: t.textMuted,
      }}
    >
      <span style={{ color: t.text, fontWeight: 600 }}>{label.trim()}</span>
      {metaLabel && <span style={{ color: t.textMuted }}>{metaLabel}</span>}
    </div>
  );
}

function renderDiffBlock(detail: string, t: ThemeTokens, rowId: string, isTerminalMode = false, titleLabel?: string | null, titleMeta?: string | null) {
  const rows = detailRows(detail).filter((line) => (
    !isTerminalMode || (line.sign !== "---" && line.sign !== "+++" && !line.text.startsWith("---") && !line.text.startsWith("+++"))
  ));
  return (
    <>
      {isTerminalMode && renderDiffTitle(titleLabel, titleMeta, t)}
      <div
        style={{
          marginLeft: 10,
          marginTop: isTerminalMode ? 0 : 6,
          fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : CODE_FONT_STACK,
          fontSize: isTerminalMode ? 11 : 11.5,
          lineHeight: 1.45,
        }}
      >
        {rows.map((line, lineIndex) => (
          <div
            key={`${rowId}-detail-${lineIndex}`}
            style={{
              display: "grid",
              gridTemplateColumns: "38px 14px minmax(0, 1fr)",
              gap: 8,
              alignItems: "start",
              background: line.tone === "success"
                ? t.successSubtle
                : line.tone === "danger"
                  ? t.dangerSubtle
                  : line.tone === "accent"
                    ? t.overlayLight
                    : "transparent",
              borderRadius: 3,
            }}
          >
            <span
              style={{
                color: t.textDim,
                textAlign: "right",
                userSelect: "none",
                padding: "0 0 0 2px",
              }}
            >
              {line.lineNumber ?? ""}
            </span>
            <span
              style={{
                color: line.tone === "success"
                  ? t.success
                  : line.tone === "danger"
                    ? t.danger
                    : line.tone === "accent"
                      ? t.accent
                      : t.textDim,
                textAlign: "center",
                userSelect: "none",
              }}
            >
              {line.sign ?? ""}
            </span>
            <span
              style={{
                color: line.tone === "success"
                  ? t.success
                  : line.tone === "danger"
                    ? t.danger
                    : line.tone === "accent"
                      ? t.accent
                      : t.textMuted,
                padding: "0 4px 0 0",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                overflowWrap: "anywhere",
                fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : CODE_FONT_STACK,
              }}
            >
              {line.text || " "}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

export function ToolBadges({
  toolNames,
  toolCalls,
  toolResults,
  entries,
  sessionId,
  channelId,
  botId,
  chatMode = "default",
  compact = false,
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

  const stripMode = striped ?? (resolvedEntries.length >= TRACE_STRIP_THRESHOLD);
  if (stripMode) {
    return <ToolTraceStrip ticks={ticks} onExpand={() => setStriped(false)} t={t} />;
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

export function DefaultToolRows({
  entries,
  expandedIdx,
  setExpandedIdx,
  t,
  chatMode = "default",
  sessionId,
  channelId,
  botId,
  onApproval,
  decidingIds,
}: {
  entries: SharedToolTranscriptEntry[];
  expandedIdx: number | null;
  setExpandedIdx: (value: number | null) => void;
  t: ThemeTokens;
  chatMode?: "default" | "terminal";
  sessionId?: string;
  channelId?: string;
  botId?: string;
  onApproval?: (approvalId: string, approved: boolean) => void;
  decidingIds?: Set<string>;
}) {
  const isTerminalMode = chatMode === "terminal";

  return (
    <div
      className="flex flex-col"
      style={{ gap: isTerminalMode ? 7 : 6, marginTop: isTerminalMode ? 8 : 6 }}
    >
      {entries.map((entry, idx) => {
        const formattedArgs = entry.args ? formatToolArgs(entry.args) : null;
        const expandable = entry.detailKind === "expandable" && (!!formattedArgs || !!entry.env);
        const isExpanded = expandedIdx === idx;

        return (
          <div key={entry.id} className="flex flex-col">
            <div
              role={expandable ? "button" : undefined}
              tabIndex={expandable ? 0 : undefined}
              aria-expanded={expandable ? isExpanded : undefined}
              onClick={expandable ? () => setExpandedIdx(isExpanded ? null : idx) : undefined}
              onKeyDown={expandable ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setExpandedIdx(isExpanded ? null : idx);
                }
              } : undefined}
              className={`${isTerminalMode ? "flex w-full max-w-full" : "inline-flex self-start"} items-center gap-1.5 py-0.5 transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-offset-1 ${expandable ? "cursor-pointer" : "cursor-default"}`}
              style={{
                fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
                fontSize: isTerminalMode ? 11.5 : undefined,
                lineHeight: isTerminalMode ? 1.5 : undefined,
                minWidth: isTerminalMode ? 0 : undefined,
              }}
            >
              {isTerminalMode ? (
                <span
                  style={{
                    color: expandable ? (entry.isError ? t.danger : t.text) : t.textDim,
                    width: 12,
                    flexShrink: 0,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: expandable ? 11.5 : 10.5,
                    lineHeight: 1,
                  }}
                >
                  {expandable ? (isExpanded ? "" : "›") : "·"}
                </span>
              ) : (
                <Wrench size={11} style={{ color: t.textDim, flexShrink: 0 }} />
              )}
              <span
                className="text-[10px] font-medium uppercase tracking-wider"
                style={{
                  color: isTerminalMode ? (entry.isError ? t.danger : t.text) : (entry.isError ? t.dangerMuted : t.textDim),
                  textTransform: isTerminalMode ? "none" : undefined,
                  letterSpacing: isTerminalMode ? "normal" : undefined,
                  fontSize: isTerminalMode ? 11.5 : undefined,
                  whiteSpace: isTerminalMode ? "nowrap" : undefined,
                  flexShrink: isTerminalMode ? 0 : undefined,
                }}
              >
                {entry.label}
              </span>
              {entry.metaLabel && (
                <span
                  className="text-[10px] font-mono normal-case overflow-hidden text-ellipsis"
                  style={{
                    color: t.textDim,
                    fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
                    fontSize: isTerminalMode ? 10.5 : undefined,
                    minWidth: isTerminalMode ? 0 : undefined,
                    maxWidth: isTerminalMode ? "100%" : undefined,
                    whiteSpace: "nowrap",
                  }}
                >
                  {entry.metaLabel}
                </span>
              )}
              {entry.target && (
                <span
                  className="text-[10px] font-mono normal-case overflow-hidden text-ellipsis"
                  style={{
                    color: t.textMuted,
                    opacity: 0.85,
                    fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
                    fontSize: isTerminalMode ? 10.5 : undefined,
                    minWidth: isTerminalMode ? 0 : undefined,
                    maxWidth: isTerminalMode ? "100%" : undefined,
                    whiteSpace: "nowrap",
                  }}
                >
                  {"→"} {entry.target}
                </span>
              )}
              {!isExpanded && entry.detailKind === "expandable" && (entry.previewText || entry.env) && (
                <span
                  className="text-[11px] overflow-hidden text-ellipsis whitespace-nowrap"
                  style={{
                    color: toneColor(entry.isError, t),
                    flex: isTerminalMode ? "1 1 0" : undefined,
                    minWidth: 0,
                    maxWidth: isTerminalMode ? "100%" : 360,
                  }}
                >
                  {entry.previewText || resultSummary(entry.env)}
                </span>
              )}
              {entry.env && !expandable && entry.detailKind !== "collapsed-read" && (
                entry.isError ? (
                  <AlertCircle size={12} style={{ color: t.danger }} />
                ) : (
                  <CheckCircle2 size={12} style={{ color: t.success, opacity: 0.7 }} />
                )
              )}
              {!isTerminalMode && expandable &&
                (isExpanded ? (
                  <ChevronDown size={11} style={{ color: t.textDim }} />
                ) : (
                  <ChevronRight size={11} style={{ color: t.textDim }} />
                ))}
            </div>

            {entry.detailKind === "inline-diff" && entry.detail && renderDiffBlock(entry.detail, t, entry.id, isTerminalMode, entry.label, entry.metaLabel)}

            {entry.approval && onApproval && (
              <div
                className="rounded-b-lg border border-t-0 overflow-hidden px-3 py-2 flex items-center gap-2 flex-wrap"
                style={{
                  borderColor: t.surfaceBorder,
                  backgroundColor: t.surfaceRaised,
                }}
              >
                <span className="text-[11px]" style={{ color: t.textMuted, flex: 1, minWidth: 120 }}>
                  {entry.approval.reason || "Tool policy requires approval before execution"}
                </span>
                <button
                  type="button"
                  disabled={decidingIds?.has(entry.approval.approvalId)}
                  onClick={() => onApproval(entry.approval!.approvalId, true)}
                  className="text-[12px] font-semibold px-3 py-1 rounded"
                  style={{
                    border: "none",
                    cursor: decidingIds?.has(entry.approval.approvalId) ? "default" : "pointer",
                    backgroundColor: t.success,
                    color: "#fff",
                    opacity: decidingIds?.has(entry.approval.approvalId) ? 0.6 : 1,
                  }}
                >
                  Approve
                </button>
                <button
                  type="button"
                  disabled={decidingIds?.has(entry.approval.approvalId)}
                  onClick={() => onApproval(entry.approval!.approvalId, false)}
                  className="text-[12px] font-semibold px-3 py-1 rounded"
                  style={{
                    border: "none",
                    cursor: decidingIds?.has(entry.approval.approvalId) ? "default" : "pointer",
                    backgroundColor: t.danger,
                    color: "#fff",
                    opacity: decidingIds?.has(entry.approval.approvalId) ? 0.6 : 1,
                  }}
                >
                  Deny
                </button>
              </div>
            )}

            {isExpanded && expandable && (
              <div
                className="rounded-lg border overflow-hidden mt-1"
                style={{
                  borderColor: isTerminalMode ? "transparent" : t.surfaceBorder,
                  backgroundColor: isTerminalMode ? "transparent" : t.surfaceRaised,
                  borderRadius: isTerminalMode ? 0 : undefined,
                }}
              >
                {formattedArgs && (
                  <div
                    className="max-h-[200px] overflow-y-auto px-3 py-2 border-b"
                    style={{
                      borderColor: isTerminalMode ? "transparent" : t.surfaceBorder,
                      padding: isTerminalMode ? "2px 0 4px 18px" : undefined,
                      overflowY: isTerminalMode ? "hidden" : undefined,
                    }}
                  >
                    <pre className="m-0 text-[11px] font-mono whitespace-pre-wrap break-words leading-relaxed" style={{ color: t.textMuted }}>
                      {formattedArgs}
                    </pre>
                  </div>
                )}

                {entry.env && (
                  <div
                    className="relative px-3 py-1 pb-2"
                    style={isTerminalMode ? { padding: "2px 0 2px 18px" } : undefined}
                  >
                    {entry.isError ? (
                      <ErrorResult env={entry.env} t={t} chatMode={chatMode} sessionId={sessionId} channelId={channelId} botId={botId} />
                    ) : (
                      <RichToolResult
                        envelope={entry.env}
                        sessionId={sessionId}
                        channelId={channelId}
                        botId={botId}
                        rendererVariant={isTerminalMode ? "terminal-chat" : "default-chat"}
                        chromeMode="embedded"
                        t={t}
                      />
                    )}
                    {!entry.env.truncated && (entry.env.byte_size > 2000 || envelopeBodyLength(entry.env) > 1500) && (
                      <div
                        className="absolute bottom-0 left-0 right-0 h-12 flex items-end justify-center pb-1.5 pointer-events-none"
                        style={{ background: isTerminalMode ? "transparent" : `linear-gradient(transparent, ${t.surfaceRaised})` }}
                      />
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ErrorResult({
  env,
  t,
  chatMode = "default",
  sessionId,
  channelId,
  botId,
}: {
  env: ToolResultEnvelope;
  t: ThemeTokens;
  chatMode?: "default" | "terminal";
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
          fontFamily: CODE_FONT_STACK,
          color: t.dangerMuted,
          lineHeight: 1.5,
        }}
      >
        {errorMsg}
      </div>
    );
  }

  return (
    <RichToolResult
      envelope={env}
      sessionId={sessionId}
      channelId={channelId}
      botId={botId}
      rendererVariant={chatMode === "terminal" ? "terminal-chat" : "default-chat"}
      chromeMode="embedded"
      t={t}
    />
  );
}
