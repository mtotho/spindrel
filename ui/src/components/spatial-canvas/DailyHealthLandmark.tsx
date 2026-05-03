import { Activity } from "lucide-react";

import { useLatestHealthSummary } from "../../api/hooks/useSystemHealth";

interface Props {
  zoom: number;
  onOpen: () => void;
}

function formatRelative(value: string | null | undefined): string {
  if (!value) return "never";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "never";
  const diff = Date.now() - dt.getTime();
  if (diff < 0) return "now";
  const min = Math.round(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.round(hr / 24);
  return `${d}d ago`;
}

/**
 * Daily Health Summary landmark — sibling to the Attention Hub.
 * Persistent canvas tile that surfaces a non-LLM, server-side rollup of
 * yesterday's errors. Click to open the SummaryPanel.
 */
export default function DailyHealthLandmark({ zoom, onOpen }: Props) {
  const { data } = useLatestHealthSummary();
  const summary = data?.summary ?? null;

  const compact = zoom < 0.45;
  const size = compact ? 156 : 180;
  const errorCount = summary?.error_count ?? 0;
  const criticalCount = summary?.critical_count ?? 0;
  const qualityFindings = Number(summary?.source_counts?.agent_quality || 0);
  const services = summary
    ? Object.keys(summary.source_counts || {}).filter((key) => key !== "agent_quality").length
    : 0;
  const isClean = !!summary && errorCount === 0 && criticalCount === 0;

  const accent =
    summary === null
      ? "border-surface-border/60 text-text-muted"
      : criticalCount > 0
        ? "border-danger/45 text-danger"
        : errorCount > 0
          ? "border-warning/45 text-warning"
          : "border-success/40 text-success";

  return (
    <button
      type="button"
      className={`absolute flex flex-col items-center justify-center rounded-full border bg-surface-raised/85 text-text backdrop-blur transition-colors hover:bg-surface-hover ${accent}`}
      style={{
        left: -size / 2,
        top: -size / 2,
        width: size,
        height: size,
        zIndex: 4,
      }}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onOpen();
      }}
      title="Open Daily Health Summary"
    >
      <Activity size={compact ? 36 : 44} />
      {!compact ? <span className="mt-2 text-sm font-semibold">Daily Health</span> : null}
      {summary === null ? (
        <span className="mt-1 text-[11px] font-medium text-text-muted">Pending first run</span>
      ) : isClean ? (
        <span className="mt-1 text-[11px] font-medium">
          {qualityFindings > 0 ? `${qualityFindings} quality` : "Clean"} ·{" "}
          {formatRelative(summary.generated_at)}
        </span>
      ) : (
        <span className="mt-1 text-[11px] font-medium">
          {errorCount} err{criticalCount > 0 ? ` · ${criticalCount} crit` : ""} · {services}{" "}
          svc
        </span>
      )}
    </button>
  );
}
