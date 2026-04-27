/**
 * Tool badges — persisted tool activity for default chat mode.
 *
 * New persisted rows prefer the normalized `tool_call.summary` contract.
 * Legacy rows still fall back to raw tool names + envelopes so historical
 * messages keep rendering.
 */

import { useMemo, useState, type ReactNode } from "react";
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

function EndTruncatedPath({
  value,
  color,
  fontFamily,
  fontSize,
}: {
  value: string;
  color: string;
  fontFamily?: string;
  fontSize?: number;
}) {
  return (
    <span
      className="min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap"
      title={value}
      style={{
        color,
        direction: "rtl",
        display: "inline-block",
        fontFamily,
        fontSize,
        textAlign: "left",
      }}
    >
      {value}
    </span>
  );
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
  onApproval?: (approvalId: string, approved: boolean, options?: { bypassRestOfTurn?: boolean }) => void;
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
              className="flex w-full max-w-full min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 py-0.5 transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
              style={{
                fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
                fontSize: isTerminalMode ? 11.5 : undefined,
                lineHeight: isTerminalMode ? 1.5 : undefined,
                minWidth: 0,
                cursor: expandable ? "pointer" : "default",
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
                  minWidth: 0,
                  maxWidth: "100%",
                  overflowWrap: "anywhere",
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
                  className="inline-flex min-w-0 max-w-full items-baseline gap-1 text-[10px] font-mono normal-case"
                  style={{
                    color: t.textMuted,
                    opacity: 0.85,
                    fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
                    fontSize: isTerminalMode ? 10.5 : undefined,
                    flex: "1 1 12rem",
                  }}
                >
                  <span style={{ flexShrink: 0 }}>{"→"}</span>
                  <EndTruncatedPath
                    value={entry.target}
                    color={t.textMuted}
                    fontFamily={isTerminalMode ? TERMINAL_FONT_STACK : undefined}
                    fontSize={isTerminalMode ? 10.5 : undefined}
                  />
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
              <HarnessAwareApprovalRow
                approval={entry.approval}
                onApproval={onApproval}
                decidingIds={decidingIds}
                t={t}
                chatMode={chatMode}
              />
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

// ---------------------------------------------------------------------------
// HarnessAwareApprovalRow
//
// Single approval row that adapts based on whether the underlying ToolApproval
// row is from a Spindrel-loop tool (`local`/`client`/`mcp`) or from a harness
// (`harness`). Harness rows get:
//   * a tool-arg preview tailored to the tool name (Bash command, Edit diff,
//     Write content, ExitPlanMode plan markdown, fallback JSON);
//   * an "Approve all this turn" button that sends `bypass_rest_of_turn=true`
//     so the harness stops asking for the rest of the current turn.
// ---------------------------------------------------------------------------

function HarnessAwareApprovalRow({
  approval,
  onApproval,
  decidingIds,
  t,
  chatMode = "default",
}: {
  approval: NonNullable<SharedToolTranscriptEntry["approval"]>;
  onApproval: (approvalId: string, approved: boolean, options?: { bypassRestOfTurn?: boolean }) => void;
  decidingIds?: Set<string>;
  t: ThemeTokens;
  chatMode?: "default" | "terminal";
}) {
  const isHarness = approval.toolType === "harness";
  const isTerminalMode = chatMode === "terminal";
  const busy = !!decidingIds?.has(approval.approvalId);
  return (
    <div
      className={isTerminalMode ? "overflow-hidden" : "rounded-b-lg border border-t-0 overflow-hidden"}
      style={{
        borderColor: isTerminalMode ? "transparent" : t.surfaceBorder,
        backgroundColor: isTerminalMode ? "transparent" : t.surfaceRaised,
        marginLeft: isTerminalMode ? 18 : undefined,
        marginTop: isTerminalMode ? 2 : undefined,
        fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
      }}
    >
      {isHarness && approval.toolName && (
        <HarnessToolPreview
          toolName={approval.toolName}
          args={approval.arguments ?? {}}
          t={t}
          chatMode={chatMode}
        />
      )}
      <div
        className="flex items-center gap-2 flex-wrap"
        style={{
          padding: isTerminalMode ? "2px 0 0 0" : "8px 12px",
        }}
      >
        <span className="text-[11px]" style={{ color: t.textMuted, flex: 1, minWidth: 120 }}>
          {approval.reason || "Tool policy requires approval before execution"}
        </span>
        <button
          type="button"
          disabled={busy}
          onClick={() => onApproval(approval.approvalId, true)}
          className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0" : "text-[12px] font-semibold px-3 py-1 rounded"}
          style={{
            border: isTerminalMode ? `1px solid ${t.successBorder}` : "none",
            cursor: busy ? "default" : "pointer",
            backgroundColor: isTerminalMode ? "transparent" : t.success,
            color: isTerminalMode ? t.success : "#fff",
            opacity: busy ? 0.6 : 1,
            fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
          }}
        >
          Approve
        </button>
        {isHarness && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onApproval(approval.approvalId, true, { bypassRestOfTurn: true })}
            className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0" : "text-[12px] font-semibold px-3 py-1 rounded"}
            style={{
              border: `1px solid ${t.successBorder}`,
              cursor: busy ? "default" : "pointer",
              backgroundColor: "transparent",
              color: t.success,
              opacity: busy ? 0.6 : 1,
              fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
            }}
            title="Approve this call AND auto-approve every remaining tool call in this turn. Reverts at end of turn."
          >
            {isTerminalMode ? "Approve turn" : "Approve all this turn"}
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => onApproval(approval.approvalId, false)}
          className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0" : "text-[12px] font-semibold px-3 py-1 rounded"}
          style={{
            border: isTerminalMode ? `1px solid ${t.dangerBorder}` : "none",
            cursor: busy ? "default" : "pointer",
            backgroundColor: isTerminalMode ? "transparent" : t.danger,
            color: isTerminalMode ? t.danger : "#fff",
            opacity: busy ? 0.6 : 1,
            fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
          }}
        >
          Deny
        </button>
      </div>
    </div>
  );
}

function HarnessToolPreview({
  toolName,
  args,
  t,
  chatMode = "default",
}: {
  toolName: string;
  args: Record<string, unknown>;
  t: ThemeTokens;
  chatMode?: "default" | "terminal";
}) {
  const isTerminalMode = chatMode === "terminal";
  const codeFont = isTerminalMode ? TERMINAL_FONT_STACK : CODE_FONT_STACK;
  const stringArg = (key: string): string | null => {
    const v = args[key];
    return typeof v === "string" && v.trim() ? v : null;
  };
  let body: ReactNode = null;
  if (toolName === "Bash") {
    const cmd = stringArg("command");
    const desc = stringArg("description");
    body = (
      <div className="flex flex-col gap-1">
        {desc && (
          <div className="text-[11px]" style={{ color: t.textMuted }}>
            {desc}
          </div>
        )}
        {cmd && (
          <pre
            className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words text-[11.5px]"
            style={{ fontFamily: codeFont, color: t.text }}
          >
            {cmd.length > 800 ? `${cmd.slice(0, 800)}…` : cmd}
          </pre>
        )}
      </div>
    );
  } else if (toolName === "Edit") {
    const file = stringArg("file_path") ?? stringArg("path");
    const oldS = stringArg("old_string") ?? "";
    const newS = stringArg("new_string") ?? "";
    body = (
      <div className="flex flex-col gap-1">
        {file && (
          <div className="text-[11px] font-mono" style={{ color: t.textMuted }}>
            {file}
          </div>
        )}
        <pre
          className="m-0 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11.5px]"
          style={{ fontFamily: codeFont, color: t.text }}
        >
          {oldS && (
            <span style={{ color: t.danger }}>{`- ${oldS.replace(/\n/g, "\n- ")}\n`}</span>
          )}
          {newS && (
            <span style={{ color: t.success }}>{`+ ${newS.replace(/\n/g, "\n+ ")}`}</span>
          )}
        </pre>
      </div>
    );
  } else if (toolName === "Write") {
    const file = stringArg("file_path") ?? stringArg("path");
    const content = stringArg("content") ?? "";
    const lines = content.split(/\r?\n/);
    const previewLines = lines.slice(0, 40);
    const truncated = lines.length > 40;
    body = (
      <div className="flex flex-col gap-1">
        {file && (
          <div className="text-[11px] font-mono" style={{ color: t.textMuted }}>
            {file}
          </div>
        )}
        <pre
          className="m-0 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11.5px]"
          style={{ fontFamily: codeFont, color: t.text }}
        >
          {previewLines.join("\n")}
          {truncated && <span style={{ color: t.textDim }}>{`\n… (${lines.length - 40} more lines)`}</span>}
        </pre>
      </div>
    );
  } else if (toolName === "ExitPlanMode") {
    const plan = stringArg("plan") ?? "";
    body = (
      <pre
        className="m-0 max-h-72 overflow-auto whitespace-pre-wrap break-words text-[11.5px]"
        style={{ fontFamily: codeFont, color: t.text }}
      >
        {plan}
      </pre>
    );
  } else {
    body = (
      <pre
        className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words text-[10.5px]"
        style={{ fontFamily: codeFont, color: t.textMuted }}
      >
        {JSON.stringify(args, null, 2)}
      </pre>
    );
  }
  return (
    <div
      className={isTerminalMode ? "" : "border-b px-3 py-2"}
      style={{
        borderColor: isTerminalMode ? "transparent" : t.surfaceBorder,
        backgroundColor: isTerminalMode ? "transparent" : t.overlayLight,
        padding: isTerminalMode ? "0 0 4px 0" : undefined,
      }}
    >
      <div
        className="text-[10px] font-medium uppercase mb-1"
        style={{
          color: t.textDim,
          letterSpacing: isTerminalMode ? "normal" : undefined,
          fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
        }}
      >
        {toolName}
      </div>
      {body}
    </div>
  );
}
