import { useState, useMemo } from "react";
import { ChevronDown, ChevronRight, FileText, Pencil } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

function buildMetadataPreview(form: any, data: any): string {
  const interval = form?.interval_minutes ?? 60;
  const dispatchResults = form?.dispatch_results ?? true;
  const dispatchMode = form?.dispatch_mode ?? "always";
  const prevMaxChars = form?.previous_result_max_chars;
  const globalDefault = data?.default_previous_result_chars ?? 500;
  const effectiveMax = prevMaxChars ?? globalDefault;

  const lines = [
    "[SCHEDULED HEARTBEAT]",
    "You are running a scheduled heartbeat \u2014 an automated periodic prompt (not a user message).",
    "Your job: follow the prompt below, analyze what is relevant, and produce a concise result.",
    "Current time: {current_time}",
    `Channel: ${data?.channel_name ?? "{channel_name}"}`,
    `Heartbeat interval: every ${interval} minutes`,
    "Run number: {run_number}",
    "Last heartbeat: {last_run_time}",
    "Activity since last heartbeat: {activity_summary}",
  ];

  const qStart = form?.quiet_start;
  const qEnd = form?.quiet_end;
  const qTz = form?.timezone;
  if (qStart && qEnd) {
    lines.push(`Quiet hours: ${qStart}\u2013${qEnd} (${qTz || data?.default_timezone || "server default"})`);
  } else if (data?.default_quiet_hours) {
    lines.push(`Quiet hours: ${data.default_quiet_hours} (global default, ${data.default_timezone})`);
  }

  if (effectiveMax === 0) {
    lines.push("Previous heartbeat conclusion: {full_previous_result}");
  } else {
    lines.push(`Previous heartbeat conclusion: {previous_result_truncated_to_${effectiveMax}_chars}`);
    lines.push("(Use get_last_heartbeat tool for full previous output if needed)");
  }

  if (dispatchResults && dispatchMode === "optional") {
    lines.push(
      "Dispatch: Your response will NOT be automatically posted. " +
      "You have a post_heartbeat_to_channel tool \u2014 call it ONLY if you have " +
      "something worth sharing. If nothing noteworthy, just respond normally " +
      "and nothing will be posted to the channel."
    );
  } else if (dispatchResults) {
    lines.push("Dispatch: Your response will be posted to the channel.");
  }

  const repEnabled = form?.repetition_detection ?? data?.default_repetition_detection ?? true;
  if (repEnabled) {
    lines.push("");
    lines.push("Recent heartbeat outputs (newest first):");
    lines.push("  #1 ({N}m ago): {first_line_of_result} [tools: ...]");
    lines.push("  #2 ({N}m ago): {first_line_of_result} [tools: ...]");
    lines.push("");
    lines.push("{repetition_warning_if_detected}");
  }

  lines.push(
    "",
    "--- [system: current-turn marker] ---",
    "Everything above is context and conversation history. The user's CURRENT message follows \u2014 respond to it directly.",
    "",
    "--- [user message: heartbeat prompt] ---",
    "{heartbeat_prompt}",
  );
  return lines.join("\n");
}

export function ContextPreview({ form, data }: { form: any; data: any }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const preview = useMemo(() => buildMetadataPreview(form, data), [form, data]);

  return (
    <div style={{ marginTop: 20 }}>
      <div
        onClick={() => setExpanded((v) => !v)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6, cursor: "pointer",
          fontSize: 11, fontWeight: 600, color: t.textDim,
          letterSpacing: "0.05em", textTransform: "uppercase",
        }}
      >
        {expanded ? <ChevronDown size={12} color={t.textDim} /> : <ChevronRight size={12} color={t.textDim} />}
        Context Preview
      </div>
      {expanded && (
        <pre style={{
          marginTop: 8, padding: 12, background: t.codeBg, borderRadius: 6,
          border: `1px solid ${t.surfaceBorder}`,
          fontSize: 11, lineHeight: 1.6, color: t.textMuted,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          maxHeight: 400, overflowY: "auto",
          fontFamily: "monospace",
        }}>
          {preview}
        </pre>
      )}
    </div>
  );
}

export function HeartbeatTemplatePreview({
  content,
  description,
  expanded,
  onToggleExpand,
  onCustomize,
}: {
  content: string;
  description?: string | null;
  expanded: boolean;
  onToggleExpand: () => void;
  onCustomize: () => void;
}) {
  const t = useThemeTokens();
  const PREVIEW_LINES = 12;
  const lines = content.split("\n");
  const isLong = lines.length > PREVIEW_LINES;
  const displayContent = expanded || !isLong
    ? content
    : lines.slice(0, PREVIEW_LINES).join("\n") + "\n...";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {description && (
        <div style={{ fontSize: 12, color: t.textDim, lineHeight: "1.5" }}>
          {description}
        </div>
      )}
      <div style={{
        borderLeft: `3px solid ${t.accent}`,
        borderRadius: 6,
        background: t.surfaceOverlay,
        padding: 12,
      }}>
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8,
        }}>
          <FileText size={12} color={t.textDim} />
          <span style={{
            fontSize: 10, fontWeight: 700, color: t.textDim,
            textTransform: "uppercase", letterSpacing: "0.05em",
          }}>
            Template Prompt
          </span>
        </div>
        <pre style={{
          margin: 0, fontSize: 12, fontFamily: "monospace",
          color: t.text, lineHeight: "1.5",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>
          {displayContent}
        </pre>
        {isLong && (
          <button
            onClick={onToggleExpand}
            style={{
              marginTop: 4, padding: 0, border: "none", cursor: "pointer",
              background: "none", fontSize: 11, color: t.accent, fontWeight: 500,
            }}
          >
            {expanded ? "Show less" : `Show all (${lines.length} lines)`}
          </button>
        )}
        <div style={{ display: "flex", flexDirection: "row", gap: 6, marginTop: 10 }}>
          <button
            onClick={onCustomize}
            style={{
              display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "4px 10px", borderRadius: 4, cursor: "pointer",
              fontSize: 11, fontWeight: 500,
              border: `1px solid ${t.surfaceBorder}`,
              background: "transparent", color: t.textDim,
            }}
          >
            <Pencil size={11} />
            Customize for this channel
          </button>
        </div>
      </div>
    </div>
  );
}
