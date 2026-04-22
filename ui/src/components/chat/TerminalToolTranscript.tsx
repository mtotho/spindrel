import { useState } from "react";
import { useDecideApproval, type DecideRequest } from "../../api/hooks/useApprovals";
import type { ToolCall, ToolCallSummary, ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

type InlineWidgetEntry = { envelope: ToolResultEnvelope; toolName: string; recordId?: string };

type TranscriptEntry = {
  kind: "activity" | "file" | "widget" | "approval";
  summary: string;
  id?: string;
  detail?: string | null;
  tone?: "default" | "muted" | "success" | "warning" | "danger" | "accent";
  metaLabel?: string | null;
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

type DiffStats = {
  additions: number;
  deletions: number;
};

type DetailRow = {
  text: string;
  tone?: "default" | "muted" | "success" | "warning" | "danger" | "accent";
  lineNumber?: string | null;
  sign?: string | null;
};

function truncate(text: string, max = 140): string {
  const clean = text.trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

function shortToolName(name: string): string {
  return name.includes("-") ? name.slice(name.lastIndexOf("-") + 1) : name;
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

function summarizeDiffStats(diff: string | null | undefined): DiffStats | null {
  if (!diff) return null;
  const lines = diff.split(/\r?\n/);
  let additions = 0;
  let deletions = 0;
  for (const line of lines) {
    if (!line) continue;
    if (line.startsWith("+++ ") || line.startsWith("--- ") || line.startsWith("@@")) continue;
    if (line.startsWith("+")) additions += 1;
    if (line.startsWith("-")) deletions += 1;
  }
  if (additions === 0 && deletions === 0) return null;
  return { additions, deletions };
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

function parseEnvelopeJson(envelope: ToolResultEnvelope | undefined): Record<string, unknown> | null {
  if (!envelope) return null;
  if (typeof envelope.body === "string") return parseJsonObject(envelope.body);
  return null;
}

function extractArgValue(args: string | undefined, ...keys: string[]): string | null {
  const parsed = parseJsonObject(args);
  for (const key of keys) {
    const fromJson = formatValue(parsed?.[key]);
    if (fromJson) return fromJson;
  }
  if (!args) return null;
  for (const key of keys) {
    const pattern = new RegExp(`"${key}"\\s*:\\s*"([^"]+)"`);
    const match = args.match(pattern);
    if (match?.[1]) return match[1];
  }
  return null;
}

function formatSkillRef(skillId: string): string {
  const clean = skillId.trim();
  if (!clean) return "skill";
  if (clean.includes("/")) return `${clean}.md`;
  return `${clean}/INDEX.md`;
}

function toneColor(tone: TranscriptEntry["tone"], t: ThemeTokens): string {
  if (tone === "success") return t.success;
  if (tone === "warning") return t.warning;
  if (tone === "danger") return t.danger;
  if (tone === "accent") return t.accent;
  if (tone === "muted") return t.textMuted;
  return t.text;
}

function normalizePersistedToolCall(tc: ToolCall | undefined): { name: string; arguments?: string; summary?: ToolCallSummary | null } | null {
  if (!tc) return null;
  if (tc.function) {
    return {
      name: tc.function.name,
      arguments: typeof tc.function.arguments === "string" ? tc.function.arguments : JSON.stringify(tc.function.arguments ?? {}),
      summary: tc.summary,
    };
  }
  return {
    name: tc.name ?? tc.tool_name ?? "unknown",
    arguments: tc.arguments ?? tc.args,
    summary: tc.summary,
  };
}

function summarizeEnvelope(envelope: ToolResultEnvelope | undefined | null): string | null {
  if (!envelope) return null;
  const label = envelope.display_label?.trim();
  if (label) return truncate(label, 100);
  const bodyText = typeof envelope.body === "string" ? envelope.body : "";
  const firstLine = firstMeaningfulLine(envelope.plain_body || bodyText || "");
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
  const body = typeof envelope.body === "string" ? envelope.body : (envelope.plain_body || "");
  if (!body.trim() || looksLikeJson(body)) return null;
  const diff = extractDiff(body);
  if (diff) return diff;
  return truncateBlock(body);
}

function summarizeGenericTool(toolName: string, args?: string): string {
  const shortName = shortToolName(toolName);
  if (shortName === "get_skill" || shortName === "load_skill") {
    return "Loaded skill";
  }
  const parsed = parseJsonObject(args);
  if (shortName === "inspect_widget_pin") {
    const widget = (
      parsed?.display_label ||
      parsed?.name ||
      parsed?.id ||
      parsed?.widget_id ||
      parsed?.record_id
    ) as string | undefined;
    return widget ? `Inspected widget pin ${widget}` : "Inspected widget pin";
  }
  if (shortName === "file") {
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
  if (/^loaded skill$/i.test(envelopeSummary) && genericSummary === "Loaded skill") return true;
  if (/^inspected widget pin$/i.test(envelopeSummary) && /^Inspected widget pin\s+\S+/.test(genericSummary)) return true;
  return false;
}

function resolveSkillRef(
  toolName: string,
  args: string | undefined,
  result: ToolResultEnvelope | undefined,
  rawCall?: ToolCall,
): string | null {
  const shortName = shortToolName(toolName);
  if (shortName !== "get_skill" && shortName !== "load_skill") return null;
  const resultJson = parseEnvelopeJson(result);
  const skillId = formatValue(resultJson?.id)
    || extractArgValue(args, "skill_id", "skill_name", "skillId", "name", "id");
  if (skillId) return formatSkillRef(skillId);
  const rawText = rawCall ? JSON.stringify(rawCall) : "";
  const rawMatch = rawText.match(/"skill_id"\s*:\s*"([^"]+)"/) || rawText.match(/\\"skill_id\\"\s*:\s*\\"([^"]+)\\"/);
  return rawMatch?.[1] ? formatSkillRef(rawMatch[1]) : null;
}

function buildEntryFromSummary(toolName: string, summary: ToolCallSummary, result: ToolResultEnvelope | undefined): TranscriptEntry {
  if (summary.kind === "diff" && summary.subject_type === "file") {
    return {
      kind: "file",
      id: `${toolName}:${summary.label}`,
      summary: summary.label,
      metaLabel: summary.diff_stats ? `(+${summary.diff_stats.additions} -${summary.diff_stats.deletions})` : null,
      detail: typeof result?.body === "string" ? result.body : (result?.plain_body || null),
      tone: "muted",
    };
  }
  if (summary.kind === "read" && summary.subject_type === "file") {
    return {
      kind: "file",
      id: `${toolName}:${summary.label}`,
      summary: summary.label,
      metaLabel: null,
      detail: null,
      tone: "muted",
    };
  }
  return {
    kind: "activity",
    id: `${toolName}:${summary.label}`,
    summary: summary.label,
    metaLabel: summary.target_label ? `(${summary.target_label})` : null,
    detail: summary.kind === "error" ? summary.error || null : null,
    tone: summary.kind === "error" ? "danger" : "default",
  };
}

function diffRows(detail: string): DetailRow[] {
  const rows: DetailRow[] = [];
  let oldLine: number | null = null;
  let newLine: number | null = null;

  for (const line of detail.split(/\r?\n/)) {
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      rows.push({ text: line, tone: "accent", lineNumber: null });
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

function plainRows(detail: string): DetailRow[] {
  return detail.split(/\r?\n/).map((line, index) => ({
    text: line,
    tone: "muted",
    lineNumber: String(index + 1),
    sign: null,
  }));
}

function detailRows(detail: string): DetailRow[] {
  return extractDiff(detail) ? diffRows(detail) : plainRows(detail);
}

function buildPersistedEntry(
  toolName: string,
  args: string | undefined,
  result: ToolResultEnvelope | undefined,
  toolSummary: ToolCallSummary | null | undefined,
  rawCall?: ToolCall,
): TranscriptEntry {
  if (toolSummary) {
    return buildEntryFromSummary(toolName, toolSummary, result);
  }
  const envelopeSummary = summarizeEnvelope(result);
  const fileAction = envelopeSummary ? parseFileAction(envelopeSummary) : null;
  if (fileAction) {
    const bodyText = typeof result?.body === "string" ? result.body : undefined;
    const diff = extractDiff(bodyText || result?.plain_body);
    const diffStats = summarizeDiffStats(diff);
    const lowerVerb = fileAction.verb.toLowerCase();
    const isRead = lowerVerb === "read";
    return {
      kind: "file",
      id: `${toolName}:${fileAction.verb}:${fileAction.path}`,
      summary: `${fileAction.verb} ${fileAction.path}`,
      metaLabel: diffStats ? `(+${diffStats.additions} -${diffStats.deletions})` : null,
      detail: isRead ? null : (diff ?? truncateBlock(bodyText || result?.plain_body, 900, 18)),
      tone: lowerVerb === "deleted" ? "danger" : "muted",
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
  const skillRef = resolveSkillRef(toolName, args, result, rawCall);

  return {
    kind: "activity",
    id: `${toolName}:${envelopeSummary || "activity"}`,
    summary,
    metaLabel: skillRef ? `(${skillRef})` : null,
    detail,
    tone: result?.content_type.includes("error") ? "danger" : "default",
  };
}

function collapseConsecutiveFileEntries(entries: TranscriptEntry[]): TranscriptEntry[] {
  return entries.map((entry) => ({ ...entry }));
}

function TranscriptBlock({ entries, t, onAddWidget, decidingIds, onApproval }: {
  entries: TranscriptEntry[];
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
              {entry.metaLabel && (
                <span
                  style={{
                    color: t.textDim,
                    marginLeft: 8,
                    fontSize: 11.5,
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

          {entry.kind === "file" && structuredDetail && (
            <div
              style={{
                marginLeft: 10,
                fontFamily: TERMINAL_FONT_STACK,
                fontSize: 11.5,
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
    const normalized = normalizePersistedToolCall(call);
    entries.push(buildPersistedEntry(
      normalized?.name ?? remainingToolNames[i] ?? "tool",
      normalized?.arguments,
      remainingToolResults[i],
      normalized?.summary,
      call,
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
