import { useState } from "react";
import { useDecideApproval, type DecideRequest } from "../../api/hooks/useApprovals";
import { normalizeToolCall, type ToolCall, type ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

type InlineWidgetEntry = { envelope: ToolResultEnvelope; toolName: string; recordId?: string };

type TranscriptEntry = {
  kind: "activity" | "widget" | "approval";
  summary: string;
  id?: string;
  detail?: string | null;
  tone?: "default" | "muted" | "success" | "warning" | "danger" | "accent";
  widget?: InlineWidgetEntry;
  approval?: {
    approvalId: string;
    capabilityId?: string;
    reason?: string;
  };
};

type ParsedFileAction = {
  verb: string;
  path: string;
  detail?: string;
};

function truncate(text: string, max = 140): string {
  const clean = text.trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

function parseJsonObject(text: string | undefined): Record<string, unknown> | null {
  if (!text) return null;
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) return null;
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function firstMeaningfulLine(text: string | null | undefined): string {
  if (!text) return "";
  const line = text
    .split(/\r?\n/)
    .map((part) => part.trim())
    .find(Boolean);
  return line ?? "";
}

function looksLikeJson(text: string | null | undefined): boolean {
  if (!text) return false;
  const trimmed = text.trim();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

function extractDiff(text: string | null | undefined): string | null {
  if (!text) return null;
  const trimmed = text.trim();
  if (!/^(---|\+\+\+|@@|\+|-)/m.test(trimmed)) return null;
  return trimmed.split(/\r?\n/).slice(0, 16).join("\n");
}

function truncateBlock(text: string | null | undefined, maxChars = 900, maxLines = 18): string | null {
  if (!text) return null;
  const lines = text.trim().split(/\r?\n/);
  const sliced = lines.slice(0, maxLines).join("\n").trim();
  if (!sliced) return null;
  return sliced.length > maxChars ? `${sliced.slice(0, maxChars - 1)}…` : sliced;
}

function parseFileAction(summary: string): ParsedFileAction | null {
  const match = summary.match(/^(Read|Edited|Wrote|Created|Deleted)\s+(.+?)(?::\s*(.*))?$/i);
  if (!match) return null;
  return {
    verb: match[1],
    path: match[2],
    detail: match[3]?.trim() || undefined,
  };
}

function toneColor(tone: TranscriptEntry["tone"], t: ThemeTokens): string {
  if (tone === "success") return t.success;
  if (tone === "warning") return t.warning;
  if (tone === "danger") return t.danger;
  if (tone === "accent") return t.accent;
  if (tone === "muted") return t.textMuted;
  return t.text;
}

function summarizeEnvelope(envelope: ToolResultEnvelope | undefined | null): string | null {
  if (!envelope) return null;
  const label = envelope.display_label?.trim();
  if (label) return truncate(label, 100);
  const firstLine = firstMeaningfulLine(envelope.plain_body || envelope.body || "");
  if (!firstLine || looksLikeJson(firstLine)) return null;
  return truncate(firstLine, 160);
}

function formatValue(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => (typeof item === "string" || typeof item === "number" || typeof item === "boolean") ? String(item) : null)
      .filter(Boolean);
    return parts.length ? parts.join(", ") : null;
  }
  return null;
}

function formatSimpleParams(args: string | undefined): string | null {
  const parsed = parseJsonObject(args);
  if (!parsed) return null;
  const skipped = new Set(["content", "body", "html", "css", "js", "javascript", "markdown", "diff", "patch", "output"]);
  const lines: string[] = [];
  for (const [key, value] of Object.entries(parsed)) {
    if (skipped.has(key)) continue;
    const formatted = formatValue(value);
    if (!formatted) continue;
    if (formatted.length > 180) continue;
    lines.push(`${key}: ${formatted}`);
    if (lines.length >= 6) break;
  }
  return lines.length ? lines.join("\n") : null;
}

function basicBulletColor(entry: TranscriptEntry, t: ThemeTokens): string {
  if (entry.kind === "widget") return t.accent;
  if (entry.kind === "approval") return t.warning;
  if (entry.tone === "success") return t.success;
  if (entry.tone === "warning") return t.warning;
  if (entry.tone === "danger") return t.danger;
  return t.textDim;
}

function extractNonJsonOutput(envelope: ToolResultEnvelope | undefined): string | null {
  if (!envelope) return null;
  const body = envelope.body || envelope.plain_body || "";
  if (!body.trim() || looksLikeJson(body)) return null;
  const diff = extractDiff(body);
  if (diff) return diff;
  return truncateBlock(body);
}

function summarizeGenericTool(toolName: string, args?: string): string {
  const parsed = parseJsonObject(args);
  if (toolName === "get_skill" || toolName === "load_skill") {
    const skill = (parsed?.name || parsed?.id || parsed?.skill_name || parsed?.skill_id) as string | undefined;
    return skill ? `Loaded skill ${skill}` : "Loaded skill";
  }
  if (toolName === "inspect_widget_pin") {
    const widget = (
      parsed?.display_label ||
      parsed?.name ||
      parsed?.id ||
      parsed?.widget_id ||
      parsed?.record_id
    ) as string | undefined;
    return widget ? `Inspected widget pin ${widget}` : "Inspected widget pin";
  }
  if (toolName === "file") {
    const path = (parsed?.path || parsed?.file_path || parsed?.target_path) as string | undefined;
    return path ? `Updated ${path}` : "Updated file";
  }
  const path = (parsed?.path || parsed?.file_path || parsed?.target_path || parsed?.source_path) as string | undefined;
  if (path) return `${toolName.replace(/_/g, " ")} ${path}`;
  return toolName.replace(/_/g, " ");
}

function shouldPreferGenericSummary(envelopeSummary: string | null, genericSummary: string): boolean {
  if (!envelopeSummary) return true;
  if (envelopeSummary === genericSummary) return false;
  if (/^loaded skill$/i.test(envelopeSummary) && /^Loaded skill\s+\S+/.test(genericSummary)) return true;
  if (/^inspected widget pin$/i.test(envelopeSummary) && /^Inspected widget pin\s+\S+/.test(genericSummary)) return true;
  return false;
}

function buildPersistedEntry(toolName: string, args: string | undefined, result: ToolResultEnvelope | undefined): TranscriptEntry {
  const envelopeSummary = summarizeEnvelope(result);
  const fileAction = envelopeSummary ? parseFileAction(envelopeSummary) : null;
  if (fileAction) {
    return {
      kind: "activity",
      id: `${toolName}:${fileAction.verb}:${fileAction.path}`,
      summary: `${fileAction.verb} ${fileAction.path}`,
      detail: fileAction.detail ?? extractDiff(result?.body || result?.plain_body),
      tone: fileAction.verb.toLowerCase() === "deleted" ? "danger" : "muted",
    };
  }

  const paramsDetail = formatSimpleParams(args);
  const outputDetail = extractNonJsonOutput(result);
  const detail = paramsDetail && outputDetail
    ? `${paramsDetail}\n\n${outputDetail}`
    : paramsDetail || outputDetail;
  const genericSummary = summarizeGenericTool(toolName, args);
  const summary = shouldPreferGenericSummary(envelopeSummary, genericSummary)
    ? genericSummary
    : envelopeSummary!;

  return {
    kind: "activity",
    id: `${toolName}:${envelopeSummary || "activity"}`,
    summary,
    detail,
    tone: result?.content_type.includes("error") ? "danger" : "default",
  };
}

function collapseConsecutiveFileEntries(entries: TranscriptEntry[]): TranscriptEntry[] {
  const collapsed: TranscriptEntry[] = [];

  for (const entry of entries) {
    const currentFile = parseFileAction(entry.summary);
    const previous = collapsed[collapsed.length - 1];
    const previousFile = previous ? parseFileAction(previous.summary) : null;

    if (
      currentFile &&
      previous &&
      previous.kind === "activity" &&
      previousFile &&
      currentFile.verb === previousFile.verb &&
      currentFile.path === previousFile.path
    ) {
      const countMatch = previous.detail?.match(/^(\d+) changes$/);
      const nextCount = countMatch ? Number(countMatch[1]) + 1 : 2;
      previous.detail = `${nextCount} changes`;
      previous.tone = entry.tone ?? previous.tone;
      continue;
    }

    collapsed.push({ ...entry });
  }

  return collapsed;
}

function TranscriptBlock({ entries, t, onAddWidget, decidingIds, onApproval }: {
  entries: TranscriptEntry[];
  t: ThemeTokens;
  onAddWidget?: (widget: InlineWidgetEntry) => void;
  decidingIds?: Set<string>;
  onApproval?: (approvalId: string, approved: boolean, pinCapabilityId?: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 8 }}>
      {entries.map((entry, index) => {
        const rowId = entry.id ?? `${entry.kind}-${index}`;
        const expandable = !!entry.detail && !looksLikeJson(entry.detail);
        const isExpanded = expanded.has(rowId);
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
              fontSize: 12.5,
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
                fontSize: expandable ? 12.5 : 11,
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
                {entry.summary}
              </span>
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
                  fontSize: 11.5,
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

          {isExpanded && entry.detail && !looksLikeJson(entry.detail) && (
            <div
              style={{
                marginLeft: 18,
                color: t.textMuted,
                fontFamily: TERMINAL_FONT_STACK,
                fontSize: 11.5,
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
                  fontSize: 11.5,
                  padding: "2px 6px",
                  borderRadius: 2,
                  cursor: "pointer",
                }}
              >
                Approve
              </button>
              {entry.approval.capabilityId && (
                <button
                  type="button"
                  disabled={decidingIds?.has(entry.approval.approvalId)}
                  onClick={() => onApproval(entry.approval!.approvalId, true, entry.approval!.capabilityId)}
                  style={{
                    border: `1px solid ${t.accentBorder}`,
                    background: "transparent",
                    color: t.accent,
                    fontFamily: TERMINAL_FONT_STACK,
                    fontSize: 11.5,
                    padding: "2px 6px",
                    borderRadius: 2,
                    cursor: "pointer",
                  }}
                >
                  Approve + pin
                </button>
              )}
              <button
                type="button"
                disabled={decidingIds?.has(entry.approval.approvalId)}
                onClick={() => onApproval(entry.approval!.approvalId, false)}
                style={{
                  border: `1px solid ${t.dangerBorder}`,
                  background: "transparent",
                  color: t.danger,
                  fontFamily: TERMINAL_FONT_STACK,
                  fontSize: 11.5,
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
  const entries: TranscriptEntry[] = [];

  if (richEnvelope) {
    const summary = summarizeEnvelope(richEnvelope);
    entries.push({
      kind: "activity",
      id: `rich:${richSource || "event"}`,
      summary: summary ? `${(richSource || "event").toLowerCase()} · ${summary}` : (richSource || "event").toLowerCase(),
      detail: extractNonJsonOutput(richEnvelope),
      tone: "muted",
    });
  }

  const count = Math.max(remainingToolCalls.length, remainingToolNames.length, remainingToolResults.length);
  for (let i = 0; i < count; i++) {
    const call = remainingToolCalls[i];
    const normalized = call ? normalizeToolCall(call) : null;
    entries.push(buildPersistedEntry(
      normalized?.name ?? remainingToolNames[i] ?? "tool",
      normalized?.arguments,
      remainingToolResults[i],
    ));
  }

  for (const widget of inlineWidgets) {
    const widgetLabel = widget.envelope.display_label || widget.toolName || "widget";
    entries.push({
      kind: "widget",
      id: `widget:${widget.toolName}:${widget.recordId ?? widget.envelope.record_id ?? widgetLabel}`,
      summary: `Widget available: ${truncate(widgetLabel, 100)}`,
      tone: "accent",
      widget,
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
    status: "running" | "done" | "awaiting_approval" | "denied";
    approvalId?: string;
    approvalReason?: string;
    capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
  }[];
  t: ThemeTokens;
}) {
  const decideApproval = useDecideApproval();
  const [decidingIds, setDecidingIds] = useState<Set<string>>(new Set());

  const handleDecide = (approvalId: string, approved: boolean, pinCapabilityId?: string) => {
    setDecidingIds((prev) => new Set(prev).add(approvalId));
    const data: DecideRequest = { approved, decided_by: "web:admin" };
    if (pinCapabilityId) data.pin_capability = pinCapabilityId;
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

  const entries = toolCalls.map<TranscriptEntry>((tc, index) => {
    const toolName = tc.capability?.name || tc.name;
    const baseSummary = summarizeGenericTool(toolName, tc.args);
    const tone = tc.status === "done"
      ? "success"
      : tc.status === "awaiting_approval"
        ? "warning"
        : tc.status === "denied"
          ? "danger"
          : "muted";

    return {
      kind: tc.status === "awaiting_approval" && tc.approvalId ? "approval" : "activity",
      id: `stream:${toolName}:${tc.status}:${index}`,
      summary: tc.status === "awaiting_approval"
        ? `Approval required: ${toolName}`
        : tc.status === "running"
          ? `Running ${baseSummary}`
          : tc.status === "done"
            ? `Completed ${baseSummary}`
            : `Denied ${baseSummary}`,
      detail: formatSimpleParams(tc.args) || tc.approvalReason || tc.capability?.description || null,
      tone,
      approval: tc.approvalId ? {
        approvalId: tc.approvalId,
        capabilityId: tc.capability?.id,
        reason: tc.approvalReason,
      } : undefined,
    };
  });

  return (
    <TranscriptBlock
      entries={entries}
      t={t}
      decidingIds={decidingIds}
      onApproval={handleDecide}
    />
  );
}
