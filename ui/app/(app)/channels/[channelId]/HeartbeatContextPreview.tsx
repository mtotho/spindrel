import { useState, useMemo } from "react";
import { ChevronDown, ChevronRight, FileText, Pencil } from "lucide-react";
import { ActionButton } from "@/src/components/shared/SettingsControls";

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
  const [expanded, setExpanded] = useState(false);
  const preview = useMemo(() => buildMetadataPreview(form, data), [form, data]);

  return (
    <div className="mt-5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-text-dim transition-colors hover:text-text-muted"
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Context Preview
      </button>
      {expanded && (
        <pre className="mt-2 max-h-[400px] overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-surface/80 px-3 py-2.5 font-mono text-[11px] leading-relaxed text-text-muted">
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
  const PREVIEW_LINES = 12;
  const lines = content.split("\n");
  const isLong = lines.length > PREVIEW_LINES;
  const displayContent = expanded || !isLong
    ? content
    : lines.slice(0, PREVIEW_LINES).join("\n") + "\n...";

  return (
    <div className="flex flex-col gap-2">
      {description && (
        <div className="text-xs leading-relaxed text-text-dim">
          {description}
        </div>
      )}
      <div className="rounded-md bg-surface-raised/45 px-3 py-2.5">
        <div className="mb-2 flex items-center gap-1.5">
          <FileText size={12} className="text-text-dim" />
          <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-text-dim">
            Template Prompt
          </span>
        </div>
        <pre className="m-0 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-text">
          {displayContent}
        </pre>
        {isLong && (
          <button
            type="button"
            onClick={onToggleExpand}
            className="mt-1 p-0 text-[11px] font-medium text-accent transition-colors hover:text-accent-muted"
          >
            {expanded ? "Show less" : `Show all (${lines.length} lines)`}
          </button>
        )}
        <div className="mt-2 flex gap-1.5">
          <ActionButton
            label="Customize for this channel"
            onPress={onCustomize}
            icon={<Pencil size={11} />}
            variant="secondary"
            size="small"
          />
        </div>
      </div>
    </div>
  );
}
