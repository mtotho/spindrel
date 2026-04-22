/**
 * Tool badges — persisted tool activity for default chat mode.
 *
 * New persisted rows prefer the normalized `tool_call.summary` contract.
 * Legacy rows still fall back to raw tool names + envelopes so historical
 * messages keep rendering.
 */

import { useEffect, useMemo, useState } from "react";
import { Wrench, ChevronRight, ChevronDown, AlertCircle, CheckCircle2 } from "lucide-react";
import { formatToolArgs } from "./toolCallUtils";
import { normalizeToolCall } from "../../types/api";
import type { ToolCall, ToolCallSummary, ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { RichToolResult } from "./RichToolResult";
import { ToolTraceStrip, type TraceTick } from "./ToolTraceStrip";

const TRACE_STRIP_THRESHOLD = 4;
const CODE_FONT_STACK = "'Menlo', 'Monaco', 'Consolas', monospace";

type DiffRow = {
  text: string;
  tone: "muted" | "success" | "danger" | "accent";
  lineNumber?: string | null;
  sign?: string | null;
};

type ToolBadgeEntry = {
  id: string;
  label: string;
  target?: string | null;
  metaLabel?: string | null;
  args?: string;
  env?: ToolResultEnvelope;
  isError: boolean;
  detailKind: "inline-diff" | "collapsed-read" | "expandable" | "none";
  diffText?: string | null;
};

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

function introspectionTarget(name: string, argsList: (string | undefined)[]): string | null {
  const short = name.includes("-") ? name.slice(name.lastIndexOf("-") + 1) : name;
  if (short !== "get_tool_info" && short !== "get_skill" && short !== "load_skill") return null;
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

function summarizeDiffMeta(summary: ToolCallSummary | null | undefined): string | null {
  if (!summary) return null;
  if (summary.kind === "diff" && summary.diff_stats) {
    return `(+${summary.diff_stats.additions} -${summary.diff_stats.deletions})`;
  }
  if (summary.subject_type === "skill") {
    const skillRef = summary.target_label || (summary.target_id ? `${summary.target_id.includes("/") ? `${summary.target_id}.md` : `${summary.target_id}/INDEX.md`}` : null);
    if (skillRef) return `(${skillRef})`;
  }
  if (summary.target_label) {
    return `(${summary.target_label})`;
  }
  return null;
}

function extractDiffText(env: ToolResultEnvelope | undefined): string | null {
  if (!env) return null;
  if (typeof env.body === "string" && env.body.trim()) return env.body;
  if (env.plain_body?.trim()) return env.plain_body;
  return null;
}

function diffRows(detail: string): DiffRow[] {
  const rows: DiffRow[] = [];
  let oldLine: number | null = null;
  let newLine: number | null = null;

  for (const line of detail.split(/\r?\n/)) {
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      rows.push({ text: line, tone: "accent", lineNumber: null, sign: null });
      continue;
    }
    if (line.startsWith("---") || line.startsWith("+++")) {
      rows.push({ text: line, tone: "muted", lineNumber: null, sign: null });
      continue;
    }
    if (line.startsWith("+")) {
      rows.push({ text: line.slice(1), tone: "success", lineNumber: newLine != null ? String(newLine) : null, sign: "+" });
      if (newLine != null) newLine += 1;
      continue;
    }
    if (line.startsWith("-")) {
      rows.push({ text: line.slice(1), tone: "danger", lineNumber: oldLine != null ? String(oldLine) : null, sign: "-" });
      if (oldLine != null) oldLine += 1;
      continue;
    }
    rows.push({
      text: line.startsWith(" ") ? line.slice(1) : line,
      tone: "muted",
      lineNumber: newLine != null ? String(newLine) : null,
      sign: " ",
    });
    if (oldLine != null) oldLine += 1;
    if (newLine != null) newLine += 1;
  }

  return rows;
}

function legacyEntries(toolNames: string[], toolResults?: (ToolResultEnvelope | undefined)[]): ToolBadgeEntry[] {
  const out: ToolBadgeEntry[] = [];
  const counts = new Map<string, number>();
  for (let i = 0; i < toolNames.length; i++) {
    const name = toolNames[i];
    const occurrence = (counts.get(name) ?? 0) + 1;
    counts.set(name, occurrence);
    const env = toolResults?.[i];
    out.push({
      id: `${name}:${occurrence}`,
      label: name,
      target: introspectionTarget(name, []),
      env,
      isError: isErrorEnvelope(env),
      detailKind: env ? "expandable" : "none",
    });
  }
  return out;
}

function buildEntries(
  toolNames: string[],
  toolCalls?: ToolCall[],
  toolResults?: (ToolResultEnvelope | undefined)[],
): ToolBadgeEntry[] {
  if (!toolCalls || toolCalls.length === 0) {
    return legacyEntries(toolNames, toolResults);
  }

  return toolCalls.map((tc, index) => {
    const norm = normalizeToolCall(tc);
    const summary = tc.summary;
    const env = toolResults?.[index];
    const target = summary?.target_label || introspectionTarget(norm.name, [norm.arguments]);
    const isFileDiff = summary?.kind === "diff" && summary.subject_type === "file";
    const isFileRead = summary?.kind === "read" && summary.subject_type === "file";

    return {
      id: tc.id || `${norm.name}:${index}`,
      label: summary?.label || norm.name,
      target: summary?.target_label ? null : target,
      metaLabel: summarizeDiffMeta(summary),
      args: summary ? undefined : norm.arguments,
      env,
      isError: summary?.kind === "error" || isErrorEnvelope(env),
      detailKind: isFileDiff ? "inline-diff" : isFileRead ? "collapsed-read" : env || norm.arguments ? "expandable" : "none",
      diffText: isFileDiff ? extractDiffText(env) : null,
    };
  });
}

function toneColor(isError: boolean, t: ThemeTokens): string {
  return isError ? t.dangerMuted : t.textMuted;
}

function renderDiffBlock(detail: string, t: ThemeTokens, rowId: string) {
  return (
    <div
      style={{
        marginLeft: 10,
        marginTop: 6,
        fontFamily: CODE_FONT_STACK,
        fontSize: 11.5,
        lineHeight: 1.45,
      }}
    >
      {diffRows(detail).map((line, lineIndex) => (
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
              fontFamily: CODE_FONT_STACK,
            }}
          >
            {line.text || " "}
          </span>
        </div>
      ))}
    </div>
  );
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
  toolResults?: (ToolResultEnvelope | undefined)[];
  sessionId?: string;
  channelId?: string;
  botId?: string;
  compact?: boolean;
  autoExpand?: boolean;
  t: ThemeTokens;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [striped, setStriped] = useState<boolean | null>(null);

  const entries = useMemo(
    () => buildEntries(toolNames, toolCalls, toolResults),
    [toolNames, toolCalls, toolResults],
  );

  useEffect(() => {
    if (compact || !autoExpand || expandedIdx !== null) return;
    const idx = entries.findIndex((entry) => entry.detailKind === "expandable" && !!entry.env);
    if (idx >= 0) setExpandedIdx(idx);
  }, [entries, compact, autoExpand, expandedIdx]);

  const ticks: TraceTick[] = useMemo(
    () => entries.map((entry) => ({
      toolName: entry.label,
      target: entry.target ?? undefined,
      isError: entry.isError,
    })),
    [entries],
  );

  if (entries.length === 0) return null;

  const stripMode = striped ?? (entries.length >= TRACE_STRIP_THRESHOLD);
  if (stripMode) {
    return <ToolTraceStrip ticks={ticks} onExpand={() => setStriped(false)} t={t} />;
  }

  return (
    <div className="flex flex-col gap-1.5 mt-1.5">
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
              className={`inline-flex items-center self-start gap-1.5 px-2.5 py-1 transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-offset-1 ${expandable ? "cursor-pointer" : "cursor-default"} ${isExpanded ? "rounded-t-lg border border-b-0" : "rounded-lg border"}`}
              style={{
                backgroundColor: t.surfaceRaised,
                borderColor: t.surfaceBorder,
              }}
            >
              <Wrench size={11} style={{ color: t.textDim, flexShrink: 0 }} />
              <span
                className="text-[10px] font-medium uppercase tracking-wider"
                style={{ color: entry.isError ? t.dangerMuted : t.textDim }}
              >
                {entry.label}
              </span>
              {entry.metaLabel && (
                <span
                  className="text-[10px] font-mono normal-case"
                  style={{ color: t.textDim }}
                >
                  {entry.metaLabel}
                </span>
              )}
              {entry.target && (
                <span
                  className="text-[10px] font-mono normal-case"
                  style={{ color: t.textMuted, opacity: 0.85 }}
                >
                  {"→"} {entry.target}
                </span>
              )}
              {!isExpanded && entry.env && entry.detailKind === "expandable" && (
                <span
                  className="text-[11px] overflow-hidden text-ellipsis whitespace-nowrap max-w-[360px]"
                  style={{ color: toneColor(entry.isError, t) }}
                >
                  {resultSummary(entry.env)}
                </span>
              )}
              {entry.env && !expandable && entry.detailKind !== "collapsed-read" && (
                entry.isError ? (
                  <AlertCircle size={12} style={{ color: t.danger }} />
                ) : (
                  <CheckCircle2 size={12} style={{ color: t.success, opacity: 0.7 }} />
                )
              )}
              {expandable &&
                (isExpanded ? (
                  <ChevronDown size={11} style={{ color: t.textDim }} />
                ) : (
                  <ChevronRight size={11} style={{ color: t.textDim }} />
                ))}
            </div>

            {entry.detailKind === "inline-diff" && entry.diffText && renderDiffBlock(entry.diffText, t, entry.id)}

            {isExpanded && expandable && (
              <div
                className="rounded-b-lg border border-t-0 overflow-hidden"
                style={{
                  borderColor: t.surfaceBorder,
                  backgroundColor: t.surfaceRaised,
                }}
              >
                {formattedArgs && (
                  <div
                    className="max-h-[200px] overflow-y-auto px-3 py-2 border-b"
                    style={{ borderColor: t.surfaceBorder }}
                  >
                    <pre className="m-0 text-[11px] font-mono whitespace-pre-wrap break-words leading-relaxed" style={{ color: t.textMuted }}>
                      {formattedArgs}
                    </pre>
                  </div>
                )}

                {entry.env && (
                  <div className="relative px-3 py-1 pb-2">
                    {entry.isError ? (
                      <ErrorResult env={entry.env} t={t} sessionId={sessionId} channelId={channelId} botId={botId} />
                    ) : (
                      <RichToolResult envelope={entry.env} sessionId={sessionId} channelId={channelId} botId={botId} t={t} />
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
          fontFamily: CODE_FONT_STACK,
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
