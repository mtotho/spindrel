import { useState } from "react";
import { useDecideApproval, type DecideRequest } from "../../api/hooks/useApprovals";
import type { ToolCall, ToolCallSummary, ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import {
  buildLiveToolEntries,
  buildPersistedToolEntries,
  detailRows,
  looksLikeJson,
  type SharedToolTranscriptEntry,
} from "./toolTranscriptModel";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

type InlineWidgetEntry = { envelope: ToolResultEnvelope; toolName: string; recordId?: string };

function truncate(text: string, max = 140): string {
  const clean = text.trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

function toneColor(tone: SharedToolTranscriptEntry["tone"], t: ThemeTokens): string {
  if (tone === "success") return t.success;
  if (tone === "warning") return t.warning;
  if (tone === "danger") return t.danger;
  if (tone === "accent") return t.accent;
  if (tone === "muted") return t.textMuted;
  return t.text;
}

function basicBulletColor(entry: SharedToolTranscriptEntry, t: ThemeTokens): string {
  if (entry.kind === "widget") return t.accent;
  if (entry.kind === "approval") return t.warning;
  if (entry.tone === "success") return t.success;
  if (entry.tone === "warning") return t.warning;
  if (entry.tone === "danger") return t.danger;
  return t.textDim;
}

function collapseConsecutiveFileEntries(entries: SharedToolTranscriptEntry[]): SharedToolTranscriptEntry[] {
  return entries.map((entry) => ({ ...entry }));
}

function TranscriptBlock({ entries, t, onAddWidget, decidingIds, onApproval }: {
  entries: SharedToolTranscriptEntry[];
  t: ThemeTokens;
  onAddWidget?: (widget: InlineWidgetEntry) => void;
  decidingIds?: Set<string>;
  onApproval?: (approvalId: string, approved: boolean) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 8 }}>
      {entries.map((entry, index) => {
        const rowId = entry.id ?? `${entry.kind}-${index}`;
        const expandable = entry.kind !== "file" && !!entry.detail && !looksLikeJson(entry.detail);
        const isExpanded = expanded.has(rowId);
        const structuredDetail = entry.kind === "file" && entry.detail ? detailRows(entry.detail) : null;
        return (
        <div key={rowId} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div
            onClick={expandable ? () => {
              setExpanded((prev) => {
                const next = new Set(prev);
                if (next.has(rowId)) next.delete(rowId);
                else next.add(rowId);
                return next;
              });
            } : undefined}
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "baseline",
              gap: 6,
              fontFamily: TERMINAL_FONT_STACK,
              fontSize: 11.5,
              lineHeight: 1.5,
              cursor: expandable ? "pointer" : undefined,
            }}
          >
            <span
              style={{
                color: expandable ? toneColor(entry.tone, t) : basicBulletColor(entry, t),
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
            <div style={{ minWidth: 0, flex: 1 }}>
              <span
                style={{
                  color: toneColor(entry.tone, t),
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  overflowWrap: "anywhere",
                }}
              >
                {entry.label}
              </span>
              {entry.metaLabel && (
                <span
                  style={{
                    color: t.textDim,
                    marginLeft: 8,
                    fontSize: 10.5,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {entry.metaLabel}
                </span>
              )}
            </div>
            {entry.widget && onAddWidget && (
              <button
                type="button"
                onClick={() => onAddWidget(entry.widget!)}
                style={{
                  border: `1px solid ${t.accentBorder}`,
                  background: "transparent",
                  color: t.accent,
                  fontFamily: TERMINAL_FONT_STACK,
                  fontSize: 10.5,
                  lineHeight: 1.2,
                  padding: "2px 6px",
                  borderRadius: 2,
                  cursor: "pointer",
                  flexShrink: 0,
                }}
              >
                Add to dashboard
              </button>
            )}
          </div>

          {entry.kind === "file" && structuredDetail && (
            <div
              style={{
                marginLeft: 10,
                fontFamily: TERMINAL_FONT_STACK,
                fontSize: 10.5,
                lineHeight: 1.45,
              }}
            >
              {structuredDetail.map((line, lineIndex) => (
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
                      color: toneColor(line.tone, t),
                      padding: "0 4px 0 0",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      overflowWrap: "anywhere",
                    }}
                  >
                    {line.text || " "}
                  </span>
                </div>
              ))}
            </div>
          )}

          {isExpanded && entry.kind !== "file" && entry.detail && !looksLikeJson(entry.detail) && (
            <div
              style={{
                marginLeft: 18,
                color: t.textMuted,
                fontFamily: TERMINAL_FONT_STACK,
                fontSize: 10.5,
                lineHeight: 1.5,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                overflowWrap: "anywhere",
              }}
            >
              {entry.detail}
            </div>
          )}

          {entry.approval && onApproval && (
            <div style={{ display: "flex", flexDirection: "row", gap: 6, flexWrap: "wrap", marginLeft: 18 }}>
              <button
                type="button"
                disabled={decidingIds?.has(entry.approval.approvalId)}
                onClick={() => onApproval(entry.approval!.approvalId, true)}
                style={{
                  border: `1px solid ${t.successBorder}`,
                  background: "transparent",
                  color: t.success,
                  fontFamily: TERMINAL_FONT_STACK,
                  fontSize: 10.5,
                  padding: "2px 6px",
                  borderRadius: 2,
                  cursor: "pointer",
                }}
              >
                Approve
              </button>
              <button
                type="button"
                disabled={decidingIds?.has(entry.approval.approvalId)}
                onClick={() => onApproval(entry.approval!.approvalId, false)}
                style={{
                  border: `1px solid ${t.dangerBorder}`,
                  background: "transparent",
                  color: t.danger,
                  fontFamily: TERMINAL_FONT_STACK,
                  fontSize: 10.5,
                  padding: "2px 6px",
                  borderRadius: 2,
                  cursor: "pointer",
                }}
              >
                Deny
              </button>
            </div>
          )}
        </div>
      )})}
    </div>
  );
}

export function TerminalPersistedToolTranscript({
  richEnvelope,
  richSource,
  inlineWidgets,
  remainingToolNames,
  remainingToolCalls,
  remainingToolResults,
  channelId,
  botId,
  onPin,
  t,
}: {
  richEnvelope?: ToolResultEnvelope;
  richSource?: string;
  inlineWidgets: InlineWidgetEntry[];
  remainingToolNames: string[];
  remainingToolCalls: ToolCall[];
  remainingToolResults: (ToolResultEnvelope | undefined)[];
  channelId?: string;
  botId?: string;
  onPin?: (info: { widgetId: string; envelope: ToolResultEnvelope; toolName: string; channelId: string; botId: string | null }) => void | Promise<void>;
  t: ThemeTokens;
}) {
  const entries: SharedToolTranscriptEntry[] = [];

  if (richEnvelope) {
    entries.push({
      kind: "activity",
      id: `rich:${richSource || "event"}`,
      label: richEnvelope.display_label
        ? `${(richSource || "event").toLowerCase()} · ${truncate(richEnvelope.display_label, 100)}`
        : (richSource || "event").toLowerCase(),
      detail: typeof richEnvelope.body === "string" ? richEnvelope.body : (richEnvelope.plain_body || null),
      tone: "muted",
      isError: false,
      detailKind: "expandable",
    });
  }

  entries.push(...buildPersistedToolEntries(remainingToolNames, remainingToolCalls, remainingToolResults));

  for (const widget of inlineWidgets) {
    const widgetLabel = widget.envelope.display_label || widget.toolName || "widget";
    entries.push({
      kind: "widget",
      id: `widget:${widget.toolName}:${widget.recordId ?? widget.envelope.record_id ?? widgetLabel}`,
      label: `Widget available: ${truncate(widgetLabel, 100)}`,
      tone: "accent",
      widget,
      isError: false,
      detailKind: "none",
    });
  }

  const collapsed = collapseConsecutiveFileEntries(entries);
  if (collapsed.length === 0) return null;

  return (
    <TranscriptBlock
      entries={collapsed}
      t={t}
      onAddWidget={(widget) => {
        if (!channelId || !onPin) return;
        onPin({
          widgetId: widget.recordId ?? widget.envelope.record_id ?? widget.toolName,
          envelope: widget.envelope,
          toolName: widget.toolName,
          channelId,
          botId: botId ?? null,
        });
      }}
    />
  );
}

export function TerminalStreamingToolTranscript({
  toolCalls,
  t,
}: {
  toolCalls: {
    name: string;
    args?: string;
    summary?: ToolCallSummary | null;
    envelope?: ToolResultEnvelope;
    status: "running" | "done" | "awaiting_approval" | "denied";
    approvalId?: string;
    approvalReason?: string;
    capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
  }[];
  t: ThemeTokens;
}) {
  const decideApproval = useDecideApproval();
  const [decidingIds, setDecidingIds] = useState<Set<string>>(new Set());

  const handleDecide = (approvalId: string, approved: boolean) => {
    setDecidingIds((prev) => new Set(prev).add(approvalId));
    const data: DecideRequest = { approved, decided_by: "web:admin" };
    decideApproval.mutate(
      { approvalId, data },
      {
        onSettled: () => {
          setDecidingIds((prev) => {
            const next = new Set(prev);
            next.delete(approvalId);
            return next;
          });
        },
      },
    );
  };

  const entries = buildLiveToolEntries(toolCalls);

  return (
    <TranscriptBlock
      entries={entries}
      t={t}
      decidingIds={decidingIds}
      onApproval={handleDecide}
    />
  );
}
