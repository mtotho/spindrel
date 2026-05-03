import { useMemo, useState } from "react";

import {
  useHealthSummaries,
  useLatestHealthSummary,
  type SystemHealthFinding,
  type SystemHealthSummary,
} from "../../api/hooks/useSystemHealth";

interface Props {
  onClose?: () => void;
  embedded?: boolean;
}

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  try {
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return value;
    return dt.toLocaleString();
  } catch {
    return value;
  }
}

function severityClass(severity: SystemHealthFinding["severity"]): string {
  switch (severity) {
    case "critical":
      return "text-danger";
    case "error":
      return "text-warning";
    case "warning":
      return "text-warning/80";
    default:
      return "text-text-muted";
  }
}

function HealthFindingRow({ finding }: { finding: SystemHealthFinding }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md bg-surface-raised/40 px-3 py-2.5">
      <button
        type="button"
        className="flex w-full items-start gap-3 text-left"
        onClick={() => setOpen((prev) => !prev)}
      >
        <span
          className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${
            finding.severity === "critical"
              ? "bg-danger"
              : finding.severity === "error"
                ? "bg-warning"
                : "bg-text-muted/60"
          }`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className={`truncate text-sm font-medium ${severityClass(finding.severity)}`}>
              {finding.title || finding.signature || "Error"}
            </span>
            <span className="shrink-0 text-xs text-text-muted">x{finding.count}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-muted">
            <span>{finding.service}</span>
            <span>last {formatDateTime(finding.last_seen)}</span>
            {finding.kind ? <span>{finding.kind}</span> : null}
          </div>
        </div>
      </button>
      {open ? (
        <pre className="mt-2 max-h-72 overflow-auto rounded bg-surface-overlay/30 px-3 py-2 text-xs text-text-muted">
          {finding.sample}
        </pre>
      ) : null}
    </div>
  );
}

function SummaryHeader({ summary }: { summary: SystemHealthSummary | null }) {
  if (!summary) {
    return (
      <div className="px-4 py-3 text-sm text-text-muted">
        No daily summary has been generated yet. The first run lands at 03:15 UTC.
      </div>
    );
  }
  const services = Object.keys(summary.source_counts || {}).filter((key) => key !== "agent_quality").length;
  const qualityFindings = Number(summary.source_counts?.agent_quality || 0);
  const isClean = summary.error_count === 0 && summary.critical_count === 0;
  return (
    <div className="px-3 py-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold text-text">
          {isClean ? "Clean" : `${summary.error_count} errors`}
          {summary.critical_count > 0 ? (
            <span className="ml-2 text-danger">· {summary.critical_count} critical</span>
          ) : null}
        </span>
        <span className="text-xs text-text-muted">{formatDateTime(summary.generated_at)}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-muted">
        <span>{services} services</span>
        <span>{summary.trace_event_count} trace events</span>
        <span>{summary.tool_error_count} tool errors</span>
        {qualityFindings > 0 ? <span>{qualityFindings} quality findings</span> : null}
      </div>
    </div>
  );
}

export default function SummaryPanel({ onClose, embedded = false }: Props) {
  const latestQuery = useLatestHealthSummary();
  const listQuery = useHealthSummaries(14);
  const summary = latestQuery.data?.summary ?? null;

  const findings = useMemo(() => summary?.findings ?? [], [summary]);
  const previousSummaries = useMemo(() => {
    const all = listQuery.data?.summaries ?? [];
    if (!summary) return all;
    return all.filter((row) => row.id !== summary.id);
  }, [listQuery.data, summary]);

  return (
    <div className={`flex h-full w-full flex-col text-text ${embedded ? "" : "bg-surface-raised"}`}>
      {!embedded ? (
        <header className="flex items-center justify-between px-4 py-3">
          <div>
            <div className="text-sm font-semibold">Daily Health Summary</div>
            <div className="text-xs text-text-muted">Deterministic 24h server-error rollup</div>
          </div>
          {onClose ? (
            <button
              type="button"
              className="rounded px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text"
              onClick={onClose}
            >
              Close
            </button>
          ) : null}
        </header>
      ) : null}

      <SummaryHeader summary={summary} />

      <div className="flex-1 space-y-2 overflow-auto px-3 pb-3">
        {latestQuery.isLoading ? (
          <div className="px-3 py-2 text-sm text-text-muted">Loading...</div>
        ) : findings.length === 0 ? (
          <div className="px-3 py-2 text-sm text-text-muted">
            {summary ? "No findings in the last window." : ""}
          </div>
        ) : (
          findings.map((f) => <HealthFindingRow key={f.dedupe_key} finding={f} />)
        )}
      </div>

      {previousSummaries.length > 0 ? (
        <details className="px-3 py-2 text-xs text-text-muted">
          <summary className="cursor-pointer select-none">
            Previous summaries ({previousSummaries.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {previousSummaries.map((row) => (
              <li key={row.id} className="flex items-baseline justify-between gap-2">
                <span>{formatDateTime(row.generated_at)}</span>
                <span>
                  {row.error_count} errors
                  {row.critical_count > 0 ? ` · ${row.critical_count} critical` : ""}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
