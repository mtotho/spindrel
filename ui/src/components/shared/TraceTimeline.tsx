import { useState } from "react";
import { AlertTriangle, Bot, ChevronDown, ChevronRight, Code2, MessageSquare, Wrench } from "lucide-react";

import type { TraceEvent } from "@/src/api/hooks/useLogs";
import { QuietPill, StatusBadge } from "./SettingsControls";

export type TraceFilter = "all" | "messages" | "tools" | "usage" | "errors";

export const TRACE_FILTER_OPTIONS: Array<{ value: TraceFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "messages", label: "Messages" },
  { value: "tools", label: "Tools" },
  { value: "usage", label: "Usage" },
  { value: "errors", label: "Errors" },
];

export function fmtTraceTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function fmtTraceDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function fmtTraceTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function traceEventType(event: TraceEvent): string {
  if (event.kind === "tool_call") return "tool_call";
  if (event.kind === "message") return "message";
  return event.event_type || "trace_event";
}

export function traceEventKind(event: TraceEvent): TraceFilter {
  if (event.kind === "message") return "messages";
  if (event.kind === "tool_call") return "tools";
  if (event.event_type === "token_usage") return "usage";
  if (event.event_type === "error" || event.event_type === "llm_error" || event.error) return "errors";
  return "all";
}

export function traceEventLabel(event: TraceEvent): string {
  if (event.kind === "message") return event.role === "user" ? "User message" : "Assistant response";
  if (event.kind === "tool_call") return event.tool_name || "Tool call";
  return event.event_name || event.event_type || "Trace event";
}

export function traceEventSummary(event: TraceEvent): string {
  if (event.kind === "message") {
    const content = event.content || "";
    return content.length > 220 ? `${content.slice(0, 220)}...` : content || "Empty message";
  }
  if (event.kind === "tool_call") {
    if (event.error) return event.error;
    if (event.result) return event.result.length > 180 ? `${event.result.slice(0, 180)}...` : event.result;
    return event.tool_type ? `${event.tool_type} tool` : "Tool call";
  }
  if (event.event_type === "token_usage" && event.data) {
    const total = Number(event.data.total_tokens ?? 0);
    const prompt = Number(event.data.prompt_tokens ?? 0);
    const completion = Number(event.data.completion_tokens ?? 0);
    return `${fmtTraceTokens(total)} tokens (${fmtTraceTokens(prompt)} in / ${fmtTraceTokens(completion)} out)`;
  }
  if (event.error) return event.error;
  if (event.data) return JSON.stringify(event.data).slice(0, 220);
  return event.event_type || "Trace event";
}

export function traceEventMatches(event: TraceEvent, filter: TraceFilter, query: string): boolean {
  if (filter !== "all" && traceEventKind(event) !== filter) return false;
  const term = query.trim().toLowerCase();
  if (!term) return true;
  return `${traceEventLabel(event)} ${traceEventSummary(event)} ${JSON.stringify(event.data ?? {})} ${JSON.stringify(event.arguments ?? {})}`
    .toLowerCase()
    .includes(term);
}

export function traceTotals(events: TraceEvent[]) {
  let tokens = 0;
  let tools = 0;
  let errors = 0;
  for (const event of events) {
    if (event.event_type === "token_usage") tokens += Number(event.data?.total_tokens ?? 0);
    if (event.kind === "tool_call") tools += 1;
    if (event.event_type === "error" || event.event_type === "llm_error" || event.error) errors += 1;
  }
  return { tokens, tools, errors };
}

function eventIcon(event: TraceEvent) {
  if (event.kind === "message") return <MessageSquare size={14} />;
  if (event.kind === "tool_call") return <Wrench size={14} />;
  if (event.event_type === "token_usage") return <Code2 size={14} />;
  if (event.event_type === "error" || event.event_type === "llm_error" || event.error) return <AlertTriangle size={14} />;
  return <Code2 size={14} />;
}

function eventTone(event: TraceEvent): "neutral" | "info" | "warning" | "danger" | "success" | "purple" {
  if (event.event_type === "error" || event.event_type === "llm_error" || event.error) return "danger";
  if (event.kind === "tool_call") return event.error ? "danger" : "info";
  if (event.event_type === "token_usage") return "neutral";
  if (event.kind === "message") return event.role === "user" ? "purple" : "success";
  if (event.event_type?.includes("retrieval")) return "warning";
  return "neutral";
}

function dotClass(event: TraceEvent) {
  const tone = eventTone(event);
  if (tone === "danger") return "bg-danger";
  if (tone === "warning") return "bg-warning";
  if (tone === "success") return "bg-success";
  if (tone === "purple") return "bg-purple";
  if (tone === "info") return "bg-accent";
  return "bg-text-dim";
}

function jsonDetails(event: TraceEvent) {
  return {
    arguments: event.arguments,
    result: event.result,
    error: event.error,
    data: event.data,
    content: event.content,
  };
}

function hasDetails(event: TraceEvent) {
  return Boolean(
    event.data ||
    event.arguments ||
    event.result ||
    event.error ||
    (event.content && event.content.length > 240),
  );
}

function DiscoverySummary({ events }: { events: TraceEvent[] }) {
  const event = events.find((candidate) => candidate.event_type === "discovery_summary");
  if (!event?.data) return null;
  const skills = (event.data.skills || {}) as any;
  const tools = (event.data.tools || {}) as any;
  const autoInjected = skills.auto_injected || [];
  const retrieved = tools.retrieved || [];
  const hasSkills = (skills.enrolled_count ?? 0) > 0 || (skills.discoverable_unenrolled_count ?? 0) > 0;
  const hasTools = tools.tool_retrieval_enabled || retrieved.length > 0;
  if (!hasSkills && !hasTools) return null;

  return (
    <div className="mb-4 rounded-md bg-surface-raised/45 px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
        <Bot size={12} />
        Discovery
      </div>
      <div className="grid gap-2 text-[12px] text-text-muted">
        {hasSkills && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">Skills</span>
            <QuietPill label={`${skills.enrolled_count ?? 0} enrolled`} />
            {(skills.relevant_count ?? 0) > 0 && <QuietPill label={`${skills.relevant_count} relevant`} className="text-success" />}
            {autoInjected.length > 0 && <QuietPill label={`${autoInjected.length} auto-injected`} className="text-purple" />}
            {(skills.discoverable_unenrolled_count ?? 0) > 0 && <QuietPill label={`${skills.discoverable_unenrolled_count} discoverable`} />}
          </div>
        )}
        {hasTools && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">Tools</span>
            <QuietPill label={`${(tools.pinned || []).length} pinned`} />
            <QuietPill label={`${(tools.included || []).length} included`} />
            <QuietPill label={`${tools.retrieved_count ?? retrieved.length} retrieved`} className={(tools.retrieved_count ?? 0) > 0 ? "text-warning-muted" : ""} />
            {(tools.unretrieved_count ?? 0) > 0 && <QuietPill label={`${tools.unretrieved_count} index-only`} />}
            {retrieved.length > 0 && (
              <span className="min-w-0 truncate text-[11px] text-text-dim">
                {retrieved.slice(0, 5).join(", ")}{retrieved.length > 5 ? ` +${retrieved.length - 5}` : ""}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function TraceTimelineEvent({ event }: { event: TraceEvent }) {
  const [open, setOpen] = useState(false);
  const expandable = hasDetails(event);
  const tone = eventTone(event);
  const type = traceEventType(event);
  const isMessage = event.kind === "message";

  return (
    <div className="relative pb-3 pl-6">
      <div className={`absolute left-[-5px] top-3 h-2.5 w-2.5 rounded-full ring-4 ring-surface ${dotClass(event)}`} />
      <button
        type="button"
        disabled={!expandable}
        onClick={() => expandable && setOpen((value) => !value)}
        className={
          `w-full rounded-md bg-surface-raised/45 px-3 py-2.5 text-left transition-colors ` +
          (expandable ? "hover:bg-surface-overlay/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35" : "")
        }
      >
        <div className="flex min-w-0 items-start gap-2.5">
          <div className="mt-0.5 shrink-0 text-text-dim">{eventIcon(event)}</div>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="min-w-0 truncate text-[12px] font-semibold text-text">
                {traceEventLabel(event)}
              </span>
              <StatusBadge label={isMessage ? "message" : type} variant={tone} />
              <span className="text-[10px] text-text-dim">{fmtTraceTime(event.created_at)}</span>
              {event.duration_ms != null && <QuietPill label={fmtTraceDuration(event.duration_ms)} />}
              {event.count != null && <QuietPill label={`${event.count} items`} />}
              {event.kind === "tool_call" && event.tool_type && <QuietPill label={event.tool_type} />}
            </div>
            <div className="mt-1 line-clamp-3 text-[11px] leading-snug text-text-dim">
              {traceEventSummary(event)}
            </div>
          </div>
          {expandable && (
            <span className="mt-1 shrink-0 text-text-dim">
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
          )}
        </div>
      </button>
      {open && (
        <pre className="mt-1.5 max-h-[360px] overflow-auto rounded-md bg-input/60 p-3 text-[11px] leading-5 text-text-muted">
          {JSON.stringify(jsonDetails(event), null, 2)}
        </pre>
      )}
    </div>
  );
}

export function TraceTimeline({
  events,
  emptyMessage = "No trace events match the current filter.",
  showDiscoverySummary = true,
}: {
  events: TraceEvent[];
  emptyMessage?: string;
  showDiscoverySummary?: boolean;
}) {
  if (events.length === 0) {
    return <div className="rounded-md bg-surface-raised/35 px-4 py-6 text-center text-[13px] text-text-dim">{emptyMessage}</div>;
  }
  return (
    <div>
      {showDiscoverySummary && <DiscoverySummary events={events} />}
      <div className="relative ml-2 border-l-2 border-surface-overlay">
        {events.map((event, index) => (
          <TraceTimelineEvent key={`${event.created_at}-${traceEventType(event)}-${index}`} event={event} />
        ))}
      </div>
    </div>
  );
}
