import { normalizeToolCall } from "../../types/api";
import type { ToolCall, ToolCallSummary, ToolResultEnvelope, ToolSurface } from "../../types/api";

export type SharedToolTranscriptEntry = {
  id: string;
  kind: "activity" | "file" | "widget" | "approval";
  label: string;
  metaLabel?: string | null;
  target?: string | null;
  args?: string;
  env?: ToolResultEnvelope;
  isError: boolean;
  detailKind: "inline-diff" | "collapsed-read" | "expandable" | "none";
  detail?: string | null;
  tone?: "default" | "muted" | "success" | "warning" | "danger" | "accent";
  widget?: {
    envelope: ToolResultEnvelope;
    toolName: string;
    recordId?: string;
  };
  approval?: {
    approvalId: string;
    capabilityId?: string;
    reason?: string;
  };
};

export type InlineWidgetEntry = {
  envelope: ToolResultEnvelope;
  toolName: string;
  recordId?: string;
};

export type PersistedRenderItem =
  | {
      kind: "transcript";
      key: string;
      entries: SharedToolTranscriptEntry[];
    }
  | {
      kind: "widget";
      key: string;
      widget: InlineWidgetEntry;
    }
  | {
      kind: "rich_result" | "root_rich_result";
      key: string;
      envelope: ToolResultEnvelope;
    };

export type DetailRow = {
  text: string;
  tone?: "default" | "muted" | "success" | "warning" | "danger" | "accent";
  lineNumber?: string | null;
  sign?: string | null;
};

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

export function looksLikeJson(text: string | null | undefined): boolean {
  if (!text) return false;
  const trimmed = text.trim();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
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

function shortToolName(name: string): string {
  return name.includes("-") ? name.slice(name.lastIndexOf("-") + 1) : name;
}

function introspectionTarget(
  name: string,
  argsList: (string | undefined)[],
  rawCall?: ToolCall,
  result?: ToolResultEnvelope,
): string | null {
  const short = shortToolName(name);
  if (short !== "get_tool_info" && short !== "get_skill" && short !== "load_skill") return null;
  for (const raw of argsList) {
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw);
      const target = parsed?.tool_name ?? parsed?.skill_id ?? parsed?.name ?? parsed?.tool?.name ?? parsed?.skill?.id;
      if (typeof target === "string" && target) return target;
    } catch {
      // ignore malformed args
    }
  }
  if (result) {
    const parsed = parseEnvelopeJson(result);
    const target = parsed?.tool_name ?? parsed?.name ?? parsed?.id;
    if (typeof target === "string" && target) return target;
  }
  if (rawCall) {
    const normalized = normalizeToolCall(rawCall);
    if (normalized.arguments) {
      const fallback = introspectionTarget(name, [normalized.arguments]);
      if (fallback) return fallback;
    }
  }
  return null;
}

export function envelopeBodyText(env: ToolResultEnvelope | undefined): string {
  if (!env) return "";
  if (typeof env.body === "string") return env.body;
  return env.plain_body ?? "";
}

export function envelopeBodyLength(env: ToolResultEnvelope | undefined): number {
  if (!env) return 0;
  if (typeof env.body === "string") return env.body.length;
  if (env.body && typeof env.body === "object") return JSON.stringify(env.body).length;
  return (env.plain_body ?? "").length;
}

function parseEnvelopeJson(envelope: ToolResultEnvelope | undefined): Record<string, unknown> | null {
  if (!envelope) return null;
  if (typeof envelope.body === "string") return parseJsonObject(envelope.body);
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

export function resultSummary(env: ToolResultEnvelope | undefined): string {
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
  const json = parseEnvelopeJson(env);
  if (json) {
    const compact = JSON.stringify(json);
    if (compact.length <= 120) return compact;
  }
  if (env.byte_size > 0) return `${(env.byte_size / 1024).toFixed(1)} KB`;
  return "";
}

function summarizeEnvelope(envelope: ToolResultEnvelope | undefined | null): string | null {
  if (!envelope) return null;
  const label = envelope.display_label?.trim();
  if (label) return label;
  const bodyText = typeof envelope.body === "string" ? envelope.body : "";
  const firstLine = firstMeaningfulLine(envelope.plain_body || bodyText || "");
  if (!firstLine || looksLikeJson(firstLine)) return null;
  return firstLine.length > 160 ? `${firstLine.slice(0, 159)}…` : firstLine;
}

function summarizeDiffMeta(summary: ToolCallSummary | null | undefined): string | null {
  if (!summary) return null;
  if (summary.kind === "diff" && summary.diff_stats) {
    return `(+${summary.diff_stats.additions} -${summary.diff_stats.deletions})`;
  }
  if (summary.subject_type === "skill") {
    const skillRef = summary.target_label || (summary.target_id ? formatSkillRef(summary.target_id) : null);
    if (skillRef) return `(${skillRef})`;
  }
  if (summary.target_label) {
    return `(${summary.target_label})`;
  }
  return null;
}

export function extractDiffText(env: ToolResultEnvelope | undefined): string | null {
  if (!env) return null;
  if (typeof env.body === "string" && env.body.trim()) return env.body;
  if (env.plain_body?.trim()) return env.plain_body;
  return null;
}

function extractDiff(text: string | null | undefined): string | null {
  if (!text) return null;
  const trimmed = text.trim();
  if (!/^(---|\+\+\+|@@|\+|-)/m.test(trimmed)) return null;
  return trimmed;
}

function summarizeDiffStats(diff: string | null | undefined): { additions: number; deletions: number } | null {
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

function extractNonJsonOutput(envelope: ToolResultEnvelope | undefined): string | null {
  if (!envelope) return null;
  const body = typeof envelope.body === "string" ? envelope.body : (envelope.plain_body || "");
  if (!body.trim() || looksLikeJson(body)) return null;
  const diff = extractDiff(body);
  if (diff) return diff;
  return truncateBlock(body);
}

function isWidgetEnvelope(env: ToolResultEnvelope | undefined): boolean {
  return !!(
    env &&
    env.display === "inline" &&
    (env.content_type === "application/vnd.spindrel.components+json"
      || env.content_type === "application/vnd.spindrel.html+interactive")
  );
}

function isRichInlineEnvelope(env: ToolResultEnvelope | undefined): boolean {
  return !!(env && env.display === "inline" && !isWidgetEnvelope(env));
}

function resolveEnvelopeSurface(
  env: ToolResultEnvelope | undefined,
  surface?: ToolSurface,
): ToolSurface | "root_rich_result" | null {
  if (surface) return surface;
  if (isWidgetEnvelope(env)) return "widget";
  if (isRichInlineEnvelope(env)) return "rich_result";
  return env ? "root_rich_result" : null;
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

function resolveToolInfoRef(
  toolName: string,
  args: string | undefined,
  result: ToolResultEnvelope | undefined,
  rawCall?: ToolCall,
): string | null {
  if (shortToolName(toolName) !== "get_tool_info") return null;
  const target = introspectionTarget(toolName, [args], rawCall, result);
  return target ? `(${target})` : null;
}

function buildEntryFromSummary(
  toolName: string,
  summary: ToolCallSummary,
  result: ToolResultEnvelope | undefined,
  args?: string,
  rawCall?: ToolCall,
): SharedToolTranscriptEntry {
  const toolInfoRef = resolveToolInfoRef(toolName, args, result, rawCall);
  const target = summary.target_label || (toolInfoRef ? null : introspectionTarget(toolName, [args], rawCall, result));
  if (summary.kind === "diff" && summary.subject_type === "file") {
    return {
      id: `${toolName}:${summary.label}`,
      kind: "file",
      label: summary.label,
      metaLabel: summarizeDiffMeta(summary),
      target: summary.target_label ? null : target,
      env: result,
      isError: false,
      detailKind: "inline-diff",
      detail: extractDiffText(result),
      tone: "muted",
    };
  }
  if (summary.kind === "read" && summary.subject_type === "file") {
    return {
      id: `${toolName}:${summary.label}`,
      kind: "file",
      label: summary.label,
      metaLabel: null,
      target: summary.target_label ? null : target,
      env: result,
      isError: false,
      detailKind: "collapsed-read",
      detail: null,
      tone: "muted",
    };
  }
  return {
    id: `${toolName}:${summary.label}`,
    kind: "activity",
    label: summary.label,
    metaLabel: summarizeDiffMeta(summary) || toolInfoRef,
    target: summary.target_label ? null : target,
    env: result,
    isError: summary.kind === "error",
    detailKind: result ? "expandable" : "none",
    detail: summary.kind === "error" ? summary.error || null : null,
    tone: summary.kind === "error" ? "danger" : "default",
  };
}

function buildPersistedEntry(
  toolName: string,
  args: string | undefined,
  result: ToolResultEnvelope | undefined,
  toolSummary: ToolCallSummary | null | undefined,
  rawCall?: ToolCall,
): SharedToolTranscriptEntry {
  if (toolSummary) {
    return buildEntryFromSummary(toolName, toolSummary, result, args, rawCall);
  }

  const envelopeSummary = summarizeEnvelope(result);
  const genericSummary = summarizeGenericTool(toolName, args);
  const summary = shouldPreferGenericSummary(envelopeSummary, genericSummary)
    ? genericSummary
    : envelopeSummary ?? genericSummary;
  const diff = extractDiff(typeof result?.body === "string" ? result.body : result?.plain_body);
  const diffStats = summarizeDiffStats(diff);
  const isLikelyFile = summary.match(/^(Read|Edited|Wrote|Created|Deleted)\s+/i);
  if (isLikelyFile) {
    const isRead = /^read\s+/i.test(summary);
    return {
      id: `${toolName}:${summary}`,
      kind: "file",
      label: summary,
      metaLabel: diffStats ? `(+${diffStats.additions} -${diffStats.deletions})` : null,
      env: result,
      isError: false,
      detailKind: isRead ? "collapsed-read" : diff ? "inline-diff" : "expandable",
      detail: isRead ? null : (diff ?? extractNonJsonOutput(result)),
      tone: /^deleted\s+/i.test(summary) ? "danger" : "muted",
    };
  }

  const toolInfoRef = resolveToolInfoRef(toolName, args, result, rawCall);
  const skillRef = resolveSkillRef(toolName, args, result, rawCall);

  return {
    id: `${toolName}:${summary}`,
    kind: "activity",
    label: summary,
    metaLabel: toolInfoRef || (skillRef ? `(${skillRef})` : null),
    target: toolInfoRef || skillRef ? null : introspectionTarget(toolName, [args], rawCall, result),
    args,
    env: result,
    isError: isErrorEnvelope(result),
    detailKind: result || args ? "expandable" : "none",
    detail: (() => {
      const paramsDetail = formatSimpleParams(args);
      const outputDetail = extractNonJsonOutput(result);
      return paramsDetail && outputDetail
        ? `${paramsDetail}\n\n${outputDetail}`
        : paramsDetail || outputDetail;
    })(),
    tone: result?.content_type.includes("error") ? "danger" : "default",
  };
}

export function buildPersistedToolEntries(
  toolNames: string[],
  toolCalls?: ToolCall[],
  toolResults?: (ToolResultEnvelope | undefined)[],
): SharedToolTranscriptEntry[] {
  if (!toolCalls || toolCalls.length === 0) {
    return toolNames.map((name, index) =>
      buildPersistedEntry(name, undefined, toolResults?.[index], null),
    );
  }

  return toolCalls.map((tc, index) => {
    const norm = normalizeToolCall(tc);
    return buildPersistedEntry(
      norm.name,
      norm.arguments,
      toolResults?.[index],
      tc.summary,
      tc,
    );
  });
}

export function buildPersistedRenderItems({
  toolNames,
  toolCalls,
  toolResults,
  rootEnvelope,
}: {
  toolNames: string[];
  toolCalls?: ToolCall[];
  toolResults?: (ToolResultEnvelope | undefined)[];
  rootEnvelope?: ToolResultEnvelope;
}): PersistedRenderItem[] {
  const items: PersistedRenderItem[] = [];

  if (toolCalls?.length) {
    for (let index = 0; index < toolCalls.length; index += 1) {
      const call = toolCalls[index];
      const env = toolResults?.[index];
      const normalized = normalizeToolCall(call);
      const surface = resolveEnvelopeSurface(env, call.surface);

      if (surface === "widget" && env) {
        items.push({
          kind: "widget",
          key: `widget:${index}:${env.record_id ?? normalized.name ?? "widget"}`,
          widget: {
            envelope: env,
            toolName: normalized.name ?? "",
            recordId: env.record_id ?? undefined,
          },
        });
        continue;
      }

      if (surface === "rich_result" && env) {
        items.push({
          kind: "rich_result",
          key: `rich:${index}:${env.record_id ?? normalized.name ?? "result"}`,
          envelope: env,
        });
        continue;
      }

      items.push({
        kind: "transcript",
        key: `transcript:${index}:${normalized.name ?? call.id ?? "tool"}`,
        entries: buildPersistedToolEntries([], [call], [env]),
      });
    }
  } else {
    const count = Math.max(toolNames.length, toolResults?.length ?? 0);
    for (let index = 0; index < count; index += 1) {
      const name = toolNames[index];
      const env = toolResults?.[index];
      const surface = resolveEnvelopeSurface(env);

      if (surface === "widget" && env) {
        items.push({
          kind: "widget",
          key: `widget:${index}:${env.record_id ?? name ?? "widget"}`,
          widget: {
            envelope: env,
            toolName: name ?? "",
            recordId: env.record_id ?? undefined,
          },
        });
        continue;
      }

      if (surface === "rich_result" && env) {
        items.push({
          kind: "rich_result",
          key: `rich:${index}:${env.record_id ?? name ?? "result"}`,
          envelope: env,
        });
        continue;
      }

      if (!name && !env) continue;
      items.push({
        kind: "transcript",
        key: `transcript:${index}:${name ?? "tool"}`,
        entries: buildPersistedToolEntries(name ? [name] : [], [], [env]),
      });
    }
  }

  const rootSurface = resolveEnvelopeSurface(rootEnvelope);
  if (rootSurface === "root_rich_result" && rootEnvelope) {
    items.unshift({
      kind: "root_rich_result",
      key: `root-rich:${rootEnvelope.record_id ?? rootEnvelope.display_label ?? "result"}`,
      envelope: rootEnvelope,
    });
  }

  return items;
}

export function buildLiveToolEntries(toolCalls: {
  name: string;
  args?: string;
  summary?: ToolCallSummary | null;
  envelope?: ToolResultEnvelope;
  status: "running" | "done" | "awaiting_approval" | "denied";
  approvalId?: string;
  approvalReason?: string;
  capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
}[]): SharedToolTranscriptEntry[] {
  return toolCalls.map((tc, index) => {
    const toolName = tc.capability?.name || tc.name;
    const base = tc.summary
      ? buildEntryFromSummary(toolName, tc.summary, tc.envelope)
      : buildPersistedEntry(toolName, tc.args, tc.envelope, null);

    return {
      ...base,
      id: `stream:${toolName}:${tc.status}:${index}`,
      kind: tc.status === "awaiting_approval" && tc.approvalId ? "approval" : base.kind,
      label: tc.status === "awaiting_approval"
        ? `Approval required: ${toolName}`
        : base.label,
      detail: formatSimpleParams(tc.args) || tc.approvalReason || tc.capability?.description || base.detail || null,
      tone: tc.status === "done"
        ? base.tone === "danger"
          ? "danger"
          : "success"
        : tc.status === "awaiting_approval"
          ? "warning"
          : tc.status === "denied"
            ? "danger"
            : "muted",
      approval: tc.approvalId ? {
        approvalId: tc.approvalId,
        capabilityId: tc.capability?.id,
        reason: tc.approvalReason,
      } : undefined,
    };
  });
}

export function diffRows(detail: string): DetailRow[] {
  const rows: DetailRow[] = [];
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

function plainRows(detail: string): DetailRow[] {
  return detail.split(/\r?\n/).map((line, index) => ({
    text: line,
    tone: "muted",
    lineNumber: String(index + 1),
    sign: null,
  }));
}

export function detailRows(detail: string): DetailRow[] {
  return extractDiff(detail) ? diffRows(detail) : plainRows(detail);
}
