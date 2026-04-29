import type { ThemeTokens } from "../../theme/tokens";
import type { ToolResultEnvelope } from "../../types/api";
import { RichToolResult } from "./RichToolResult";
import { formatToolArgs } from "./toolCallUtils";
import {
  envelopeBodyText,
  resultSummary,
  type SharedToolTranscriptEntry,
} from "./toolTranscriptModel";
import {
  CodePreviewRenderer,
  TERMINAL_FONT_STACK,
  looksLikeCodePreview,
} from "./CodePreviewRenderer";
import { DiffRenderer } from "./renderers/DiffRenderer";
import { HarnessAwareApprovalRow } from "./HarnessApprovalPreview";

const TERMINAL_INLINE_OUTPUT_CHARS = 1800;
const TERMINAL_INLINE_OUTPUT_LINES = 18;
const TERMINAL_EXPANDED_OUTPUT_CHARS = 12000;
const PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json";

function toneColor(isError: boolean, t: ThemeTokens): string {
  return isError ? t.dangerMuted : t.textMuted;
}

function sanitizeTerminalLabel(value: string | null | undefined): string {
  const clean = (value ?? "")
    .replace(/^harness-spindrel:/i, "")
    .replace(/^mcp__spindrel__/i, "")
    .replace(/^mcp\s+spindrel\s+/i, "")
    .replace(/\bharness-spindrel:/gi, "")
    .replace(/\bmcp__spindrel__/gi, "")
    .trim();
  if (!clean) return "";
  return clean.includes(" ") ? clean : clean.replace(/_/g, " ");
}

function normalizeTerminalOutput(env: ToolResultEnvelope | undefined): string {
  if (!env) return "";
  const body = envelopeBodyText(env).trim();
  const plain = (env.plain_body ?? "").trim();
  const raw = body || plain;
  if (!raw) return "";
  if (env.content_type.toLowerCase().includes("json")) {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }
  return raw;
}

function terminalOutputPreview(env: ToolResultEnvelope | undefined): { text: string; isLarge: boolean } | null {
  const output = normalizeTerminalOutput(env);
  if (!output) return null;
  const lines = output.split(/\r?\n/);
  const isLarge = output.length > TERMINAL_INLINE_OUTPUT_CHARS || lines.length > TERMINAL_INLINE_OUTPUT_LINES;
  if (!isLarge) return { text: output, isLarge: false };
  return {
    text: lines.slice(0, TERMINAL_INLINE_OUTPUT_LINES).join("\n").slice(0, TERMINAL_INLINE_OUTPUT_CHARS),
    isLarge: true,
  };
}

function rendersInlineRichTerminalResult(env: ToolResultEnvelope | undefined): boolean {
  if (!env) return false;
  return env.view_key === "core.plan" || env.content_type === PLAN_CONTENT_TYPE;
}

function expandedTerminalOutput(env: ToolResultEnvelope | undefined): string {
  const output = normalizeTerminalOutput(env);
  if (output.length <= TERMINAL_EXPANDED_OUTPUT_CHARS) return output;
  return `${output.slice(0, TERMINAL_EXPANDED_OUTPUT_CHARS)}\n... output truncated for display`;
}

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
    if (typeof parsed?.error === "string") errorMsg = parsed.error;
    else if (typeof parsed?.error === "object") errorMsg = JSON.stringify(parsed.error, null, 2);
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
          fontFamily: TERMINAL_FONT_STACK,
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
      rendererVariant="terminal-chat"
      chromeMode="embedded"
      t={t}
    />
  );
}

export function TerminalToolTranscript({
  entries,
  expandedIdx,
  setExpandedIdx,
  t,
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
  sessionId?: string;
  channelId?: string;
  botId?: string;
  onApproval?: (approvalId: string, approved: boolean, options?: { bypassRestOfTurn?: boolean }) => void;
  decidingIds?: Set<string>;
}) {
  return (
    <div
      data-testid="terminal-tool-transcript"
      className="flex min-w-0 max-w-full flex-col"
      style={{ gap: 8, marginTop: 8, fontFamily: TERMINAL_FONT_STACK }}
    >
      {entries.map((entry, idx) => {
        const formattedArgs = entry.args ? formatToolArgs(entry.args) : null;
        const isExpanded = expandedIdx === idx;
        const inlineRichResult = rendersInlineRichTerminalResult(entry.env);
        const output = inlineRichResult ? null : terminalOutputPreview(entry.env);
        const label = sanitizeTerminalLabel(entry.label) || "tool";
        const metaLabel = sanitizeTerminalLabel(entry.metaLabel);
        const target = sanitizeTerminalLabel(entry.target);
        const hasLargeOutput = !!output?.isLarge;
        const hasExpandableDetails = !inlineRichResult && (!!formattedArgs || hasLargeOutput || (!!entry.env && !output));
        const canToggle = hasExpandableDetails && entry.detailKind !== "inline-diff";
        const rowTone = entry.isError
          ? t.danger
          : entry.tone === "warning"
            ? t.warning
            : entry.tone === "success"
              ? t.success
              : entry.tone === "accent"
                ? t.accent
                : entry.isRunning
                  ? t.text
                  : t.textMuted;
        const statusGlyph = entry.isError ? "x" : entry.approval ? "?" : ">";
        const renderCodeOutput = output && !output.isLarge && entry.detailKind !== "inline-diff"
          && looksLikeCodePreview(output.text, target || entry.target);

        return (
          <div key={`${entry.id}:${idx}`} className="min-w-0 max-w-full overflow-hidden" data-testid="tool-transcript-row">
            <div
              className="grid min-w-0 max-w-full items-baseline gap-x-2"
              style={{ gridTemplateColumns: "14px minmax(0, 1fr)", fontSize: 12, lineHeight: 1.45 }}
            >
              <span aria-hidden="true" style={{ color: entry.isError ? t.danger : t.textDim, textAlign: "center", userSelect: "none" }}>
                {statusGlyph}
              </span>
              <span className="inline-flex min-w-0 max-w-full flex-wrap items-baseline gap-x-2 gap-y-0 overflow-hidden" style={{ color: t.textMuted }}>
                <span
                  data-testid="terminal-tool-label"
                  title={label}
                  style={{
                    color: rowTone,
                    fontWeight: 600,
                    minWidth: 0,
                    maxWidth: "min(26ch, 100%)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {label}
                </span>
                {metaLabel && (
                  <span data-testid="terminal-tool-meta" className="min-w-0 break-words" style={{ color: t.textDim, overflowWrap: "anywhere" }}>
                    {metaLabel}
                  </span>
                )}
                {target && (
                  <span data-testid="terminal-tool-target" className="min-w-0 break-words" title={target} style={{ maxWidth: "100%", overflowWrap: "anywhere" }}>
                    {target}
                  </span>
                )}
                {!output && entry.previewText && (
                  <span className="min-w-0 break-words" style={{ color: toneColor(entry.isError, t), maxWidth: "100%", overflowWrap: "anywhere" }}>
                    {entry.previewText}
                  </span>
                )}
                {canToggle && (
                  <button
                    type="button"
                    onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                    className="px-0 py-0 text-[11px] underline-offset-2 hover:underline"
                    style={{ color: t.accent, fontFamily: TERMINAL_FONT_STACK }}
                  >
                    {isExpanded ? "hide details" : hasLargeOutput ? "show output" : "show details"}
                  </button>
                )}
              </span>
            </div>

            {renderCodeOutput && output && (
              <CodePreviewRenderer text={output.text} target={target || entry.target} t={t} isError={entry.isError} />
            )}

            {output && !output.isLarge && entry.detailKind !== "inline-diff" && !renderCodeOutput && (
              <pre
                data-testid="terminal-tool-output"
                className="m-0 whitespace-pre-wrap break-words"
                style={{
                  color: entry.isError ? t.dangerMuted : t.textDim,
                  borderLeft: `1px solid ${entry.isError ? t.dangerBorder : t.surfaceBorder}`,
                  marginLeft: 6,
                  marginTop: 2,
                  paddingLeft: 14,
                  fontFamily: TERMINAL_FONT_STACK,
                  fontSize: 11.5,
                  lineHeight: 1.45,
                  maxWidth: "calc(100% - 22px)",
                  overflowX: "hidden",
                  overflowWrap: "anywhere",
                  wordBreak: "break-word",
                }}
              >
                {output.text}
              </pre>
            )}

            {entry.detailKind === "inline-diff" && entry.detail && (
              <div data-testid="terminal-tool-output">
                <div data-testid="terminal-diff-output">
                  <DiffRenderer
                    body={entry.detail}
                    rendererVariant="terminal-chat"
                    summary={entry.summary}
                    t={t}
                  />
                </div>
              </div>
            )}

            {entry.approval && onApproval && (
              <div style={{ marginLeft: 22 }}>
                <HarnessAwareApprovalRow
                  approval={entry.approval}
                  onApproval={onApproval}
                  decidingIds={decidingIds}
                  t={t}
                  chatMode="terminal"
                />
              </div>
            )}

            {inlineRichResult && entry.env && (
              <div className="min-w-0" style={{ marginLeft: 22, marginTop: 5, maxWidth: "calc(100% - 22px)" }}>
                <RichToolResult
                  envelope={entry.env}
                  sessionId={sessionId}
                  channelId={channelId}
                  botId={botId}
                  rendererVariant="terminal-chat"
                  chromeMode="embedded"
                  t={t}
                />
              </div>
            )}

            {isExpanded && canToggle && (
              <div
                className="min-w-0"
                style={{
                  borderLeft: `1px solid ${t.surfaceBorder}`,
                  marginLeft: 6,
                  marginTop: 3,
                  paddingLeft: 14,
                  maxWidth: "calc(100% - 22px)",
                  overflowX: "hidden",
                }}
              >
                {formattedArgs && (
                  <pre
                    className="m-0 whitespace-pre-wrap break-words"
                    style={{
                      color: t.textDim,
                      fontFamily: TERMINAL_FONT_STACK,
                      fontSize: 11,
                      lineHeight: 1.45,
                      marginBottom: entry.env ? 6 : 0,
                      maxWidth: "100%",
                      overflowX: "hidden",
                      overflowWrap: "anywhere",
                      wordBreak: "break-word",
                    }}
                  >
                    {formattedArgs}
                  </pre>
                )}
                {entry.env && output?.isLarge && (
                  looksLikeCodePreview(expandedTerminalOutput(entry.env), target || entry.target) ? (
                    <CodePreviewRenderer
                      text={expandedTerminalOutput(entry.env)}
                      target={target || entry.target}
                      t={t}
                      isError={entry.isError}
                    />
                  ) : (
                    <pre
                      data-testid="terminal-tool-output"
                      className="m-0 max-h-[520px] overflow-auto whitespace-pre-wrap break-words"
                      style={{
                        color: entry.isError ? t.dangerMuted : t.textDim,
                        fontFamily: TERMINAL_FONT_STACK,
                        fontSize: 11.5,
                        lineHeight: 1.45,
                        maxWidth: "100%",
                        overflowWrap: "anywhere",
                        wordBreak: "break-word",
                      }}
                    >
                      {expandedTerminalOutput(entry.env)}
                    </pre>
                  )
                )}
                {entry.env && !output && (
                  entry.isError ? (
                    <ErrorResult env={entry.env} t={t} sessionId={sessionId} channelId={channelId} botId={botId} />
                  ) : (
                    <RichToolResult
                      envelope={entry.env}
                      sessionId={sessionId}
                      channelId={channelId}
                      botId={botId}
                      rendererVariant="terminal-chat"
                      chromeMode="embedded"
                      t={t}
                    />
                  )
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
