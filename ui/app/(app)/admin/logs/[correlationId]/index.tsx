import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Check, Copy, Search } from "lucide-react";

import { useTrace, type TraceDetailResponse } from "@/src/api/hooks/useLogs";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { ActionButton, EmptyState, QuietPill, SettingsSegmentedControl, StatusBadge } from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import {
  fmtTraceDuration,
  fmtTraceTime,
  fmtTraceTokens,
  TRACE_FILTER_OPTIONS,
  traceEventLabel,
  traceEventMatches,
  traceEventSummary,
  traceTotals,
  TraceTimeline,
  type TraceFilter,
} from "@/src/components/shared/TraceTimeline";
import { writeToClipboard } from "@/src/utils/clipboard";

function formatTraceForCopy(data: TraceDetailResponse): string {
  const lines: string[] = [];
  lines.push("=== Request Trace ===");
  lines.push(`Correlation: ${data.correlation_id}`);
  if (data.bot_id) lines.push(`Bot: ${data.bot_id}`);
  if (data.session_id) lines.push(`Session: ${data.session_id}`);
  if (data.client_id) lines.push(`Client: ${data.client_id}`);
  if (data.time_range_start && data.time_range_end) {
    lines.push(`Time: ${fmtTraceTime(data.time_range_start)} - ${fmtTraceTime(data.time_range_end)}`);
  }
  lines.push("");

  for (const event of data.events) {
    lines.push(`[${fmtTraceTime(event.created_at)}] ${traceEventLabel(event)}${event.duration_ms != null ? ` (${fmtTraceDuration(event.duration_ms)})` : ""}`);
    const summary = traceEventSummary(event);
    if (summary) lines.push(summary);
    if (event.arguments) lines.push(JSON.stringify(event.arguments, null, 2));
    if (event.data) lines.push(JSON.stringify(event.data, null, 2));
    if (event.result) lines.push(event.result);
    if (event.error) lines.push(`ERROR: ${event.error}`);
    lines.push("");
  }
  return lines.join("\n");
}

export default function TraceScreen() {
  const navigate = useNavigate();
  const { correlationId } = useParams<{ correlationId: string }>();
  const { data, isLoading, error } = useTrace(correlationId);
  const [copied, setCopied] = useState(false);
  const [filter, setFilter] = useState<TraceFilter>("all");
  const [find, setFind] = useState("");

  const totals = useMemo(() => traceTotals(data?.events ?? []), [data]);
  const filteredEvents = useMemo(
    () => (data?.events ?? []).filter((event) => traceEventMatches(event, filter, find)),
    [data, filter, find],
  );

  const handleCopy = async () => {
    if (!data) return;
    await writeToClipboard(formatTraceForCopy(data));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <Spinner />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <EmptyState message="Trace not found." />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Logs"
        onBack={() => window.history.length > 1 ? navigate(-1) : navigate("/admin/logs")}
        title="Request Trace"
        subtitle={correlationId}
        right={
          <ActionButton
            label={copied ? "Copied" : "Copy"}
            variant="secondary"
            size="small"
            icon={copied ? <Check size={13} /> : <Copy size={13} />}
            onPress={handleCopy}
          />
        }
      />

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-surface-overlay/45 px-4 py-3 text-[11px] text-text-dim lg:px-6">
        <QuietPill label={`${data.events.length} events`} />
        <QuietPill label={`${fmtTraceTokens(totals.tokens)} tokens`} />
        <QuietPill label={`${totals.tools} tools`} />
        {totals.errors > 0 && <StatusBadge label={`${totals.errors} errors`} variant="danger" />}
        {data.bot_id && <span>Bot: {data.bot_id}</span>}
        {data.session_id && <span className="font-mono">Session: {data.session_id.slice(0, 12)}</span>}
        {data.time_range_start && data.time_range_end && (
          <span>{fmtTraceTime(data.time_range_start)} - {fmtTraceTime(data.time_range_end)}</span>
        )}
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-surface-overlay/45 px-4 py-3 lg:px-6">
        <div className="flex min-h-[34px] min-w-[220px] flex-1 items-center gap-2 rounded-md bg-input px-2.5 text-text-dim focus-within:ring-2 focus-within:ring-accent/25">
          <Search size={13} className="shrink-0" />
          <input
            value={find}
            onChange={(event) => setFind(event.target.value)}
            placeholder="Find in trace..."
            className="min-w-0 flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
          />
        </div>
        <div className="overflow-x-auto">
          <SettingsSegmentedControl<TraceFilter>
            value={filter}
            onChange={setFilter}
            className="w-max"
            options={TRACE_FILTER_OPTIONS.map((option) => ({
              ...option,
              count: option.value === "errors" ? totals.errors : undefined,
            }))}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-4 lg:px-6">
        <TraceTimeline events={filteredEvents} />
      </div>
    </div>
  );
}
