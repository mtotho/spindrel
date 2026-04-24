import { useMemo, useState } from "react";
import { AlertTriangle, Check, Code2, Copy, ExternalLink, MessageSquare, Search, Wrench, X } from "lucide-react";

import { useTrace, type TraceDetailResponse, type TraceEvent } from "@/src/api/hooks/useLogs";
import { writeToClipboard } from "@/src/utils/clipboard";
import { ActionButton, EmptyState, QuietPill, SettingsControlRow, SettingsSegmentedControl, StatusBadge } from "./SettingsControls";

type TraceFilter = "all" | "messages" | "tools" | "usage" | "errors";

interface TraceInspectorProps {
  correlationId: string | null | undefined;
  title?: string;
  subtitle?: string;
  onClose: () => void;
  onOpenFullTrace?: (correlationId: string) => void;
  className?: string;
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function eventKind(event: TraceEvent): TraceFilter {
  if (event.kind === "message") return "messages";
  if (event.kind === "tool_call") return "tools";
  if (event.event_type === "token_usage") return "usage";
  if (event.event_type === "error" || event.event_type === "llm_error" || event.error) return "errors";
  return "all";
}

function eventLabel(event: TraceEvent): string {
  if (event.kind === "message") return event.role === "user" ? "User message" : "Assistant response";
  if (event.kind === "tool_call") return event.tool_name || "Tool call";
  return event.event_name || event.event_type || "Trace event";
}

function eventIcon(event: TraceEvent) {
  if (event.kind === "message") return <MessageSquare size={14} />;
  if (event.kind === "tool_call") return <Wrench size={14} />;
  if (event.event_type === "token_usage") return <Code2 size={14} />;
  if (event.event_type === "error" || event.event_type === "llm_error" || event.error) return <AlertTriangle size={14} />;
  return <Code2 size={14} />;
}

function eventTone(event: TraceEvent): "neutral" | "info" | "warning" | "danger" | "success" {
  if (event.event_type === "error" || event.event_type === "llm_error" || event.error) return "danger";
  if (event.kind === "tool_call") return event.error ? "danger" : "info";
  if (event.event_type === "token_usage") return "neutral";
  if (event.kind === "message") return "success";
  return "neutral";
}

function eventSummary(event: TraceEvent): string {
  if (event.kind === "message") {
    const content = event.content || "";
    return content.length > 160 ? `${content.slice(0, 160)}...` : content || "Empty message";
  }
  if (event.kind === "tool_call") {
    if (event.error) return event.error;
    if (event.result) return event.result.length > 140 ? `${event.result.slice(0, 140)}...` : event.result;
    return event.tool_type ? `${event.tool_type} tool` : "Tool call";
  }
  if (event.event_type === "token_usage" && event.data) {
    const total = event.data.total_tokens ?? 0;
    const prompt = event.data.prompt_tokens ?? 0;
    const completion = event.data.completion_tokens ?? 0;
    return `${fmtTokens(total)} tokens (${fmtTokens(prompt)} in / ${fmtTokens(completion)} out)`;
  }
  if (event.error) return event.error;
  if (event.data) return JSON.stringify(event.data).slice(0, 180);
  return event.event_type || "Trace event";
}

function formatTraceForCopy(data: TraceDetailResponse): string {
  const lines = [`Trace ${data.correlation_id}`];
  if (data.bot_id) lines.push(`Bot: ${data.bot_id}`);
  if (data.session_id) lines.push(`Session: ${data.session_id}`);
  lines.push("");
  for (const event of data.events) {
    lines.push(`[${fmtTime(event.created_at)}] ${eventLabel(event)}${event.duration_ms != null ? ` (${fmtDuration(event.duration_ms)})` : ""}`);
    const summary = eventSummary(event);
    if (summary) lines.push(summary);
    if (event.data) lines.push(JSON.stringify(event.data, null, 2));
    lines.push("");
  }
  return lines.join("\n");
}

function TraceEventRow({ event }: { event: TraceEvent }) {
  const [open, setOpen] = useState(false);
  const hasDetails = Boolean(
    event.data ||
    event.arguments ||
    event.result ||
    event.error ||
    (event.content && event.content.length > 160),
  );
  return (
    <SettingsControlRow
      compact
      leading={eventIcon(event)}
      title={
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate">{eventLabel(event)}</span>
          <StatusBadge label={event.kind === "tool_call" ? "tool" : event.event_type || event.kind || "event"} variant={eventTone(event)} />
        </span>
      }
      description={eventSummary(event)}
      meta={
        <span className="inline-flex items-center gap-1.5">
          <span>{fmtTime(event.created_at)}</span>
          {event.duration_ms != null && <QuietPill label={fmtDuration(event.duration_ms)} />}
        </span>
      }
      onClick={hasDetails ? () => setOpen((value) => !value) : undefined}
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex min-w-0 items-start gap-2.5">
          <div className="mt-0.5 shrink-0 text-text-dim">{eventIcon(event)}</div>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="min-w-0 truncate text-[12px] font-semibold text-text">{eventLabel(event)}</span>
              <StatusBadge label={event.kind === "tool_call" ? "tool" : event.event_type || event.kind || "event"} variant={eventTone(event)} />
              <span className="text-[10px] text-text-dim">{fmtTime(event.created_at)}</span>
              {event.duration_ms != null && <QuietPill label={fmtDuration(event.duration_ms)} />}
            </div>
            <div className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-text-dim">{eventSummary(event)}</div>
          </div>
        </div>
        {open && (
          <pre className="max-h-[320px] overflow-auto rounded-md bg-input/60 p-3 text-[11px] leading-5 text-text-muted">
            {JSON.stringify({
              arguments: event.arguments,
              result: event.result,
              error: event.error,
              data: event.data,
              content: event.content,
            }, null, 2)}
          </pre>
        )}
      </div>
    </SettingsControlRow>
  );
}

export function TraceInspector({
  correlationId,
  title = "Trace",
  subtitle,
  onClose,
  onOpenFullTrace,
  className = "",
}: TraceInspectorProps) {
  const { data, isLoading, error } = useTrace(correlationId || undefined);
  const [copied, setCopied] = useState(false);
  const [filter, setFilter] = useState<TraceFilter>("all");
  const [find, setFind] = useState("");

  const totals = useMemo(() => {
    let tokens = 0;
    let tools = 0;
    let errors = 0;
    for (const event of data?.events ?? []) {
      if (event.event_type === "token_usage") tokens += Number(event.data?.total_tokens ?? 0);
      if (event.kind === "tool_call") tools += 1;
      if (event.event_type === "error" || event.event_type === "llm_error" || event.error) errors += 1;
    }
    return { tokens, tools, errors };
  }, [data]);

  const filteredEvents = useMemo(() => {
    const term = find.trim().toLowerCase();
    return (data?.events ?? []).filter((event) => {
      if (filter !== "all" && eventKind(event) !== filter) return false;
      if (!term) return true;
      return `${eventLabel(event)} ${eventSummary(event)} ${JSON.stringify(event.data ?? {})}`.toLowerCase().includes(term);
    });
  }, [data, filter, find]);

  const handleCopy = async () => {
    if (!data) return;
    await writeToClipboard(formatTraceForCopy(data));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <aside
      className={
        `fixed inset-3 z-40 flex min-h-0 flex-col overflow-hidden rounded-md bg-surface-raised ` +
        `ring-1 ring-surface-border xl:sticky xl:top-3 xl:inset-auto xl:z-auto xl:h-[calc(100vh-180px)] xl:w-[520px] xl:shrink-0 ` +
        className
      }
    >
      <div className="flex shrink-0 items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-1.5">
            <QuietPill label="trace" />
            {correlationId && <span className="truncate font-mono text-[11px] text-text-dim">{correlationId.slice(0, 12)}</span>}
          </div>
          <h3 className="truncate text-[14px] font-semibold text-text">{title}</h3>
          {subtitle && <p className="mt-1 line-clamp-2 text-[12px] text-text-muted">{subtitle}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-[34px] min-w-[34px] shrink-0 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text-muted"
          aria-label="Close trace inspector"
        >
          <X size={15} />
        </button>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pb-3">
        <div className="flex min-h-[34px] min-w-[180px] flex-1 items-center gap-2 rounded-md bg-input px-2.5 text-text-dim focus-within:ring-2 focus-within:ring-accent/25">
          <Search size={13} className="shrink-0" />
          <input
            value={find}
            onChange={(event) => setFind(event.target.value)}
            placeholder="Find in trace..."
            className="min-w-0 flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
          />
        </div>
        <ActionButton
          label={copied ? "Copied" : "Copy"}
          size="small"
          variant="secondary"
          icon={copied ? <Check size={13} /> : <Copy size={13} />}
          disabled={!data}
          onPress={handleCopy}
        />
        {correlationId && onOpenFullTrace && (
          <ActionButton
            label="Open"
            size="small"
            variant="secondary"
            icon={<ExternalLink size={13} />}
            onPress={() => onOpenFullTrace(correlationId)}
          />
        )}
      </div>

      {data && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pb-3 text-[11px] text-text-dim">
          <QuietPill label={`${data.events.length} events`} />
          <QuietPill label={`${fmtTokens(totals.tokens)} tokens`} />
          <QuietPill label={`${totals.tools} tools`} />
          {totals.errors > 0 && <StatusBadge label={`${totals.errors} errors`} variant="danger" />}
          {data.bot_id && <span className="truncate">{data.bot_id}</span>}
        </div>
      )}

      <div className="shrink-0 overflow-x-auto px-4 pb-3">
        <SettingsSegmentedControl<TraceFilter>
          value={filter}
          onChange={setFilter}
          className="w-max"
          options={[
            { value: "all", label: "All" },
            { value: "messages", label: "Messages" },
            { value: "tools", label: "Tools" },
            { value: "usage", label: "Usage" },
            { value: "errors", label: "Errors", count: totals.errors },
          ]}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-input/35 p-3">
        {isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3, 4].map((item) => <div key={item} className="h-12 rounded-md bg-surface-overlay/35" />)}
          </div>
        ) : error || !correlationId ? (
          <EmptyState message="Could not load this trace." />
        ) : filteredEvents.length === 0 ? (
          <EmptyState message="No trace events match the current filter." />
        ) : (
          <div className="flex flex-col gap-1.5">
            {filteredEvents.map((event, index) => <TraceEventRow key={`${event.created_at}-${index}`} event={event} />)}
          </div>
        )}
      </div>
    </aside>
  );
}
