import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { Check, Copy, ExternalLink, Search, X } from "lucide-react";

import { useTrace, type TraceDetailResponse } from "@/src/api/hooks/useLogs";
import { useTraceInspectorStore } from "@/src/stores/traceInspector";
import { writeToClipboard } from "@/src/utils/clipboard";
import { ActionButton, EmptyState, QuietPill, SettingsSegmentedControl, StatusBadge } from "./SettingsControls";
import {
  fmtTraceDuration,
  fmtTraceTime,
  fmtTraceTokens,
  TRACE_FILTER_OPTIONS,
  traceEventMatches,
  traceEventSummary,
  traceEventLabel,
  traceTotals,
  TraceTimeline,
  type TraceFilter,
} from "./TraceTimeline";

function formatTraceForCopy(data: TraceDetailResponse): string {
  const lines = [`Trace ${data.correlation_id}`];
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

export function TraceInspectorRoot({ disabled = false }: { disabled?: boolean }) {
  const request = useTraceInspectorStore((state) => state.request);
  const closeTrace = useTraceInspectorStore((state) => state.closeTrace);
  const navigate = useNavigate();
  const location = useLocation();
  const { data, isLoading, error } = useTrace(disabled ? undefined : request?.correlationId);
  const [copied, setCopied] = useState(false);
  const [filter, setFilter] = useState<TraceFilter>("all");
  const [find, setFind] = useState("");

  useEffect(() => {
    if (!request) return;
    setFilter("all");
    setFind("");
    setCopied(false);
  }, [request?.correlationId]);

  useEffect(() => {
    if (!request) return;
    closeTrace();
  }, [location.pathname, location.search, closeTrace]);

  useEffect(() => {
    if (!request) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeTrace();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [request, closeTrace]);

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

  if (disabled || !request || typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-[10060]">
      <button
        type="button"
        aria-label="Close trace inspector"
        className="absolute inset-0 bg-black/45 backdrop-blur-[2px]"
        onClick={closeTrace}
      />
      <aside
        role="dialog"
        aria-label="Trace inspector"
        className="absolute bottom-0 right-0 top-0 flex w-full max-w-full flex-col border-l border-surface-border bg-surface-raised shadow-2xl sm:w-[620px]"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-surface-border px-4 py-3">
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-1.5">
              <QuietPill label="trace" />
              <span className="truncate font-mono text-[11px] text-text-dim">
                {request.correlationId.slice(0, 12)}
              </span>
            </div>
            <h3 className="truncate text-[15px] font-semibold text-text">{request.title || "Trace"}</h3>
            <p className="mt-1 line-clamp-2 text-[12px] text-text-muted">
              {request.subtitle || request.correlationId}
            </p>
          </div>
          <button
            type="button"
            onClick={closeTrace}
            className="inline-flex min-h-[34px] min-w-[34px] shrink-0 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text-muted"
            aria-label="Close trace inspector"
          >
            <X size={15} />
          </button>
        </header>

        <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 py-3">
          <div className="flex min-h-[34px] min-w-[190px] flex-1 items-center gap-2 rounded-md bg-input px-2.5 text-text-dim focus-within:ring-2 focus-within:ring-accent/25">
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
          <ActionButton
            label="Open"
            size="small"
            variant="secondary"
            icon={<ExternalLink size={13} />}
            onPress={() => {
              const id = request.correlationId;
              closeTrace();
              navigate(`/admin/logs/${id}`);
            }}
          />
        </div>

        {data && (
          <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pb-3 text-[11px] text-text-dim">
            <QuietPill label={`${data.events.length} events`} />
            <QuietPill label={`${fmtTraceTokens(totals.tokens)} tokens`} />
            <QuietPill label={`${totals.tools} tools`} />
            {data.time_range_start && data.time_range_end && (
              <QuietPill label={`${fmtTraceTime(data.time_range_start)} - ${fmtTraceTime(data.time_range_end)}`} maxWidthClass="max-w-[180px]" />
            )}
            {totals.errors > 0 && <StatusBadge label={`${totals.errors} errors`} variant="danger" />}
            {data.bot_id && <span className="truncate">{data.bot_id}</span>}
          </div>
        )}

        <div className="shrink-0 overflow-x-auto px-4 pb-3">
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

        <div className="min-h-0 flex-1 overflow-y-auto bg-input/35 px-4 py-4">
          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2, 3, 4, 5].map((item) => <div key={item} className="h-16 rounded-md bg-surface-overlay/35" />)}
            </div>
          ) : error ? (
            <EmptyState message="Could not load this trace." />
          ) : (
            <TraceTimeline events={filteredEvents} />
          )}
        </div>
      </aside>
    </div>,
    document.body,
  );
}
