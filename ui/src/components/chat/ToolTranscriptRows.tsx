import { useState } from "react";
import { Wrench, ChevronRight, ChevronDown, AlertCircle, CheckCircle2 } from "lucide-react";
import type { ThemeTokens } from "../../theme/tokens";
import type { ToolResultEnvelope } from "../../types/api";
import { RichToolResult } from "./RichToolResult";
import { ToolTraceStrip, type TraceTick } from "./ToolTraceStrip";
import { formatToolArgs } from "./toolCallUtils";
import {
  envelopeBodyLength,
  envelopeBodyText,
  resultSummary,
  type SharedToolTranscriptEntry,
} from "./toolTranscriptModel";
import { HarnessAwareApprovalRow } from "./HarnessApprovalPreview";
import { TerminalToolTranscript } from "./TerminalToolTranscript";
import { CODE_FONT_STACK, TERMINAL_FONT_STACK } from "./CodePreviewRenderer";
import { DiffRenderer } from "./renderers/DiffRenderer";
import { ChannelFileTargetLink } from "./ChannelFileTargetLink";

const TRACE_STRIP_THRESHOLD = 4;

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
  const [groupExpanded, setGroupExpanded] = useState(false);
  const hasApproval = entries.some((entry) => !!entry.approval);
  const ticks: TraceTick[] = entries.map((entry) => ({
    toolName: entry.label,
    target: entry.target ?? undefined,
    isError: entry.isError,
  }));

  if (!isTerminalMode && !hasApproval && !groupExpanded && entries.length >= TRACE_STRIP_THRESHOLD) {
    return <ToolTraceStrip ticks={ticks} onExpand={() => setGroupExpanded(true)} t={t} chatMode={chatMode} />;
  }

  if (isTerminalMode) {
    return (
      <TerminalToolTranscript
        entries={entries}
        expandedIdx={expandedIdx}
        setExpandedIdx={setExpandedIdx}
        t={t}
        sessionId={sessionId}
        channelId={channelId}
        botId={botId}
        onApproval={onApproval}
        decidingIds={decidingIds}
      />
    );
  }

  return (
    <div className="flex flex-col" style={{ gap: 6, marginTop: 6 }}>
      {entries.map((entry, idx) => {
        const formattedArgs = entry.args ? formatToolArgs(entry.args) : null;
        const expandable = entry.detailKind === "expandable" && (!!formattedArgs || !!entry.env);
        const isExpanded = expandedIdx === idx;

        return (
          <div key={`${entry.id}:${idx}`} className="flex flex-col">
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
              style={{ minWidth: 0, cursor: expandable ? "pointer" : "default" }}
            >
              <Wrench size={11} style={{ color: t.textDim, flexShrink: 0 }} />
              <span
                className="text-[10px] font-medium uppercase tracking-wider"
                style={{ color: entry.isError ? t.dangerMuted : t.textDim, minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere" }}
              >
                {entry.label}
              </span>
              {entry.metaLabel && (
                <span className="text-[10px] font-mono normal-case overflow-hidden text-ellipsis" style={{ color: t.textDim, whiteSpace: "nowrap" }}>
                  {entry.metaLabel}
                </span>
              )}
              {entry.target && (
                <span className="inline-flex min-w-0 max-w-full items-baseline gap-1 text-[10px] font-mono normal-case" style={{ color: t.textMuted, opacity: 0.85, flex: "1 1 12rem" }}>
                  <span style={{ flexShrink: 0 }}>{"->"}</span>
                  <ChannelFileTargetLink
                    channelId={entry.kind === "file" ? channelId : null}
                    sessionId={entry.kind === "file" ? sessionId : null}
                    target={entry.target}
                    className="min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap underline-offset-2 hover:underline"
                    style={{ color: t.linkColor, textDecorationColor: `${t.linkColor}66` }}
                    testId="tool-file-target-link"
                  >
                    <EndTruncatedPath value={entry.target} color="currentColor" />
                  </ChannelFileTargetLink>
                </span>
              )}
              {!isExpanded && entry.detailKind === "expandable" && (entry.previewText || entry.env) && (
                <span className="text-[11px] overflow-hidden text-ellipsis whitespace-nowrap" style={{ color: toneColor(entry.isError, t), maxWidth: 360 }}>
                  {entry.previewText || resultSummary(entry.env)}
                </span>
              )}
              {entry.env && !expandable && entry.detailKind !== "collapsed-read" && (
                entry.isError ? <AlertCircle size={12} style={{ color: t.danger }} /> : <CheckCircle2 size={12} style={{ color: t.success, opacity: 0.7 }} />
              )}
              {expandable && (isExpanded ? <ChevronDown size={11} style={{ color: t.textDim }} /> : <ChevronRight size={11} style={{ color: t.textDim }} />)}
            </div>

            {entry.detailKind === "inline-diff" && entry.detail && (
              <div className="mt-1.5">
                <DiffRenderer body={entry.detail} rendererVariant="default-chat" summary={entry.summary} t={t} />
              </div>
            )}

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
              <div className="rounded-lg border overflow-hidden mt-1" style={{ borderColor: t.surfaceBorder, backgroundColor: t.surfaceRaised }}>
                {formattedArgs && (
                  <div className="max-h-[200px] overflow-y-auto px-3 py-2 border-b" style={{ borderColor: t.surfaceBorder }}>
                    <pre className="m-0 text-[11px] font-mono whitespace-pre-wrap break-words leading-relaxed" style={{ color: t.textMuted }}>
                      {formattedArgs}
                    </pre>
                  </div>
                )}

                {entry.env && (
                  <div className="relative px-3 py-1 pb-2">
                    {entry.isError ? (
                      <ErrorResult env={entry.env} t={t} chatMode={chatMode} sessionId={sessionId} channelId={channelId} botId={botId} />
                    ) : (
                      <RichToolResult
                        envelope={entry.env}
                        sessionId={sessionId}
                        channelId={channelId}
                        botId={botId}
                        rendererVariant="default-chat"
                        chromeMode="embedded"
                        t={t}
                      />
                    )}
                    {!entry.env.truncated && (entry.env.byte_size > 2000 || envelopeBodyLength(entry.env) > 1500) && (
                      <div
                        className="absolute bottom-0 left-0 right-0 h-12 flex items-end justify-center pb-1.5 pointer-events-none"
                        style={{ background: `linear-gradient(transparent, ${t.surfaceRaised})` }}
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
