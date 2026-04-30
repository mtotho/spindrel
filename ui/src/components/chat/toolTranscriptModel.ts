import { normalizeToolCall } from "../../types/api.js";
import type {
  AssistantTurnBody,
  ToolCall,
  ToolCallSummary,
  ToolResultEnvelope,
  ToolSurface,
} from "../../types/api.js";

export type SharedToolTranscriptEntry = {
  id: string;
  kind: "activity" | "file" | "widget" | "approval";
  label: string;
  metaLabel?: string | null;
  previewText?: string | null;
  target?: string | null;
  args?: string;
  env?: ToolResultEnvelope;
  summary?: ToolCallSummary | null;
  isError: boolean;
  isRunning?: boolean;
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
    /** "local" | "client" | "mcp" | "harness". Drives harness-specific
     *  affordances on the approval row (Approve all this turn, tool-arg
     *  preview tailored to Bash / Edit / Write / ExitPlanMode). */
    toolType?: string;
    /** The actual tool name the harness wants to invoke (e.g. "Bash", "Edit").
     *  May differ from the entry's `label`, which is summary-style copy. */
    toolName?: string;
    /** Raw tool-input arguments the harness supplied for the approval prompt. */
    arguments?: Record<string, unknown>;
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
      kind: "rich_result";
      key: string;
      envelope: ToolResultEnvelope;
      summary?: ToolCallSummary | null;
    }
  | {
      kind: "root_rich_result";
      key: string;
      envelope: ToolResultEnvelope;
    };

export type OrderedTurnBodyItem =
  | {
      kind: "text";
      key: string;
      text: string;
    }
  | PersistedRenderItem;

export type OrderedLiveToolCall = {
  id: string;
  name: string;
  args?: string;
  summary?: ToolCallSummary | null;
  envelope?: ToolResultEnvelope;
  surface?: ToolSurface;
  status: "running" | "done" | "awaiting_approval" | "denied" | "expired";
  approvalId?: string;
  approvalReason?: string;
  tool_type?: string;
  capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
};

type CanonicalToolCall = OrderedLiveToolCall | ToolCall;
export type TranscriptRenderMode = "default" | "terminal";

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
  return clean;
}

function shortToolName(name: string): string {
  return name.includes("-") ? name.slice(name.lastIndexOf("-") + 1) : name;
}

function parsedArgsObject(args: string | undefined): Record<string, unknown> | null {
  return parseJsonObject(args);
}

function unwrapShellCommand(value: string): string {
  const trimmed = value.trim();
  for (const prefix of ["/bin/bash -lc ", "bash -lc ", "/bin/sh -lc ", "sh -lc "]) {
    if (trimmed.startsWith(prefix)) {
      let rest = trimmed.slice(prefix.length).trim();
      if (rest.length >= 2 && ((rest.startsWith("'") && rest.endsWith("'")) || (rest.startsWith("\"") && rest.endsWith("\"")))) {
        rest = rest.slice(1, -1);
      }
      return rest;
    }
  }
  return trimmed;
}

function shellCommandParts(command: string): { command: string; cwd?: string; display: string } {
  const inner = unwrapShellCommand(command);
  if (inner.startsWith("cd ") && inner.includes(" && ")) {
    const [cwdRaw, ...rest] = inner.slice(3).split(" && ");
    const cwd = cwdRaw.trim().replace(/^['"]|['"]$/g, "");
    const display = rest.join(" && ").trim();
    return { command, cwd: cwd || undefined, display: display || inner };
  }
  return { command, display: inner || command };
}

function shellCallSummary(toolName: string, args?: string, summaryLabel?: string | null): {
  label: string;
  metaLabel: string | null;
  target: string | null;
  command: string;
} | null {
  const parsed = parsedArgsObject(args);
  const commandFromArgs = formatValue(parsed?.command) || formatValue(parsed?.cmd);
  const commandFromName = /^(?:\/bin\/)?(?:bash|sh)\s+-lc\s+/.test(toolName.trim()) ? toolName : null;
  const commandFromSummary = summaryLabel && /^(?:\/bin\/)?(?:bash|sh)\s+-lc\s+/.test(summaryLabel.trim()) ? summaryLabel : null;
  const command = commandFromArgs || commandFromName || commandFromSummary;
  if (!command) return null;
  const cwdFromArgs = formatValue(parsed?.cwd) || formatValue(parsed?.workdir);
  const displayFromArgs = formatValue(parsed?.display_command) || formatValue(parsed?.displayCommand);
  const parts = shellCommandParts(command);
  const cwd = cwdFromArgs || parts.cwd || null;
  const display = displayFromArgs || parts.display || command;
  return {
    label: "Bash",
    metaLabel: cwd ? `(${cwd})` : null,
    target: display,
    command,
  };
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
    if (typeof parsed !== "object" || parsed === null) return false;
    // `ok: true` is the explicit success signal; never treat such results
    // as errors regardless of an empty `error` slot.
    if (parsed.ok === true) return false;
    // An `error` key only counts as an error when its value is non-empty.
    // Many tool results include `"error": null` on the happy path; those
    // are NOT errors. Same for empty strings and empty objects.
    const err = parsed.error;
    if (err === null || err === undefined) return false;
    if (typeof err === "string" && err.trim().length === 0) return false;
    if (typeof err === "object" && Object.keys(err as object).length === 0) return false;
    return "error" in parsed;
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

function normalizePreviewText(value: string | null | undefined, label?: string | null): string | null {
  if (!value) return null;
  const clean = value.trim();
  if (!clean) return null;
  if (label && clean === label.trim()) return null;
  return clean.length > 160 ? `${clean.slice(0, 159)}…` : clean;
}

function resolvePreviewText(
  summary: ToolCallSummary | null | undefined,
  result: ToolResultEnvelope | undefined,
  label?: string | null,
): string | null {
  return (
    normalizePreviewText(summary?.preview_text ?? null, label)
    ?? normalizePreviewText(summarizeEnvelope(result), label)
  );
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

function summaryFileTarget(summary: ToolCallSummary | null | undefined): string | null {
  if (!summary) return null;
  return summary.path || summary.target_label || null;
}

function isDiffEnvelope(env: ToolResultEnvelope | undefined): boolean {
  return env?.content_type === "application/vnd.spindrel.diff+text";
}

function diffSummaryFromEnvelope(
  toolSummary: ToolCallSummary | null | undefined,
  result: ToolResultEnvelope | undefined,
): ToolCallSummary | null {
  if (!isDiffEnvelope(result)) return null;
  const diff = extractDiffText(result);
  const stats = summarizeDiffStats(diff);
  const path = toolSummary?.path || toolSummary?.target_label || result?.display_label || null;
  const label = result?.plain_body?.trim()
    || toolSummary?.label
    || (path ? `Changed ${path}` : "Changed file");
  return {
    kind: "diff",
    subject_type: "file",
    label,
    ...(path ? { path } : {}),
    ...(stats ? { diff_stats: { additions: stats.additions, deletions: stats.deletions } } : {}),
  };
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
    !env.view_key &&
    (env.content_type === "application/vnd.spindrel.components+json"
      || env.content_type === "application/vnd.spindrel.html+interactive")
  );
}

function isRichInlineEnvelope(env: ToolResultEnvelope | undefined): boolean {
  return !!(env && env.display === "inline" && !isWidgetEnvelope(env));
}

function inferEnvelopeSurface(
  env: ToolResultEnvelope | undefined,
): ToolSurface | "root_rich_result" | null {
  if (isWidgetEnvelope(env)) return "widget";
  if (isRichInlineEnvelope(env)) return "rich_result";
  return env ? "root_rich_result" : null;
}

function resolveToolEnvelopeSurface(
  surface: ToolSurface | null | undefined,
  env: ToolResultEnvelope | undefined,
): ToolSurface | "root_rich_result" | null {
  if (env?.view_key) return "rich_result";
  return surface ?? inferEnvelopeSurface(env);
}

type OrderedToolResolution = {
  key: string;
  transcriptEntries: SharedToolTranscriptEntry[];
} | {
  key: string;
  widget: InlineWidgetEntry;
} | {
  key: string;
  envelope: ToolResultEnvelope;
  kind: "rich_result";
  summary?: ToolCallSummary | null;
};

function buildMissingToolDataEntry(toolCallId: string): SharedToolTranscriptEntry {
  return {
    id: `missing-tool:${toolCallId}`,
    kind: "activity",
    label: "Missing tool data",
    metaLabel: null,
    previewText: null,
    target: null,
    isError: true,
    detailKind: "none",
    detail: null,
    tone: "danger",
  };
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
    const operation = typeof parsed?.operation === "string" ? parsed.operation.toLowerCase() : "";
    const labelByOperation: Record<string, string> = {
      read: "Read file",
      create: "Created file",
      overwrite: "Updated file",
      append: "Updated file",
      edit: "Updated file",
      json_patch: "Updated file",
      delete: "Deleted file",
      mkdir: "Created folder",
      move: "Moved file",
      restore: "Restored file",
    };
    return labelByOperation[operation] ?? "Updated file";
  }
  const path = (parsed?.path || parsed?.file_path || parsed?.target_path || parsed?.source_path) as string | undefined;
  if (path) return `${toolName.replace(/_/g, " ")} ${path}`;
  return toolName.replace(/_/g, " ");
}

function extractFileToolTarget(toolName: string, args?: string): string | null {
  if (shortToolName(toolName) !== "file") return null;
  return extractArgValue(args, "path", "file_path", "target_path", "destination");
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
  const skillName = formatValue(resultJson?.name);
  if (skillName) return skillName;
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
  const shell = shellCallSummary(toolName, args, summary.label);
  if (shell) {
    const previewText = resolvePreviewText(summary, result, shell.label);
    return {
      id: `${toolName}:${summary.label}`,
      kind: "activity",
      label: shell.label,
      metaLabel: shell.metaLabel,
      previewText,
      target: shell.target,
      args,
      env: result,
      summary,
      isError: summary.kind === "error",
      isRunning: false,
      detailKind: result || args ? "expandable" : "none",
      detail: extractNonJsonOutput(result),
      tone: summary.kind === "error" ? "danger" : "default",
    };
  }
  const toolInfoRef = resolveToolInfoRef(toolName, args, result, rawCall);
  const target = summary.target_label || (toolInfoRef ? null : introspectionTarget(toolName, [args], rawCall, result));
  const previewText = resolvePreviewText(summary, result, summary.label);
  if (summary.kind === "diff" && summary.subject_type === "file") {
    return {
      id: `${toolName}:${summary.label}`,
      kind: "file",
      label: summary.label,
      metaLabel: summarizeDiffMeta(summary),
      previewText: null,
      target: summary.target_label ? null : target,
      env: result,
      summary,
      isError: false,
      isRunning: false,
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
      previewText,
      target: summary.target_label ? null : target,
      env: result,
      summary,
      isError: false,
      isRunning: false,
      detailKind: "collapsed-read",
      detail: null,
      tone: "muted",
    };
  }
  if (summary.kind === "write" && summary.subject_type === "file") {
    return {
      id: `${toolName}:${summary.label}`,
      kind: "file",
      label: summary.label,
      metaLabel: null,
      previewText,
      target: summaryFileTarget(summary),
      env: result,
      summary,
      isError: false,
      isRunning: false,
      detailKind: result ? "expandable" : "none",
      detail: extractNonJsonOutput(result),
      tone: "muted",
    };
  }
  return {
    id: `${toolName}:${summary.label}`,
    kind: "activity",
    label: summary.label,
    metaLabel: summarizeDiffMeta(summary) || toolInfoRef,
    previewText,
    target: summary.target_label ? null : target,
    env: result,
    summary,
    isError: summary.kind === "error",
    isRunning: false,
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
  const diffSummary = diffSummaryFromEnvelope(toolSummary, result);
  if (diffSummary) {
    return buildEntryFromSummary(toolName, diffSummary, result, args, rawCall);
  }

  if (toolSummary) {
    return buildEntryFromSummary(toolName, toolSummary, result, args, rawCall);
  }

  const shell = shellCallSummary(toolName, args);
  if (shell) {
    return {
      id: `${toolName}:${shell.command}`,
      kind: "activity",
      label: shell.label,
      metaLabel: shell.metaLabel,
      previewText: normalizePreviewText(resultSummary(result), shell.label),
      target: shell.target,
      args,
      env: result,
      isError: isErrorEnvelope(result),
      isRunning: false,
      detailKind: result || args ? "expandable" : "none",
      detail: extractNonJsonOutput(result),
      tone: result?.content_type.includes("error") ? "danger" : "default",
    };
  }

  const envelopeSummary = summarizeEnvelope(result);
  const genericSummary = summarizeGenericTool(toolName, args);
  const fileToolTarget = extractFileToolTarget(toolName, args);
  const summary = shouldPreferGenericSummary(envelopeSummary, genericSummary)
    ? genericSummary
    : envelopeSummary ?? genericSummary;
  const previewText = normalizePreviewText(
    shouldPreferGenericSummary(envelopeSummary, genericSummary) ? envelopeSummary : null,
    summary,
  ) ?? normalizePreviewText(resultSummary(result), summary);
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
      previewText: isRead ? previewText : null,
      target: fileToolTarget,
      env: result,
      summary: diff ? {
        kind: "diff",
        subject_type: "file",
        label: summary,
        ...(fileToolTarget ? { path: fileToolTarget } : {}),
        ...(diffStats ? { diff_stats: { additions: diffStats.additions, deletions: diffStats.deletions } } : {}),
      } : null,
      isError: false,
      isRunning: false,
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
    previewText,
    target: toolInfoRef || skillRef ? null : introspectionTarget(toolName, [args], rawCall, result),
    args,
    env: result,
    isError: isErrorEnvelope(result),
    isRunning: false,
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

function isPersistedToolCall(toolCall: CanonicalToolCall): toolCall is ToolCall {
  return "arguments" in toolCall || "function" in toolCall;
}

function resolveOrderedTool(
  toolCall: CanonicalToolCall,
  result: ToolResultEnvelope | undefined,
  index: number,
  renderMode: TranscriptRenderMode,
): OrderedToolResolution {
  if (isPersistedToolCall(toolCall)) {
    const normalized = normalizeToolCall(toolCall);
    const surface = resolveToolEnvelopeSurface(toolCall.surface, result);
    const richSurface = renderMode === "terminal" && surface === "widget" ? "rich_result" : surface;

    if (richSurface === "widget" && result) {
      return {
        key: `widget:${index}:${result.record_id ?? normalized.name ?? "widget"}`,
        widget: {
          envelope: result,
          toolName: normalized.name ?? "",
          recordId: result.record_id ?? undefined,
        },
      };
    }

    if (renderMode === "terminal" && surface === "widget" && richSurface === "rich_result" && result) {
      return {
        kind: "rich_result",
        key: `rich:${index}:${result.record_id ?? normalized.name ?? "result"}`,
        envelope: result,
        summary: toolCall.summary ?? null,
      };
    }

    if (renderMode === "terminal" && richSurface === "rich_result" && result) {
      return {
        key: `transcript:${index}:${normalized.name ?? toolCall.id ?? "tool"}`,
        transcriptEntries: buildPersistedToolEntries([], [toolCall], [result]),
      };
    }

    if (richSurface === "rich_result" && result) {
      return {
        kind: "rich_result",
        key: `rich:${index}:${result.record_id ?? normalized.name ?? "result"}`,
        envelope: result,
        summary: toolCall.summary ?? null,
      };
    }

    return {
      key: `transcript:${index}:${normalized.name ?? toolCall.id ?? "tool"}`,
      transcriptEntries: buildPersistedToolEntries([], [toolCall], [result]),
    };
  }

  const envelope = result ?? toolCall.envelope;
  const surface = resolveToolEnvelopeSurface(toolCall.surface, envelope);
  const richSurface = renderMode === "terminal" && surface === "widget" ? "rich_result" : surface;

  if (richSurface === "widget" && envelope) {
    return {
      key: `widget:${index}:${envelope.record_id ?? toolCall.name ?? "widget"}`,
      widget: {
        envelope,
        toolName: toolCall.name,
        recordId: envelope.record_id ?? undefined,
      },
    };
  }

  if (renderMode === "terminal" && surface === "widget" && richSurface === "rich_result" && envelope) {
    return {
      kind: "rich_result",
      key: `rich:${index}:${envelope.record_id ?? toolCall.name ?? "result"}`,
      envelope,
      summary: toolCall.summary ?? null,
    };
  }

  if (renderMode === "terminal" && richSurface === "rich_result" && envelope) {
    return {
      key: `transcript:${index}:${toolCall.name ?? toolCall.id ?? "tool"}`,
      transcriptEntries: buildLiveToolEntries([{ ...toolCall, envelope }]),
    };
  }

  if (richSurface === "rich_result" && envelope) {
    return {
      kind: "rich_result",
      key: `rich:${index}:${envelope.record_id ?? toolCall.name ?? "result"}`,
      envelope,
      summary: toolCall.summary ?? null,
    };
  }

  return {
    key: `transcript:${index}:${toolCall.name ?? toolCall.id ?? "tool"}`,
    transcriptEntries: buildLiveToolEntries([{ ...toolCall, envelope }]),
  };
}

function materializeAssistantTurnBodyItems({
  assistantTurnBody,
  orderedTools,
  rootEnvelope,
  missingToolBehavior = "placeholder",
}: {
  assistantTurnBody: AssistantTurnBody;
  orderedTools: Map<string, OrderedToolResolution>;
  rootEnvelope?: ToolResultEnvelope;
  missingToolBehavior?: "throw" | "placeholder";
}): OrderedTurnBodyItem[] {
  const items: OrderedTurnBodyItem[] = [];

  // Rich-inline envelopes normally bind to a tool_call. When there's no
  // tool_call to attach to (e.g. step_output sub-session messages from the
  // pipeline runtime), render the envelope at the message root through the
  // same RichToolResult path the per-tool surface uses. Without this branch
  // the envelope is silently dropped and the legacy text fallback dumps the
  // raw body as plain markdown.
  const rootSurface = inferEnvelopeSurface(rootEnvelope);
  const promoteRichToRoot =
    rootSurface === "rich_result" && orderedTools.size === 0 && rootEnvelope;
  if ((rootSurface === "root_rich_result" || promoteRichToRoot) && rootEnvelope) {
    items.push({
      kind: "root_rich_result",
      key: `root-rich:${rootEnvelope.record_id ?? rootEnvelope.display_label ?? "result"}`,
      envelope: rootEnvelope,
    });
  }

  for (const entry of assistantTurnBody.items) {
    if (entry.kind === "text") {
      if (!entry.text.trim()) continue;
      items.push({
        kind: "text",
        key: entry.id,
        text: entry.text,
      });
      continue;
    }

    const tool = orderedTools.get(entry.toolCallId);
    if (!tool) {
      if (missingToolBehavior === "throw") {
        throw new Error(`Transcript entry references missing canonical tool call: ${entry.toolCallId}`);
      }
      items.push({
        kind: "transcript",
        key: `${entry.id}:missing-tool:${entry.toolCallId}`,
        entries: [buildMissingToolDataEntry(entry.toolCallId)],
      });
      continue;
    }

    if ("widget" in tool) {
      items.push({
        kind: "widget",
        key: `${entry.id}:${tool.key}`,
        widget: tool.widget,
      });
      continue;
    }

    if ("envelope" in tool) {
      items.push({
        kind: tool.kind,
        key: `${entry.id}:${tool.key}`,
        envelope: tool.envelope,
        summary: tool.summary,
      });
      continue;
    }

    items.push({
      kind: "transcript",
      key: `${entry.id}:${tool.key}`,
      entries: tool.transcriptEntries,
    });
  }

  return items;
}

export function buildAssistantTurnBodyItems({
  assistantTurnBody,
  toolCalls,
  toolResults,
  rootEnvelope,
  renderMode = "default",
  missingToolBehavior = "placeholder",
}: {
  assistantTurnBody: AssistantTurnBody;
  toolCalls: CanonicalToolCall[];
  toolResults?: (ToolResultEnvelope | undefined)[];
  rootEnvelope?: ToolResultEnvelope;
  renderMode?: TranscriptRenderMode;
  missingToolBehavior?: "throw" | "placeholder";
}): OrderedTurnBodyItem[] {
  const toolResultById = new Map<string, ToolResultEnvelope>();
  const legacyToolResults: (ToolResultEnvelope | undefined)[] = [];
  for (const toolResult of toolResults ?? []) {
    if (toolResult?.tool_call_id) {
      toolResultById.set(toolResult.tool_call_id, toolResult);
      continue;
    }
    legacyToolResults.push(toolResult);
  }

  const orderedTools = new Map<string, OrderedToolResolution>();
  let legacyToolResultIndex = 0;
  for (let index = 0; index < toolCalls.length; index += 1) {
    const toolCall = toolCalls[index];
    const toolId = toolCall.id || `tool-${index + 1}`;
    const toolResult = toolResultById.get(toolId) ?? legacyToolResults[legacyToolResultIndex];
    if (!toolResultById.get(toolId) && legacyToolResultIndex < legacyToolResults.length) {
      legacyToolResultIndex += 1;
    }
    orderedTools.set(toolId, resolveOrderedTool(toolCall, toolResult, index, renderMode));
  }
  return materializeAssistantTurnBodyItems({
    assistantTurnBody,
    orderedTools,
    rootEnvelope,
    missingToolBehavior,
  });
}

export function buildLegacyAssistantTurnBody({
  displayContent,
  transcriptEntries,
  toolCalls,
  rootEnvelope,
}: {
  displayContent?: string;
  transcriptEntries?: AssistantTurnBody["items"];
  toolCalls?: ToolCall[];
  rootEnvelope?: ToolResultEnvelope;
}): AssistantTurnBody {
  if (transcriptEntries?.length) {
    return {
      version: 1,
      items: transcriptEntries.map((entry) => ({ ...entry })),
    };
  }

  // When a rich-inline envelope is present and the row has no tool_calls,
  // the envelope IS the content (e.g. sub-session step_output rows persist
  // the JSON body as both `content` and `metadata.envelope.body`). Skip
  // the duplicate legacy text item so materialize can promote the envelope
  // to a root_rich_result and render through RichToolResult instead of
  // dumping the raw body via MarkdownContent.
  const skipText =
    !!rootEnvelope &&
    isRichInlineEnvelope(rootEnvelope) &&
    !toolCalls?.length &&
    !!displayContent &&
    (rootEnvelope.body === displayContent
      || rootEnvelope.plain_body === displayContent
      || rootEnvelope.truncated === true);

  const items: AssistantTurnBody["items"] = [];
  if (displayContent && !skipText) {
    items.push({ id: "legacy:text", kind: "text", text: displayContent });
  }
  for (let index = 0; index < (toolCalls?.length ?? 0); index += 1) {
    const toolCall = toolCalls![index];
    const toolCallId = toolCall.id || `legacy-tool-${index + 1}`;
    items.push({
      id: `legacy:tool:${toolCallId}`,
      kind: "tool_call",
      toolCallId,
    });
  }
  return { version: 1, items };
}

export function buildLiveToolEntries(toolCalls: {
  id?: string;
  name: string;
  args?: string;
  summary?: ToolCallSummary | null;
  envelope?: ToolResultEnvelope;
  status: "running" | "done" | "awaiting_approval" | "denied" | "expired";
  approvalId?: string;
  approvalReason?: string;
  tool_type?: string;
  capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
}[]): SharedToolTranscriptEntry[] {
  return toolCalls.map((tc, index) => {
    const toolName = tc.capability?.name || tc.name;
    const diffSummary = diffSummaryFromEnvelope(tc.summary, tc.envelope);
    const base = diffSummary
      ? buildEntryFromSummary(toolName, diffSummary, tc.envelope, tc.args)
      : tc.summary
      ? buildEntryFromSummary(toolName, tc.summary, tc.envelope)
      : buildPersistedEntry(toolName, tc.args, tc.envelope, null);

    let parsedArgs: Record<string, unknown> | undefined;
    if (tc.args) {
      const parsed = parseJsonObject(tc.args);
      if (parsed) parsedArgs = parsed;
    }

    return {
      ...base,
      id: tc.id ? `stream:${tc.id}` : `stream:${toolName}:${tc.status}:${index}`,
      kind: tc.status === "awaiting_approval" && tc.approvalId ? "approval" : base.kind,
      label: tc.status === "awaiting_approval"
        ? `Approval required: ${toolName}`
        : tc.status === "expired"
          ? `Expired: ${toolName}`
          : base.label,
      detail: formatSimpleParams(tc.args) || tc.approvalReason || tc.capability?.description || base.detail || null,
      isRunning: tc.status === "running",
      tone: tc.status === "awaiting_approval"
          ? "warning"
          : tc.status === "denied"
            ? "danger"
            : tc.status === "expired"
              ? "muted"
              : tc.status === "running"
                ? "default"
                : base.tone,
      approval: tc.approvalId && tc.status === "awaiting_approval" ? {
        approvalId: tc.approvalId,
        capabilityId: tc.capability?.id,
        reason: tc.approvalReason,
        toolType: tc.tool_type,
        toolName: tc.name,
        arguments: parsedArgs,
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
